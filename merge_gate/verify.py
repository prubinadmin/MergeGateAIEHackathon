"""The gate: run every check, then decide in plain code (owner: Michael)."""

from __future__ import annotations

from .pr import PullRequest
from .rules import check_rules
from .schema import Evidence, Owner, Verdict, VerdictReport, run_hash

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


def verify(pr: PullRequest, use_llm: bool = False, timeout_s: int = 60, config="current") -> VerdictReport:
    """use_llm=True adds Muse Spark's spec-only tests and the plain-English summary.

    config: "current" = the adopted gate version in gate_versions/, None = raw rules (used by the learner).
    """
    evidence: list[Evidence] = list(check_rules(pr))
    notes: list[str] = []

    if use_llm:
        from .testgen import independent_check

        tg = independent_check(pr, timeout_s)
        evidence.extend(tg.evidence)
        if tg.error:
            notes.append(tg.error)
        elif tg.dropped_invariants:
            notes.append(f"dropped {len(tg.dropped_invariants)} generated tests that failed on base")

    from .learn import apply_config, load_current
    from .owners import resolve_owners

    cfg = load_current() if config == "current" else config
    evidence = apply_config(evidence, cfg)
    gate_version = cfg.version if cfg else GATE_VERSION
    owners: list[Owner] = resolve_owners(pr)
    verdict = decide(evidence)
    summary = (
        llm_summary(pr, verdict, evidence, owners[0] if owners else None)
        if use_llm
        else template_summary(pr, verdict, evidence)
    )
    report = VerdictReport(
        pr_id=pr.pr_id,
        verdict=verdict,
        evidence=evidence,
        owners=owners,
        summary=summary + (f" [{'; '.join(notes)}]" if notes else ""),
        gate_version=gate_version,
    )
    report.run_hash = run_hash(
        {
            "pr": [pr.pr_id, pr.base_ref, pr.head_ref, pr.issue_text],
            "verdict": verdict,
            "evidence": [e.__dict__ for e in evidence],
            "owners": [o.email for o in owners],
            "gate": gate_version,
        }
    )
    return report
