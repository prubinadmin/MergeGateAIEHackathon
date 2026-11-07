"""rollback: re-verify a merged commit, revert it on BLOCK. No network: push and the GitHub API are faked."""

import subprocess

import pytest

from merge_gate import github, rollback, store
from merge_gate.cli import main as cli_main
from merge_gate.demo import build_demo_repo

from helpers import git


def out(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    return build_demo_repo(str(tmp_path))


def merge(repo, branch, ff=False):
    who = ("Maintainer", "m@example.com")
    git(repo, "merge", "-q", "--ff-only" if ff else "--no-ff", *([] if ff else ["-m", f"Merge {branch}"]), branch, author=who)
    return out(repo, "rev-parse", "HEAD")


def test_blocked_merge_commit_gets_a_revert_branch(repo, tmp_path):
    pre = out(repo, "rev-parse", "HEAD^{tree}")
    sha = merge(repo, "pr/demo-1")
    status_before = out(repo, "status", "--porcelain")

    result = rollback.rollback(repo, sha)

    assert result["verdict"] == "BLOCK" and result["action"] == "revert_branch"
    branch = result["branch"]
    assert branch == f"merge-gate/revert-{sha[:12]}"
    assert out(repo, "rev-parse", f"{branch}^{{tree}}") == pre  # revert restores the pre-merge tree
    msg = out(repo, "log", "-1", "--format=%B", branch)
    assert msg.startswith(f"revert: Merge Gate blocked {sha[:12]} (") and "R1_" in msg.splitlines()[0]
    assert result["run_hash"] in msg
    # the user's checkout is untouched: still on main at the merge, no stray worktrees
    assert out(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert out(repo, "rev-parse", "HEAD") == sha
    assert out(repo, "status", "--porcelain") == status_before
    assert len(out(repo, "worktree", "list").splitlines()) == 1
    recs = store.read(kind="rollback")
    assert recs[-1]["data"]["branch"] == branch and store.verify_chain()[0]


def test_clean_plain_commit_is_left_alone(repo):
    sha = merge(repo, "pr/demo-3", ff=True)  # fast-forward: a plain, non-merge commit
    result = rollback.rollback(repo, sha)
    assert result["verdict"] != "BLOCK" and result["action"] == "none" and result["branch"] is None
    assert "merge-gate/revert-" not in out(repo, "branch", "--list")
    assert store.read(kind="rollback")[-1]["data"]["action"] == "none"


def test_push_opens_revert_pr(repo, monkeypatch):
    sha = merge(repo, "pr/demo-1")
    calls, pushed = [], []

    def fake_call(method, path, body=None):
        calls.append((method, path, body))
        if path == "/repos/o/r":
            return {"default_branch": "main"}
        return {"html_url": "https://github.com/o/r/pull/9"}

    monkeypatch.setattr(github, "_call", fake_call)
    monkeypatch.setattr(rollback, "push_branch", lambda repo_path, gh, branch: pushed.append((gh, branch)))

    result = rollback.rollback(repo, sha, push=True, github_repo="o/r")

    assert pushed == [("o/r", f"merge-gate/revert-{sha[:12]}")]
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1] == "/repos/o/r/pulls"
    assert post[2]["head"] == pushed[0][1] and post[2]["base"] == "main"
    assert post[2]["title"] == f"Revert {sha[:12]}: blocked by Merge Gate"
    assert result["run_hash"] in post[2]["body"] and "R1_" in post[2]["body"]
    assert result["pr_url"] == "https://github.com/o/r/pull/9"


def test_push_never_forces(monkeypatch):
    seen = []
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    monkeypatch.setattr(rollback, "_git", lambda repo, *args, **kw: seen.append((args, kw)) or "")
    rollback.push_branch("/r", "o/r", "merge-gate/revert-abc")
    args, kw = seen[0]
    assert args[0] == "push" and not any(a.startswith("-f") or a.startswith("--force") or a.startswith("+") for a in args)
    assert "t0k" not in " ".join(args)  # token travels in env config, not argv
    assert args[-1] == "refs/heads/merge-gate/revert-abc:refs/heads/merge-gate/revert-abc"


def test_cli_rollback(repo, capsys):
    sha = merge(repo, "pr/demo-1")
    assert cli_main(["rollback", sha, "--repo", repo, "--no-llm"]) == 1
    assert f"merge-gate/revert-{sha[:12]}" in capsys.readouterr().out
    assert cli_main(["rollback", sha, "--repo", repo, "--push", "--no-llm"]) == 2  # --push without --github
