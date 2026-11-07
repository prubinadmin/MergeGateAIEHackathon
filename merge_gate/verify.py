"""The gate: run every check, then decide in plain code (owner: Michael)."""

from __future__ import annotations

import time

from .pr import PullRequest
from .rules import check_rules
from .schema import Evidence, Owner, Verdict, VerdictReport, owner_key, run_hash

GATE_VERSION = "v1"

SUMMARY_PROMPT = """You write the iMessage a senior engineer gets when someone else's pull request changes code they wrote.
At most two short sentences, under 35 words in total, plain English, no markdown, no greeting.
Sentence 1: who changed which of their functions, in everyday words. Sentence 2: the single most serious finding,
as a concrete consequence (for example "a 150% discount now returns -5.0"). Do not restate the verdict, rule ids or
test names. State only facts given to you. Do not tell them what to reply."""


def decide(evidence: list[Evidence]) -> Verdict:
    """Deterministic verdict. No LLM.

    Any block-severity evidence -> BLOCK; else any review-severity -> REVIEW; else PASS.
    """
    if any(e.severity == "block" for e in evidence):
        return "BLOCK"
    if evidence:
        return "REVIEW"
    return "PASS"


def template_summary(pr: PullRequest, verdict: Verdict, evidence: list[Evidence]) -> str:
    files = ", ".join(f for f in pr.changed_files() if f.endswith(".py"))[:120] or "your code"
    who = pr.opened_by or "Someone"
    if not evidence:
        return f"{who}'s PR changes {files}. The gate's checks all passed."
    return f"{who}'s PR changes {files}. {evidence[0].detail}."


def llm_summary(pr: PullRequest, verdict: Verdict, evidence: list[Evidence], owner: Owner | None) -> str:
    from . import llm

    facts = [
        f"PR title: {pr.title or '(none)'}",
        f"Opened by: {pr.opened_by or 'unknown'}",
        f"Files changed: {', '.join(pr.changed_files())}",
        f"Recipient wrote {owner.lines} of the changed lines" if owner else "Recipient: code owner",
        f"Gate verdict: {verdict}",
    ] + [f"Finding: {e.detail}" for e in evidence[:3]]
    try:
        text = llm.complete(SUMMARY_PROMPT, "\n".join(facts)).strip()
    except llm.LLMError:
        return template_summary(pr, verdict, evidence)
    return text[:400] if text else template_summary(pr, verdict, evidence)


# --- verify() stages. Each emits exactly its own on_stage events (the UI's live lanes); verify() keeps the order.


def _emitter(on_stage):
    def emit(name: str, status: str, **data) -> None:
        if on_stage:
            on_stage(name, status, data)

    return emit


def _timed(emit, name: str, fn):
    emit(name, "start")
    t0 = time.monotonic()
    out = fn()
    return out, int((time.monotonic() - t0) * 1000)


def _run_rules(pr: PullRequest, steps: dict, emit) -> list[Evidence]:
    raw, ms = _timed(emit, "rules", lambda: list(steps.get("rules", check_rules)(pr)))
    emit("rules", "done", ms=ms, evidence=[e.__dict__ for e in raw])
    return raw


def _run_owners(pr: PullRequest, steps: dict, emit) -> list[Owner]:
    from .owners import resolve_owners

    owners, ms = _timed(emit, "owners", lambda: steps.get("owners", resolve_owners)(pr))
    emit("owners", "done", ms=ms, owners=[o.__dict__ for o in owners])
    return owners


def _run_testgen(pr: PullRequest, timeout_s: int, steps: dict, emit) -> tuple[list[Evidence], list[str]]:
    """Muse's spec-only tests: (evidence, notes for the summary)."""
    from .testgen import independent_check

    tg, ms = _timed(emit, "testgen", lambda: steps.get("testgen", independent_check)(pr, timeout_s))
    notes: list[str] = []
    if tg.error:
        notes.append(tg.error)
    elif tg.dropped_invariants:
        notes.append(f"dropped {len(tg.dropped_invariants)} generated tests that failed on base")
    emit(
        "testgen", "done", ms=ms, error=tg.error, source=tg.source,
        kept=tg.kept_invariants, dropped=tg.dropped_invariants,
        base={"passed": tg.base.passed, "failed": len(tg.base.failed), "hash": tg.base.output_hash} if tg.base else None,
        head={"passed": tg.head.passed, "failed": len(tg.head.failed), "hash": tg.head.output_hash} if tg.head else None,
        evidence=[e.__dict__ for e in tg.evidence],
    )
    return tg.evidence, notes


def _run_owner_tests(pr: PullRequest, timeout_s: int, emit) -> list[Evidence]:
    from .owner_tests import check_owner_tests

    # stored owner rules: running them needs no model, so they run with or without Muse
    ot, ms = _timed(emit, "owner_tests", lambda: check_owner_tests(pr, timeout_s))
    emit("owner_tests", "done", ms=ms, evidence=[e.__dict__ for e in ot])
    return ot


def _route(pr: PullRequest, owners: list[Owner], evidence: list[Evidence], verdict: Verdict, use_subq: bool,
           emit) -> tuple[list[Owner], dict]:
    """(owners, report routing fields): SubQ reorders owners when opted in and keyed, else blame order stands."""
    from . import subq

    if not (use_subq and subq.has_key()):
        emit("routing", "skipped", reason="no SUBQ_API_KEY or --no-subq")
        return owners, {}
    (owners, routing), ms = _timed(emit, "routing", lambda: subq.route(pr, owners, evidence, verdict))
    emit("routing", "done", ms=ms, to=owners[0].__dict__ if owners else None,
         **{"routed_by": "blame", "route_confidence": None, "urgency_p": None, **routing})
    return owners, routing


