"""Isolated test runs (owner: Michael).

The code under test is exported with `git archive` into a fresh temp dir (never the user's checkout),
the gate's tests are added under `_gate_tests/`, and pytest runs in a subprocess with a timeout and a
scrubbed environment: no API keys, no tokens, no phone numbers reach PR code.

This is process isolation, not a security sandbox. Untrusted PR code still runs as the current user,
so the benchmark only runs repos we wrote ourselves.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

from .schema import run_hash

GATE_TEST_DIR = "_gate_tests"
# The interpreter that runs the code under test. Default: the gate's own. Set it when the target project
# needs an older Python than the gate (the BugsInPy benchmark runs its 2019-era projects on 3.8).
SANDBOX_PYTHON_ENV = "MERGE_GATE_SANDBOX_PYTHON"
# Paths and locale only: enough for Python to find its own site-packages. Never keys or tokens.
KEEP_ENV = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "PATHEXT", "COMSPEC",
    "APPDATA", "LOCALAPPDATA", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX",
)


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
    output_hash: str = ""  # run_hash of the inputs + outcome, for replay
    log: str = ""  # tail of pytest output


def export_ref(repo_dir: str, ref: str, dest: str) -> None:
    data = subprocess.run(
        ["git", "-C", repo_dir, "archive", "--format=zip", ref], capture_output=True, check=True
    ).stdout
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)


def _clean_env(workdir: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}
    env.update(PYTHONPATH=workdir, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")
    return env


def _parse_junit(path: str) -> tuple[int, list[TestFailure], bool]:
    if not os.path.exists(path):
        return 0, [], True
    root = ET.parse(path).getroot()
    passed, failed, errored = 0, [], False
    for case in root.iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        node = f"{cls.replace('.', '/')}.py::{name}" if cls else name
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
            if problem is not None and case.find("failure") is None and "collect" in (problem.get("message") or "").lower():
                errored = True
        if problem is not None:
            msg = (problem.get("message") or problem.text or "").strip().splitlines()
            failed.append(TestFailure(test_id=node, message=(msg[0] if msg else "failed")[:300], file=case.get("file"), line=_int(case.get("line"))))
        elif case.find("skipped") is None:
            passed += 1
    for suite in root.iter("testsuite"):
        if int(suite.get("errors", "0")) and not failed:
            errored = True
    return passed, failed, errored


def _int(s: str | None) -> int | None:
    try:
        return int(s) + 1 if s is not None else None  # junit lines are 0-based
    except ValueError:
        return None


def run_tests(
    repo_dir: str,
    ref: str,
    test_files: dict[str, str],
    timeout_s: int = 60,
    include_repo_tests: bool = False,
) -> SandboxResult:
    """Export `ref` to a temp dir, add `test_files` (name -> pytest source) under _gate_tests/, run pytest."""
    work = tempfile.mkdtemp(prefix="mergegate-")
    try:
        export_ref(repo_dir, ref, work)
        gate_dir = os.path.join(work, GATE_TEST_DIR)
        os.makedirs(gate_dir, exist_ok=True)
        for name, src in test_files.items():
            safe = os.path.basename(name)
            if not safe.startswith("test_"):
                safe = "test_" + safe
            with open(os.path.join(gate_dir, safe), "w", encoding="utf-8") as f:
                f.write(src)
        junit = os.path.join(work, ".gate-junit.xml")
        targets = [GATE_TEST_DIR] + (["."] if include_repo_tests else [])
        cmd = [os.environ.get(SANDBOX_PYTHON_ENV) or sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", work, f"--junitxml={junit}", *targets]
        try:
            proc = subprocess.run(cmd, cwd=work, env=_clean_env(work), capture_output=True, text=True, timeout=timeout_s, encoding="utf-8", errors="replace")
            log = (proc.stdout + proc.stderr)[-4000:]
            passed, failed, errored = _parse_junit(junit)
            if proc.returncode not in (0, 1) and not failed:
                errored = True  # 2 interrupted, 3 internal, 4 usage, 5 no tests
        except subprocess.TimeoutExpired:
            passed, failed, errored, log = 0, [], True, f"timeout after {timeout_s}s"
        outcome = {"passed": passed, "failed": [(f.test_id, f.message) for f in failed], "errored": errored}
        h = run_hash({"ref": _rev(repo_dir, ref), "tests": test_files, "outcome": outcome})
        return SandboxResult(passed, failed, errored, h, log)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _rev(repo_dir: str, ref: str) -> str:
    try:
        return subprocess.run(["git", "-C", repo_dir, "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        return ref
