"""MERGE_GATE_DEMO_GITHUB: demo cases come from a GitHub repo's open PRs and verdicts are posted back. No network."""

from merge_gate import demo_github, github, serve, store

from helpers import git, make_pr

SRC = "def total(xs):\n    return sum(xs)\n"
TESTS = "from shop.cart import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n\n\ndef test_empty():\n    assert total([]) == 0\n"


def test_github_prs_become_cases_and_verdicts_are_published(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    pr = make_pr(tmp_path, {"shop/__init__.py": "", "shop/cart.py": SRC, "tests/test_cart.py": TESTS},
                 {"tests/test_cart.py": TESTS.split("\n\n\ndef test_empty")[0] + "\n"})
    repo = pr.repo_path
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    sha = __import__("subprocess").run(["git", "-C", repo, "rev-parse", "pr/1"], capture_output=True, text=True).stdout.strip()

    calls = []

    def fake_call(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and "/pulls?" in path:
            return [{"number": 7, "head": {"sha": sha}, "base": {"ref": "main"}, "title": "Tidy tests",
                     "body": "Clean up the cart tests.", "html_url": "https://github.com/o/r/pull/7"}]
        return {}

    monkeypatch.setattr(github, "_call", fake_call)
    # a real git remote for sync() to clone and fetch: a bare copy of the PR repo stands in for github.com/o/r
    import subprocess
    bare = str(tmp_path / "remote.git")
    subprocess.run(["git", "clone", "-q", "--bare", repo, bare], check=True)
    root = str(tmp_path / "clones")
    monkeypatch.setattr(demo_github, "ROOT", root)
    subprocess.run(["git", "clone", "-q", bare, str(tmp_path / "clones" / "o__r")], check=True)
    monkeypatch.setenv("MERGE_GATE_DEMO_GITHUB", "o/r")

    state = serve.State(use_llm=False)
    cases = state.demo(refresh=True)
    assert [c.pr_id for c in cases] == ["demo-7"]
    assert cases[0].base_ref == "origin/main" and cases[0].head_ref == sha

    report = state.verify({"pr_id": "demo-7", "llm": False})
    assert report.verdict == "BLOCK"  # R1: a test was deleted
    status = [c for c in calls if "/statuses/" in c[1]]
    assert status and status[0][1] == f"/repos/o/r/statuses/{sha}" and status[0][2]["state"] == "failure"
    assert any("/issues/7/comments" in c[1] for c in calls)
    assert "posted failure" in state.published["demo-7"]


def test_without_the_variable_nothing_goes_to_github(tmp_path, monkeypatch):
    monkeypatch.delenv("MERGE_GATE_DEMO_GITHUB", raising=False)
    monkeypatch.setattr(serve, "DEMO_ROOT", str(tmp_path / "demo"))
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(github, "_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no GitHub calls")))
    state = serve.State(use_llm=False)
    ids = [p.pr_id for p in state.demo()]
    assert ids and all(i.startswith("demo-") for i in ids)  # the generated local demo repo
    state.verify({"pr_id": "demo-1", "llm": False})
    assert state.published == {}
