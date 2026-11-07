"""Anti-gaming rules (owner: Michael). Deterministic: no LLM, no network.

Each rule takes the PR and returns zero or more Evidence items.
Rule ids are stable strings; the iMessage text and the benchmark refer to them.
"""

from __future__ import annotations

from typing import Callable

from .pr import PullRequest
from .schema import Evidence

Rule = Callable[[PullRequest], list[Evidence]]

RULE_IDS = {
    "R1_DELETED_TEST": "a test function or test file was removed",
    "R2_SKIPPED_TEST": "a test was newly skipped or marked xfail",
    "R3_WEAKENED_ASSERT": "an assert was removed or loosened",
    "R4_MOCKED_SUBJECT": "the code under test is mocked out in its own tests",
    "R5_HARDCODED_OUTPUT": "the implementation special-cases test inputs",
    "R6_OUT_OF_SCOPE_TEST_EDIT": "tests changed outside the issue's scope",
}

# Filled in as rules are implemented.
RULES: list[Rule] = []


def check_rules(pr: PullRequest) -> list[Evidence]:
    evidence: list[Evidence] = []
    for rule in RULES:
        evidence.extend(rule(pr))
    return evidence
