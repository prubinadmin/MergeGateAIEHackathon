"""Isolated test runs (owner: Michael)."""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .schema import run_hash


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


_LINE = re.compile(r"^(PASSED|FAILED|ERROR) (\S+)(?: - (.*))?$", re.M)


# ponytail: process-level isolation only — PR code runs as the current user with network access.
# Upgrade path: run pytest inside `docker run --rm --network none` if attacks go beyond the benchmark.
def run_tests(repo_dir: str, ref: str, test_files: dict[str, str], timeout_s: int = 60) -> SandboxResult:
    """Check out `ref` into a temp dir, add `test_files` (path -> source), run pytest.

    Never runs in repo_dir itself.
    """
    with tempfile.TemporaryDirectory(prefix="merge-gate-") as tmp:
        work = Path(tmp) / "repo"
        work.mkdir()
        tar = subprocess.run(["git", "-C", repo_dir, "archive", "--format=tar", ref], capture_output=True, check=True)
        with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as tf:
            tf.extractall(work, filter="data")

        for rel, src in test_files.items():
            dest = (work / rel).resolve()
            if not dest.is_relative_to(work.resolve()):  # paths come from a model: keep them inside the sandbox
                raise ValueError(f"test path escapes sandbox: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src, encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-rA", "-q", "-p", "no:cacheprovider"],
                cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=timeout_s,
                # scrubbed env: PR code must never inherit API keys / phone numbers / Mongo URI from .env
                env={"PATH": os.environ.get("PATH", ""), "HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired:
            return _result(0, [], errored=True)

    passed, failed, errored = 0, [], False
    for status, node, msg in _LINE.findall(proc.stdout):
        if status == "PASSED":
            passed += 1
        elif status == "FAILED":
            failed.append(TestFailure(test_id=node, message=msg))
        else:
            errored = True
    # exit 0 = all passed, 1 = some failed; anything else (collection error, no tests) must not look clean
    return _result(passed, failed, errored or proc.returncode not in (0, 1))


def _result(passed: int, failed: list[TestFailure], errored: bool) -> SandboxResult:
    # hash the parsed result, not raw stdout: pytest prints timings, which would make every hash unique
    digest = run_hash({"passed": passed, "failed": [[f.test_id, f.message] for f in failed], "errored": errored})
    return SandboxResult(passed=passed, failed=failed, errored=errored, output_hash=digest)
