"""The system that gets better (owner: Michael).

A gate version is a rule configuration: for each rule id, "block", "review" or "off".
Proposals come from evidence, never from a model:
  - an owner replies FALSE ALARM          -> propose downgrading the rules that fired (block -> review -> off)
  - a bad train-split PR got through      -> propose upgrading/enabling the rules that saw it
Each proposal is scored on the HELD-OUT split only. It is adopted when held-out catch rate does not
drop, false-block rate does not rise, and at least one of them improves. Otherwise it is rolled back.
A proposal that would newly block a clean TRAIN PR (a label the learner already has) is vetoed outright.
Every proposal, score and decision goes into gate_versions/ and the hash-chained run log.

Raw evidence per case is computed once; scoring a configuration only re-runs decide(), so a learning
round costs no extra model calls.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field

from . import store
from .bench import Case, score
from .schema import Evidence, VerdictReport

VERSIONS_DIR = "gate_versions"
LEVELS = ("off", "review", "block")


@dataclass
class GateConfig:
    version: str = "v1"
    rule_severity: dict[str, str] = field(default_factory=dict)  # rule id -> off|review|block
    parent: str = ""
    change: str = ""  # one line: what this version changed


def knob(e: Evidence) -> str:
    """The setting that controls this evidence: its rule id, or the class of a gate test (gate::test_issue, gate::test_invariant)."""
    if e.type == "rule":
        return e.id.split("::")[0]
    name = e.id.split("::")[-1]
    for cls in ("test_issue", "test_invariant"):
        if name.startswith(cls):
            return f"gate::{cls}"
    return e.id


def apply_config(evidence: list[Evidence], cfg: GateConfig | None) -> list[Evidence]:
    if not cfg or not cfg.rule_severity:
        return evidence
    out = []
    for e in evidence:
        if e.id.startswith("owner::"):  # an owner's own rule: learned config never mutes or downgrades it
            out.append(e)
            continue
        level = cfg.rule_severity.get(e.id) or cfg.rule_severity.get(knob(e))
        if level == "off":
            continue
        if level in ("block", "review"):
            e = copy.copy(e)
            e.severity = level  # type: ignore[assignment]
        out.append(e)
    return out


def _rule_level(cfg: GateConfig, rule_id: str, default: str) -> str:
    return cfg.rule_severity.get(rule_id, default)


def rescore(raw: dict[str, VerdictReport], cfg: GateConfig) -> dict[str, VerdictReport]:
    from .verify import decide

    out = {}
    for pr_id, r in raw.items():
        ev = apply_config(r.evidence, cfg)
        out[pr_id] = VerdictReport(pr_id=pr_id, verdict=decide(ev), evidence=ev, owners=r.owners, summary=r.summary, gate_version=cfg.version)
    return out


def collect_raw(cases: list[Case], use_llm: bool = False, workers: int = 6) -> dict[str, VerdictReport]:
    """Run the full gate once per case with no config, keeping all raw evidence."""
    from concurrent.futures import ThreadPoolExecutor

    from .verify import verify

    with ThreadPoolExecutor(max_workers=workers) as pool:
        reports = list(pool.map(lambda c: verify(c.pr, use_llm=use_llm, config=None, use_subq=False), cases))
    return {c.pr.pr_id: r for c, r in zip(cases, reports)}


def _bump(level: str, up: bool, step: int = 1) -> str:
    i = LEVELS.index(level)
    return LEVELS[min(len(LEVELS) - 1, i + step)] if up else LEVELS[max(0, i - step)]


def propose(
    cfg: GateConfig,
    raw: dict[str, VerdictReport],
    train: list[Case],
    false_alarms: list[str],
    policy=None,
) -> list[GateConfig]:
    """Candidate configs. false_alarms = pr_ids an owner marked FALSE ALARM.

    policy (rsi.LearnerPolicy) says HOW to propose: step size, which evidence sources, whether to try pairs.
    It never touches what gets adopted; that floor lives in learn_round. Default: the adopted policy in
    learner_versions/, else today's behaviour (step 1, owner feedback + train misses, single changes).
    """
    from itertools import combinations

    from .rsi import load_policy

    policy = policy or load_policy()
    current = rescore(raw, cfg)
    seen: set[tuple[str, str]] = set()
    cands: list[GateConfig] = []

    def add(rule: str, level: str, why: str) -> None:
        if (rule, level) in seen or _rule_level(cfg, rule, "") == level:
            return
        seen.add((rule, level))
        new = GateConfig(version="", rule_severity={**cfg.rule_severity, rule: level}, parent=cfg.version, change=why)
        cands.append(new)

    def down(level: str) -> str:
        return _bump(level, up=False, step=policy.step)

    def up(level: str) -> str:
        return _bump(level, up=True, step=policy.step)

    if "false_alarm" in policy.sources:
        for pr_id in false_alarms:
            r = current.get(pr_id)
            if not r:
                continue
            for e in r.evidence:
                if e.id.startswith("owner::"):  # an owner's own rule is never downgraded by learning
                    continue
                k = knob(e)
                add(k, down(e.severity), f"owner marked {pr_id} FALSE ALARM; {k} {e.severity} -> {down(e.severity)}")

    if "missed_train" in policy.sources:
        for c in train:
            r = current.get(c.pr.pr_id)
            if c.label.true_verdict == "BLOCK" and r and r.verdict != "BLOCK":
                for e in raw[c.pr.pr_id].evidence:
                    k = knob(e)
                    level = _rule_level(cfg, k, e.severity)
                    if level != "block":
                        add(k, up(level), f"{c.pr.pr_id} ({c.label.kind}) got through; {k} {level} -> {up(level)}")

    if "noisy_rule" in policy.sources:
        # a knob that blocked a labelled-clean train PR and never fired on a labelled-bad one: no owner reply needed
        on_bad = {knob(e) for c in train if c.label.true_verdict == "BLOCK" for e in raw[c.pr.pr_id].evidence}
        for c in train:
            r = current.get(c.pr.pr_id)
            if c.label.true_verdict == "PASS" and r and r.verdict == "BLOCK":
                for e in r.evidence:
                    k = knob(e)
                    if e.severity == "block" and k not in on_bad and not e.id.startswith("owner::"):
                        add(k, down("block"), f"{k} blocked clean {c.pr.pr_id} and never fired on a bad train PR; block -> {down('block')}")

    if policy.combine:
        singles = [(next(iter(set(c.rule_severity.items()) - set(cfg.rule_severity.items()))), c.change) for c in cands]
        for ((ka, la), wa), ((kb, lb), wb) in combinations(singles, 2):
            if ka != kb:
                cands.append(GateConfig(version="", rule_severity={**cfg.rule_severity, ka: la, kb: lb}, parent=cfg.version,
                                        change=f"{wa} + {wb}"))
    return cands


def _better(new: dict, old: dict) -> bool:
    no_worse = new["catch_rate"] >= old["catch_rate"] and new["false_block_rate"] <= old["false_block_rate"]
    strictly = new["catch_rate"] > old["catch_rate"] or new["false_block_rate"] < old["false_block_rate"]
    return no_worse and strictly


def load_current(dir_: str = VERSIONS_DIR) -> GateConfig:
    ptr = os.path.join(dir_, "current.json")
    if not os.path.exists(ptr):
        return GateConfig()
    with open(ptr, encoding="utf-8") as f:
        name = json.load(f)["version"]
    with open(os.path.join(dir_, f"{name}.json"), encoding="utf-8") as f:
        return GateConfig(**json.load(f))


def _save(cfg: GateConfig, dir_: str, make_current: bool) -> None:
    os.makedirs(dir_, exist_ok=True)
    with open(os.path.join(dir_, f"{cfg.version}.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
    if make_current:
        with open(os.path.join(dir_, "current.json"), "w", encoding="utf-8") as f:
            json.dump({"version": cfg.version}, f)


def _next_version(dir_: str, cfg: GateConfig) -> str:
    n = int(cfg.version.lstrip("v") or 1)
    existing = {f[:-5] for f in os.listdir(dir_)} if os.path.isdir(dir_) else set()
    while f"v{n}" in existing or f"v{n}" == cfg.version:
        n += 1
    return f"v{n}"


def learn_round(
    cases: list[Case],
    raw: dict[str, VerdictReport],
    false_alarms: list[str],
    cfg: GateConfig | None = None,
    dir_: str = VERSIONS_DIR,
    policy=None,
    log: bool = True,
) -> dict:
    """One round: propose from train + feedback, score on held-out, adopt the best or roll back.

    policy: how to propose (rsi.LearnerPolicy; default = the adopted one). log=False for a trial round the
    meta-learner runs in a scratch dir: it must not enter the hash-chained run log as a real version.
    """
    cfg = cfg or load_current(dir_)
    if not os.path.exists(os.path.join(dir_, f"{cfg.version}.json")):
        _save(cfg, dir_, make_current=True)
    train = [c for c in cases if c.label.split == "train"]
    held = [c for c in cases if c.label.split == "heldout"]
    base_scores = score(held, rescore(raw, cfg))
    base_train_fb = score(train, rescore(raw, cfg))["false_block_rate"]

    decisions = []
    best: tuple[GateConfig, dict] | None = None
    for cand in propose(cfg, raw, train, false_alarms, policy):
        s = score(held, rescore(raw, cand))
        train_fb = score(train, rescore(raw, cand))["false_block_rate"]  # veto: never add a false block on a labelled clean train PR
        ok = _better(s, best[1] if best else base_scores) and train_fb <= base_train_fb
        decisions.append({"change": cand.change, "heldout": s, "train_false_block_rate": train_fb, "adopted_so_far": ok})
        if ok:
            best = (cand, s)

    if best:
        new, s = best
        new.version = _next_version(dir_, cfg)
        _save(new, dir_, make_current=True)
        result = {"from": cfg.version, "to": new.version, "adopted": new.change, "heldout_before": base_scores, "heldout_after": s}
    else:
        result = {"from": cfg.version, "to": cfg.version, "adopted": None, "heldout_before": base_scores, "heldout_after": base_scores}
    result["candidates"] = decisions
    if log:
        store.append("gate_version", result)
    return result


def false_alarms_from_log() -> list[str]:
    return sorted({r["data"]["pr_id"] for r in store.read(kind="reply") if r["data"].get("command") == "FALSE_ALARM"})
