import subprocess

import pytest

from merge_gate.sandbox import run_tests

TEST_F = "from m import f\n\ndef test_f():\n    assert f() == 1\n"


def _repo(tmp_path, body="def f():\n    return 1\n"):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "a@example.com")
    run("config", "user.name", "A")
    (repo / "m.py").write_text(body)
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    return str(repo)


def test_passing_tests(tmp_path):
    r = run_tests(_repo(tmp_path), "main", {"tests/test_gen.py": TEST_F})
    assert (r.passed, r.failed, r.errored) == (1, [], False)


def test_failing_test_reported_with_message(tmp_path):
    r = run_tests(_repo(tmp_path, "def f():\n    return 2\n"), "main", {"tests/test_gen.py": TEST_F})
    assert r.passed == 0 and not r.errored
    assert r.failed[0].test_id == "tests/test_gen.py::test_f" and "assert 2 == 1" in r.failed[0].message


def test_import_error_is_errored_not_clean(tmp_path):
    r = run_tests(_repo(tmp_path, "def f(:\n"), "main", {"tests/test_gen.py": TEST_F})
    assert r.errored and r.passed == 0


def test_no_tests_is_errored_not_clean(tmp_path):
    assert run_tests(_repo(tmp_path), "main", {}).errored


def test_timeout_is_errored(tmp_path):
    slow = "import time\n\ndef test_slow():\n    time.sleep(5)\n"
    assert run_tests(_repo(tmp_path), "main", {"tests/test_slow.py": slow}, timeout_s=1).errored


def test_hash_is_replayable(tmp_path):
    repo = _repo(tmp_path, "def f():\n    return 2\n")
    a, b = (run_tests(repo, "main", {"tests/test_gen.py": TEST_F}) for _ in range(2))
    assert a.output_hash == b.output_hash and a.output_hash.startswith("sha256:")


def test_model_written_path_cannot_escape(tmp_path):
    with pytest.raises(ValueError):
        run_tests(_repo(tmp_path), "main", {"../evil.py": "x = 1\n"})


def test_pr_code_cannot_read_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "sk-secret")
    leaky = "import os\n\ndef f():\n    return 0 if os.environ.get('META_API_KEY') else 1\n"
    assert run_tests(_repo(tmp_path, leaky), "main", {"tests/test_gen.py": TEST_F}).failed == []


def test_never_touches_repo_dir(tmp_path):
    repo = _repo(tmp_path)
    run_tests(repo, "main", {"tests/test_gen.py": TEST_F})
    assert subprocess.run(["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True).stdout == ""
