"""Isolated test runs (owner: Michael)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TestFailure:
    test_id: str  # pytest node id
    message: str  # first line of the assertion error
    file: str | None = None
    line: int | None = None


@dataclass
class SandboxResult:
    passed: int
    failed: list[TestFailure] = field(default_factory=list)
    errored: bool = False  # collection error, timeout, crash
    output_hash: str = ""  # run_hash of the raw output, for replay


def run_tests(repo_dir: str, ref: str, test_files: dict[str, str], timeout_s: int = 60) -> SandboxResult:
    """Check out `ref` into a temp dir, add `test_files` (path -> source), run pytest.

    Never runs in repo_dir itself.
    """
    raise NotImplementedError("sandbox runner: next after rules")
