"""The system that gets better (owner: Michael).

A gate version is a rule configuration: for each rule id, "block", "review" or "off".
Proposals come from evidence, never from a model:
  - an owner replies FALSE ALARM          -> propose downgrading the rules that fired (block -> review -> off)
  - a bad train-split PR got through      -> propose upgrading/enabling the rules that saw it
Each proposal is scored on the HELD-OUT split only. It is adopted when held-out catch rate does not
drop, false-block rate does not rise, and at least one of them improves. Otherwise it is rolled back.
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
        reports = list(pool.map(lambda c: verify(c.pr, use_llm=use_llm, config=None), cases))
    return {c.pr.pr_id: r for c, r in zip(cases, reports)}


def _bump(level: str, up: bool) -> str:
    i = LEVELS.index(level)
    return LEVELS[min(len(LEVELS) - 1, i + 1)] if up else LEVELS[max(0, i - 1)]


def propose(
    cfg: GateConfig,
    raw: dict[str, VerdictReport],
    train: list[Case],
    false_alarms: list[str],
) -> list[GateConfig]:
    """Single-change candidates. false_alarms = pr_ids an owner marked FALSE ALARM."""
    current = rescore(raw, cfg)
    seen: set[tuple[str, str]] = set()
    cands: list[GateConfig] = []

    def add(rule: str, level: str, why: str) -> None:
        if (rule, level) in seen or _rule_level(cfg, rule, "") == level:
            return
        seen.add((rule, level))
        new = GateConfig(version="", rule_severity={**cfg.rule_severity, rule: level}, parent=cfg.version, change=why)
        cands.append(new)

    for pr_id in false_alarms:
        r = current.get(pr_id)
        if not r:
            continue
        for e in r.evidence:
            rule = e.id.split("::")[0] if e.type == "rule" else e.id
            if e.type == "rule":
                add(rule, _bump(e.severity, up=False), f"owner marked {pr_id} FALSE ALARM; {rule} {e.severity} -> {_bump(e.severity, up=False)}")

    for c in train:
        r = current.get(c.pr.pr_id)
        if c.label.true_verdict == "BLOCK" and r and r.verdict != "BLOCK":
            for e in raw[c.pr.pr_id].evidence:
                k = knob(e)
                level = _rule_level(cfg, k, e.severity)
                if level != "block":
                    add(k, _bump(level, up=True), f"{c.pr.pr_id} ({c.label.kind}) got through; {k} {level} -> {_bump(level, up=True)}")
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
) -> dict:
    """One round: propose from train + feedback, score on held-out, adopt the best or roll back."""
    cfg = cfg or load_current(dir_)
    if not os.path.exists(os.path.join(dir_, f"{cfg.version}.json")):
        _save(cfg, dir_, make_current=True)
    train = [c for c in cases if c.label.split == "train"]
    held = [c for c in cases if c.label.split == "heldout"]
    base_scores = score(held, rescore(raw, cfg))

    decisions = []
    best: tuple[GateConfig, dict] | None = None
    for cand in propose(cfg, raw, train, false_alarms):
        s = score(held, rescore(raw, cand))
        ok = _better(s, best[1] if best else base_scores)
        decisions.append({"change": cand.change, "heldout": s, "adopted_so_far": ok})
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
    store.append("gate_version", result)
    return result


def false_alarms_from_log() -> list[str]:
    return sorted({r["data"]["pr_id"] for r in store.read(kind="reply") if r["data"].get("command") == "FALSE_ALARM"})
