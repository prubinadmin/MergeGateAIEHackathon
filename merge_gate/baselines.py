"""Baselines the gate is measured against (benchmark/RESULTS.md).

    llm         a plain reviewer: Muse Spark reads only the diff and answers BLOCK or PASS.
    codeowners  routing by the repo's CODEOWNERS folder rules: first owner of the first changed file.

Each returns VerdictReports so merge_gate.bench.score() measures them exactly like the gate.
A case whose baseline call fails or answers neither BLOCK nor PASS gets no report (counted as missing).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .bench import Case
from .pr import PullRequest
from .schema import VerdictReport

LLM_PROMPT = """You review a pull request. You see only its diff.
Answer BLOCK if it must not be merged (a bug, a security hole, a deleted or weakened test, a hardcoded result,
a backdoor), otherwise PASS. Reply with one word: BLOCK or PASS."""

METRICS = {"llm": ("catch_rate", "false_block_rate"), "codeowners": ("routing_accuracy",)}


def llm_review(pr: PullRequest) -> VerdictReport | None:
    from . import llm

    try:
        text = llm.complete(LLM_PROMPT, pr.diff())
    except llm.LLMError:
        return None
    m = re.search(r"\b(BLOCK|PASS)\b", text.upper())
    if not m:
        return None
    return VerdictReport(pr_id=pr.pr_id, verdict=m.group(1), summary=text.strip()[:200], gate_version="baseline:llm")  # type: ignore[arg-type]


def codeowners_route(pr: PullRequest) -> VerdictReport:
    from .owners import _codeowners

    owners = _codeowners(pr, pr.changed_files())
    return VerdictReport(pr_id=pr.pr_id, verdict="REVIEW", owners=owners, gate_version="baseline:codeowners")


BASELINES = {"llm": llm_review, "codeowners": codeowners_route}


def run(name: str, cases: list[Case], workers: int = 6) -> dict[str, VerdictReport]:
    fn = BASELINES[name]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        reports = list(pool.map(lambda c: fn(c.pr), cases))
    return {c.pr.pr_id: r for c, r in zip(cases, reports) if r is not None}
