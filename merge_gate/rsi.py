"""Recursive self-improvement, level 2: the learner that improves the learner.

Level 1 (learn.py) improves the gate: propose rule changes, score them on held-out PRs, adopt or roll back.
Level 2 (here) applies the same loop to the learner itself. A LearnerPolicy says HOW level 1 proposes:
  step      how far one proposal moves a rule: 1 (review -> block) or 2 (off -> block)
  sources   where proposals come from: false_alarm (an owner replied FALSE ALARM), missed_train (a labelled-bad
            train PR got through), noisy_rule (a rule blocked a labelled-clean train PR and never saw a bad one)
  combine   also try pairs of single changes
A meta-round runs a full level-1 round under the current policy and under each single-knob neighbour, in a
scratch copy so trials never touch gate_versions/. Each policy is scored by the held-out result the gate it
learned reaches. The best policy is adopted into learner_versions/ or every candidate is rolled back; the
decision goes into the hash-chained run log. `merge-gate learn` reads the adopted policy, so the improved
learner is the one that runs next time: that closes the loop.

The constitution, not learnable by construction (LearnerPolicy has no field for any of it, tests pin this):
  - the held-out split is never proposed from and never changes
  - the adoption floor (learn._better): held-out catch may not drop, false blocks may not rise, one must improve
  - the train false-block veto (learn_round)
  - decide() is plain code
A policy can change what gets proposed, never what gets accepted.

Known limit: both levels select on the same held-out split. With 15 held-out cases one flipped PR clears the
floor, so a policy that proposes more candidates gets more shots at it. The mitigation here is that a policy
must beat the gate the incumbent policy learns, not just the live gate; the real fix is a held-out slice
reserved for policy selection once the benchmark is large enough to spare one.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, replace

from . import store
from .bench import Case
from .learn import VERSIONS_DIR, _better, learn_round, load_current
from .schema import VerdictReport

POLICY_DIR = "learner_versions"
SOURCES = ("false_alarm", "missed_train", "noisy_rule")
STEPS = (1, 2)


@dataclass
class LearnerPolicy:
    version: str = "p1"
    step: int = 1
    sources: list[str] = field(default_factory=lambda: ["false_alarm", "missed_train"])
    combine: bool = False
    parent: str = ""
    change: str = ""  # one line: what this policy changed

    def __post_init__(self) -> None:
        if self.step not in STEPS:
            raise ValueError(f"step must be one of {STEPS}, got {self.step!r}")
        if not self.sources or not set(self.sources) <= set(SOURCES):
            raise ValueError(f"sources must be a non-empty subset of {SOURCES}, got {self.sources!r}")


def load_policy(dir_: str = POLICY_DIR) -> LearnerPolicy:
    """The adopted policy, or today's default. A broken policy file must never take down `merge-gate learn`."""
    ptr = os.path.join(dir_, "current.json")
    if not os.path.exists(ptr):
        return LearnerPolicy()
    try:
        with open(ptr, encoding="utf-8") as f:
            name = json.load(f)["version"]
        with open(os.path.join(dir_, f"{name}.json"), encoding="utf-8") as f:
            return LearnerPolicy(**json.load(f))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"merge-gate: ignoring unreadable learner policy in {dir_}: {exc}", file=sys.stderr)
        return LearnerPolicy()


def _save(policy: LearnerPolicy, dir_: str, make_current: bool) -> None:
    os.makedirs(dir_, exist_ok=True)
    with open(os.path.join(dir_, f"{policy.version}.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(policy), f, indent=2)
    if make_current:
        with open(os.path.join(dir_, "current.json"), "w", encoding="utf-8") as f:
            json.dump({"version": policy.version}, f)


def _next_version(dir_: str, policy: LearnerPolicy) -> str:
    n = int(policy.version.lstrip("p") or 1)
    existing = {f[:-5] for f in os.listdir(dir_)} if os.path.isdir(dir_) else set()
    while f"p{n}" in existing or f"p{n}" == policy.version:
        n += 1
    return f"p{n}"


def neighbours(policy: LearnerPolicy) -> list[LearnerPolicy]:
    """Every policy one knob away from this one."""
    out = []
    for s in STEPS:
        if s != policy.step:
            out.append(replace(policy, version="", parent=policy.version, step=s, change=f"step {policy.step} -> {s}"))
    for src in SOURCES:
        if src in policy.sources:
            if len(policy.sources) > 1:  # a learner with no proposal source cannot learn
                out.append(replace(policy, version="", parent=policy.version, sources=[x for x in policy.sources if x != src],
                                   change=f"drop source {src}"))
        else:
            out.append(replace(policy, version="", parent=policy.version, sources=[*policy.sources, src], change=f"add source {src}"))
    out.append(replace(policy, version="", parent=policy.version, combine=not policy.combine,
                       change=f"combine {policy.combine} -> {not policy.combine}"))
    return out


def trial(policy: LearnerPolicy, cases: list[Case], raw: dict[str, VerdictReport], false_alarms: list[str],
          gate_dir: str = VERSIONS_DIR) -> dict:
    """One level-1 round under `policy` in a scratch dir: the gate it would learn, and that gate's held-out score."""
    cfg = load_current(gate_dir)
    with tempfile.TemporaryDirectory(prefix="mergegate-rsi-") as tmp:
        return learn_round(cases, raw, false_alarms, cfg=cfg, dir_=tmp, policy=policy, log=False)


def meta_round(cases: list[Case], raw: dict[str, VerdictReport], false_alarms: list[str],
               policy: LearnerPolicy | None = None, dir_: str = POLICY_DIR, gate_dir: str = VERSIONS_DIR) -> dict:
    """One RSI round: try the learner's neighbours, keep the one whose learned gate does best on held-out PRs."""
    policy = policy or load_policy(dir_)
    if not os.path.exists(os.path.join(dir_, f"{policy.version}.json")):
        _save(policy, dir_, make_current=True)

    base = trial(policy, cases, raw, false_alarms, gate_dir)
    best: tuple[LearnerPolicy, dict] | None = None
    decisions = []
    for cand in neighbours(policy):
        t = trial(cand, cases, raw, false_alarms, gate_dir)
        ok = _better(t["heldout_after"], (best[1] if best else base)["heldout_after"])
        decisions.append({"policy_change": cand.change, "gate_change": t["adopted"], "candidates_tried": len(t["candidates"]),
                          "heldout": t["heldout_after"], "adopted_so_far": ok})
        if ok:
            best = (cand, t)

    # heldout_live: the gate as it runs today; heldout_before/after: the gate the old / new learner learns from it
    if best:
        new, t = best
        new.version = _next_version(dir_, policy)
        _save(new, dir_, make_current=True)
        result = {"from": policy.version, "to": new.version, "adopted": new.change, "learner": asdict(new),
                  "heldout_live": base["heldout_before"], "heldout_before": base["heldout_after"], "heldout_after": t["heldout_after"]}
    else:
        result = {"from": policy.version, "to": policy.version, "adopted": None, "learner": asdict(policy),
                  "heldout_live": base["heldout_before"], "heldout_before": base["heldout_after"], "heldout_after": base["heldout_after"]}
    result["candidates"] = decisions
    store.append("learner_version", result)
    return result