def _summarize(pr: PullRequest, verdict: Verdict, evidence: list[Evidence], owners: list[Owner], use_llm: bool,
               emit) -> str:
    if use_llm:
        summary, ms = _timed(emit, "summary", lambda: llm_summary(pr, verdict, evidence, owners[0] if owners else None))
    else:
        summary, ms = _timed(emit, "summary", lambda: template_summary(pr, verdict, evidence))
    emit("summary", "done", ms=ms, summary=summary)
    return summary


def verify(pr: PullRequest, use_llm: bool = False, timeout_s: int = 60, config="current", on_stage=None,
           use_subq: bool = False, steps: dict | None = None) -> VerdictReport:
    """use_llm=True adds Muse Spark's spec-only tests and the plain-English summary. Owners' stored rules always run.

    use_subq=True lets SubQ Snap pick owners[0] among eligible owners and the urgency, when SUBQ_API_KEY is set
    (independent of use_llm). It only routes; decide() stays code.
    steps: optional replacements for the specialist stages (the Fetch.ai agent team runs them as separate agents).

    config: "current" = the adopted gate version in gate_versions/, None = raw rules (used by the learner).
    on_stage(name, status, data): called as each real stage starts and finishes (the UI's live lanes).
    steps: optional {"rules", "owners", "testgen"} -> callables that replace the in-process step (the Fetch.ai
    agent team passes its specialists' results here). decide(), the summary and run_hash stay here.
    """
    steps = steps or {}
    emit = _emitter(on_stage)

    evidence: list[Evidence] = _run_rules(pr, steps, emit)
    owners = _run_owners(pr, steps, emit)

    notes: list[str] = []
    if use_llm:
        tg_evidence, notes = _run_testgen(pr, timeout_s, steps, emit)
        evidence = evidence + tg_evidence
    else:
        emit("testgen", "skipped", reason="no MUSE_API_KEY or --no-llm")
    evidence = evidence + _run_owner_tests(pr, timeout_s, emit)

    from .learn import apply_config, load_current

    cfg = load_current() if config == "current" else config
    evidence = apply_config(evidence, cfg)
    gate_version = cfg.version if cfg else GATE_VERSION
    verdict = decide(evidence)
    emit("decide", "done", ms=0, verdict=verdict, gate_version=gate_version)

    blame_owner = owner_key(owners[0]) if owners else ""
    owners, routing = _route(pr, owners, evidence, verdict, use_subq, emit)
    summary = _summarize(pr, verdict, evidence, owners, use_llm, emit)

    report = VerdictReport(
        pr_id=pr.pr_id,
        verdict=verdict,
        evidence=evidence,
        owners=owners,
        summary=summary + (f" [{'; '.join(notes)}]" if notes else ""),
        gate_version=gate_version,
        blame_owner=blame_owner,
        opened_by=pr.opened_by,
        **routing,
    )
    report.run_hash = run_hash(
        {
            "pr": [pr.pr_id, pr.base_ref, pr.head_ref, pr.issue_text],
            "verdict": verdict,
            "evidence": [e.__dict__ for e in evidence],
            "owners": [o.email for o in owners],
            "gate": gate_version,
            "routing": [report.routed_by, report.route_confidence, report.urgency],
        }
    )
    return report


def harden_gate(attacker_evasion: dict, candidate_rule_id: str | None = None, bench_root: str = "benchmark",
                use_llm: bool = False) -> dict:
    """An attacker PR got past the gate: run one real learning round and report what it measured.

    attacker_evasion: {"pr_id": <benchmark case id that got through>, "kind": ..., "description": ...}.
    The bypass must be a labelled train-split case, so the learner can see it was missed; candidate
    rule changes are scored on the held-out split and adopted only if catch rate does not drop and
    false blocks do not rise (merge_gate/learn.py). Nothing here reports a result it did not compute.
    """
    from .bench import load_cases
    from .learn import collect_raw, false_alarms_from_log, learn_round

    cases = load_cases(bench_root)
    if not cases:
        return {"hardened": False, "reason": f"no benchmark cases under {bench_root}/cases to validate a patch against"}
    pr_id = attacker_evasion.get("pr_id")
    known = {c.pr.pr_id: c for c in cases}
    if pr_id and pr_id not in known:
        return {"hardened": False, "reason": f"{pr_id} is not a labelled benchmark case; add it to the train split first"}
    if pr_id and known[pr_id].label.split != "train":
        return {"hardened": False, "reason": f"{pr_id} is held out; learning from it would contaminate the score"}

    raw = collect_raw(cases, use_llm=use_llm)
    result = learn_round(cases, raw, false_alarms_from_log())
    return {
        "hardened": result["adopted"] is not None,
        "from_version": result["from"],
        "new_version": result["to"],
        "adopted_change": result["adopted"],
        "requested_rule": candidate_rule_id,
        "attack": attacker_evasion.get("description", ""),
        "heldout_before": result["heldout_before"],
        "heldout_after": result["heldout_after"],
        "candidates": result["candidates"],
    }
