import os

from merge_gate.sandbox import run_tests

from helpers import make_pr

SRC = "def apply_discount(price, pct):\n    return max(0.0, price * (1 - pct / 100))\n"
BUGGY = "def apply_discount(price, pct):\n    return price * (1 - pct / 100)\n"
GATE_TEST = (
    "from shop.pricing import apply_discount\n\n"
    "def test_capped():\n    assert apply_discount(10, 150) == 0.0\n\n"
    "def test_basic():\n    assert apply_discount(100, 10) == 90\n"
)


def test_catches_the_bug_on_head_and_passes_on_base(tmp_path):
    pr = make_pr(tmp_path, {"shop/__init__.py": "", "shop/pricing.py": SRC}, {"shop/pricing.py": BUGGY})
    base = run_tests(pr.repo_path, pr.base_ref, {"test_gate.py": GATE_TEST})
    head = run_tests(pr.repo_path, pr.head_ref, {"test_gate.py": GATE_TEST})
    assert (base.passed, base.failed, base.errored) == (2, [], False)
    assert head.passed == 1 and not head.errored
    assert [f.test_id.split("::")[-1] for f in head.failed] == ["test_capped"]
    assert "-5.0" in head.failed[0].message
    assert head.output_hash.startswith("sha256:") and head.output_hash != base.output_hash


def test_secrets_do_not_reach_pr_code(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSE_API_KEY", "sk-should-not-leak")
    leak = "import os\n\ndef test_env():\n    assert 'MUSE_API_KEY' not in os.environ\n"
    pr = make_pr(tmp_path, {"m.py": "X = 1\n"}, {"m.py": "X = 2\n"})
    r = run_tests(pr.repo_path, pr.head_ref, {"test_env.py": leak})
    assert r.passed == 1 and not r.failed


def test_timeout_is_an_error_not_a_pass(tmp_path):
    hang = "import time\n\ndef test_hang():\n    time.sleep(30)\n"
    pr = make_pr(tmp_path, {"m.py": "X = 1\n"}, {"m.py": "X = 2\n"})
    r = run_tests(pr.repo_path, pr.head_ref, {"test_hang.py": hang}, timeout_s=3)
    assert r.errored and r.passed == 0


def test_never_touches_the_checkout(tmp_path):
    pr = make_pr(tmp_path, {"m.py": "X = 1\n"}, {"m.py": "X = 2\n"})
    before = sorted(os.listdir(pr.repo_path))
    run_tests(pr.repo_path, pr.head_ref, {"test_x.py": "def test_x():\n    assert True\n"})
    assert sorted(os.listdir(pr.repo_path)) == before
