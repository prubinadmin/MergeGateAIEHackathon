"""Spec-only test writer (owner: Michael). Uses Muse Spark.

Input is the issue text plus the public interface of the changed modules.
It must never see the PR's own tests, diff or the implementer's reasoning.
"""

from __future__ import annotations

from .pr import PullRequest


def public_interface(pr: PullRequest, ref: str) -> str:
    """Signatures and docstrings of the changed non-test modules at `ref`, bodies stripped."""
    raise NotImplementedError


def generate_tests(pr: PullRequest) -> dict[str, str]:
    """Return {test file path: pytest source} written from the issue + interface only."""
    raise NotImplementedError("needs MUSE_API_KEY; see merge_gate/llm.py")
