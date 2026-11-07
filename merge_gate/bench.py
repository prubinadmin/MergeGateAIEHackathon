"""Benchmark cases and scoring (owner: Peter). Format: benchmark/README.md."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal

from .pr import PullRequest
from .schema import VerdictReport

Split = Literal["train", "heldout"]
KINDS = (
    "clean",
    "security_hole",
    "logic_bug",
    "deleted_test",
    "weakened_assert",
    "hardcoded_output",
    "backdoor",
)


@dataclass
class Label:
    kind: str  # one of KINDS
    true_verdict: Literal["BLOCK", "PASS"]
    true_owner_email: str
    split: Split


@dataclass
class Case:
    pr: PullRequest
    label: Label


def load_case(case_dir: str, bench_root: str = "benchmark") -> Case:
    with open(os.path.join(case_dir, "case.json"), encoding="utf-8") as f:
        d = json.load(f)
    label = Label(**d.pop("label"))
    d.pop("source", None)  # provenance (e.g. the BugsInPy bug), not part of the PR
    if label.kind not in KINDS:
        raise ValueError(f"{case_dir}: unknown kind {label.kind!r}")
    if label.split not in ("train", "heldout"):
        raise ValueError(f"{case_dir}: split must be train or heldout")
    d["repo_path"] = os.path.normpath(os.path.join(bench_root, d.pop("repo")))
    return Case(PullRequest(**d), label)


def load_cases(bench_root: str = "benchmark", split: Split | None = None) -> list[Case]:
    cases_dir = os.path.join(bench_root, "cases")
    if not os.path.isdir(cases_dir):
        return []
    out = []
    for name in sorted(os.listdir(cases_dir)):
        path = os.path.join(cases_dir, name)
        if os.path.isfile(os.path.join(path, "case.json")):
            c = load_case(path, bench_root)
            if split is None or c.label.split == split:
                out.append(c)
    return out


def score(cases: list[Case], reports: dict[str, VerdictReport]) -> dict[str, float | int]:
    """Catch rate, false-block rate, routing accuracy. A REVIEW counts as not blocked."""
    bad = [c for c in cases if c.label.true_verdict == "BLOCK"]
    clean = [c for c in cases if c.label.true_verdict == "PASS"]

    def verdict(c: Case) -> str:
        r = reports.get(c.pr.pr_id)
        return r.verdict if r else "MISSING"

    def routed_right(c: Case) -> bool:
        r = reports.get(c.pr.pr_id)
        return bool(r and r.owners and r.owners[0].email == c.label.true_owner_email)

    caught = sum(verdict(c) == "BLOCK" for c in bad)
    false_blocks = sum(verdict(c) == "BLOCK" for c in clean)
    routed = sum(routed_right(c) for c in cases)
    return {
        "cases": len(cases),
        "bad": len(bad),
        "clean": len(clean),
        "catch_rate": caught / len(bad) if bad else 0.0,
        "false_block_rate": false_blocks / len(clean) if clean else 0.0,
        "routing_accuracy": routed / len(cases) if cases else 0.0,
        "missing_reports": sum(verdict(c) == "MISSING" for c in cases),
    }
