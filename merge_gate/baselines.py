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

_TOKENS = ("BLOCK", "PASS")
_TOKEN_RE = re.compile(r"\b(BLOCK|PASS)\b")


def parse_verdict(text: str) -> str | None:
    """The reply's verdict: the whole reply when it is exactly BLOCK or PASS; otherwise the LAST such word,
    since a reviewer that reasons first ends with its answer ('No reason to BLOCK. PASS.' -> PASS).
    The first match would read 'This should not PASS: BLOCK' as PASS."""
    whole = text.strip().upper()
    if whole in _TOKENS:
        return whole
    found = _TOKEN_RE.findall(whole)
    return found[-1] if found else None


def llm_review(pr: PullRequest) -> VerdictReport | None:
    from . import llm

    try:
        text = llm.complete(LLM_PROMPT, pr.diff())
    except llm.LLMError:
        return None
    verdict = parse_verdict(text)
    if verdict is None:
        return None
    return VerdictReport(pr_id=pr.pr_id, verdict=verdict, summary=text.strip()[:200], gate_version="baseline:llm")  # type: ignore[arg-type]


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
