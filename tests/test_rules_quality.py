"""R10-R14 report only what a PR introduces, and harden_gate runs a real learning round."""

import json
import os

import pytest

from merge_gate import store
from merge_gate.rules import check_rules
from merge_gate.verify import harden_gate, verify

from helpers import git, make_pr, write

JOBS = (
    "import time\n\n\n"
    "def retry(fn):\n    try:\n        return fn()\n    except:\n        time.sleep(1)\n        return fn()\n\n\n"
    "def label(x: int) -> str:\n    return 'job-' + str(x)\n"
)
BASE = {"svc/__init__.py": "", "svc/jobs.py": JOBS}


def found(pr):
    return {(e.id, e.severity) for e in check_rules(pr)}


def test_existing_sleep_and_bare_except_do_not_block_a_clean_pr(tmp_path):
    pr = make_pr(tmp_path, BASE, {"svc/jobs.py": JOBS.replace("'job-'", "'job:'")})
    assert found(pr) == set()
    assert verify(pr).verdict == "PASS"


def test_r11_new_sleep_and_nested_loop_are_review(tmp_path):
    head = JOBS.replace("    return 'job-' + str(x)\n",
                        "    for i in range(x):\n        for j in range(x):\n            pass\n    time.sleep(0.1)\n    return 'job-' + str(x)\n")
    f = found(make_pr(tmp_path, BASE, {"svc/jobs.py": head}))
    assert ("R11_PERFORMANCE_REGRESSION", "review") in f
    assert not any(sev == "block" for _, sev in f)


def test_r12_complexity_jump_is_review(tmp_path):
    branches = "".join(f"    if x == {i}:\n        return 'j{i}'\n" for i in range(6))
    head = JOBS.replace("    return 'job-' + str(x)\n", branches + "    return 'job-' + str(x)\n")
    assert ("R12_COMPLEXITY_INFLATION", "review") in found(make_pr(tmp_path, BASE, {"svc/jobs.py": head}))


def test_r13_camel_case_and_dropped_hints(tmp_path):
    head = JOBS.replace("def label(x: int) -> str:", "def label(x):") + "\n\ndef makeLabel(x):\n    return label(x)\n"
    details = [e.detail for e in check_rules(make_pr(tmp_path, BASE, {"svc/jobs.py": head})) if e.id == "R13_STYLE_INCONSISTENCY"]
    assert any("camelCase" in d for d in details) and any("type hints" in d for d in details)


def test_r14_new_bare_except_is_review_new_debugger_blocks(tmp_path):
    head = JOBS.replace("    return 'job-' + str(x)\n", "    try:\n        n = int(x)\n    except:\n        n = 0\n    breakpoint()\n    return 'job-' + str(n)\n")
    pr = make_pr(tmp_path, BASE, {"svc/jobs.py": head})
    sev = {e.detail.split(" adds ")[-1]: e.severity for e in check_rules(pr) if e.id == "R14_REGULATORY_STYLE_VIOLATION"}
    assert sev == {"a bare except:": "review", "a debugger breakpoint that halts the process": "block"}
    assert verify(pr).verdict == "BLOCK"


def test_r10_removed_name_still_imported_blocks(tmp_path):
    base = dict(BASE, **{"svc/api.py": "from svc.jobs import label\n\n\ndef show(x):\n    return label(x)\n"})
    head = {"svc/jobs.py": JOBS.replace("def label(", "def make_label(")}
    pr = make_pr(tmp_path, base, head)
    ev = [e for e in check_rules(pr) if e.id == "R10_RUNTIME_INTEGRITY"]
    assert len(ev) == 1 and ev[0].file == "svc/api.py" and ev[0].severity == "block"


def test_r10_removing_an_unused_name_is_fine(tmp_path):
    pr = make_pr(tmp_path, BASE, {"svc/jobs.py": JOBS.replace("def label(", "def make_label(")})
    assert not any(e.id == "R10_RUNTIME_INTEGRITY" for e in check_rules(pr))


# --- harden_gate ---------------------------------------------------------------

SRC = "def total(xs):\n    return sum(xs)\n"
TEST = "from shop.cart import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
OTHER = "def size(xs):\n    return len(xs)\n"
OTHER_TEST = "from shop.other import size\n\n\ndef test_size():\n    assert size([1]) == 1\n"


def _bench(tmp_path):
    """One repo, three PRs. pr/1 (train) and pr/2 (heldout) are bad but only trip review-level R6."""
    root = tmp_path / "benchmark"
    repo = str(root / "target_repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "o@example.com")
    git(repo, "config", "user.name", "O")
    write(repo, {"shop/__init__.py": "", "shop/cart.py": SRC, "shop/other.py": OTHER,
                 "tests/test_cart.py": TEST, "tests/test_other.py": OTHER_TEST})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    sneaky = {"shop/cart.py": SRC.replace("sum(xs)", "sum(xs) + 0"),
              "tests/test_other.py": OTHER_TEST + "\n\ndef test_extra():\n    assert True\n"}
    for branch, files in (("pr/1", sneaky), ("pr/2", sneaky), ("pr/3", {"shop/cart.py": SRC.replace("sum(xs)", "sum(list(xs))")})):
        git(repo, "checkout", "-q", "-b", branch, "main")
        write(repo, files)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", branch)
    git(repo, "checkout", "-q", "main")
    labels = {"pr1": ("pr/1", "logic_bug", "BLOCK", "train"), "pr2": ("pr/2", "logic_bug", "BLOCK", "heldout"),
              "pr3": ("pr/3", "clean", "PASS", "heldout")}
    for pid, (head, kind, verdict, split) in labels.items():
        d = root / "cases" / pid
        d.mkdir(parents=True)
        (d / "case.json").write_text(json.dumps({
            "pr_id": pid, "repo": "target_repo", "base_ref": "main", "head_ref": head, "issue_text": "x",
            "label": {"kind": kind, "true_verdict": verdict, "true_owner_email": "o@example.com", "split": split}}))
    return str(root)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_harden_gate_runs_a_real_round_and_reports_measured_scores(isolated):
    root = _bench(isolated)
    out = harden_gate({"pr_id": "pr1", "kind": "out_of_scope_test", "description": "edits an unrelated test"}, bench_root=root)
    assert out["hardened"] is True and out["from_version"] == "v1" and out["new_version"] == "v2"
    assert out["heldout_before"]["catch_rate"] == 0.0 and out["heldout_after"]["catch_rate"] == 1.0
    assert out["heldout_after"]["false_block_rate"] == 0.0
    assert "R6_OUT_OF_SCOPE_TEST_EDIT" in out["adopted_change"]


def test_harden_gate_refuses_without_cases_or_with_a_heldout_case(isolated):
    assert harden_gate({"pr_id": "x"}, bench_root=str(isolated / "none"))["hardened"] is False
    root = _bench(isolated)
    out = harden_gate({"pr_id": "pr2"}, bench_root=root)
    assert out["hardened"] is False and "held out" in out["reason"]
