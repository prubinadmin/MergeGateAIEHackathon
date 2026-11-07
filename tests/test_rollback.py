"""rollback: re-verify a merged commit, revert it on BLOCK.

No network, and nothing in merge_gate is mocked: the GitHub REST API is faked at urllib.request.urlopen, and
pushes go through real git to a local bare repo that https://github.com/o/r.git is rewritten to (insteadOf).
"""

import io
import json
import subprocess
import urllib.error
import urllib.request

import pytest

from merge_gate import github, rollback, store
from merge_gate.cli import main as cli_main
from merge_gate.demo import build_demo_repo

from helpers import git


def out(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


def no_token(monkeypatch, tmp_path):
    """Never pick up a real token from the environment or a .env.local in the cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    no_token(monkeypatch, tmp_path)
    return build_demo_repo(str(tmp_path))


def fake_remote(repo, tmp_path, exists=True):
    """Point https://github.com/o/r.git at a local bare repo for this clone; returns the bare repo's path.
    exists=False points it at a missing path, so a push really fails."""
    bare = str(tmp_path / "remote.git")
    if exists:
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    git(repo, "config", f"url.{bare}.insteadOf", "https://github.com/o/r.git")
    return bare


def remote_branches(bare):
    return out(bare, "for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()


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


class FakeGitHub:
    """Fake GitHub REST API at the HTTP layer (urllib.request.urlopen); the real github._call runs.
    Knobs: prs (commits/{sha}/pulls), statuses, remote_branch, open_prs, fail (path substrings -> HTTP 500)."""

    def __init__(self, monkeypatch, prs=(), statuses=(), remote_branch=False, open_prs=(), fail=()):
        self.calls, self.prs, self.statuses = [], list(prs), list(statuses)
        self.remote_branch, self.open_prs, self.fail = remote_branch, list(open_prs), set(fail)
        monkeypatch.setenv("GITHUB_TOKEN", "t0k")
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def urlopen(self, req, timeout=None):
        assert req.full_url.startswith(github.API + "/"), req.full_url
        assert req.get_header("Authorization") == "Bearer t0k"
        method, path = req.get_method(), req.full_url[len(github.API):]
        body = json.loads(req.data) if req.data is not None else None
        self.calls.append((method, path, body))
        status, payload = self.respond(method, path)
        data = io.BytesIO(json.dumps(payload).encode())
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, data)
        return data

    def respond(self, method, path):
        for f in self.fail:
            if f in path:
                return 500, {"message": "boom"}
        if path == "/repos/o/r":
            return 200, {"default_branch": "main"}
        if path.endswith("/pulls") and "/commits/" in path:
            return 200, self.prs
        if path.endswith("/status"):
            return 200, {"statuses": self.statuses}
        if "/git/ref/heads/" in path:
            return (200, {"ref": path}) if self.remote_branch else (404, {"message": "Not Found"})
        if method == "GET" and "/pulls?" in path:
            return 200, self.open_prs
        if method == "POST" and path == "/repos/o/r/pulls":
            return 200, {"html_url": "https://github.com/o/r/pull/9"}
        raise AssertionError(path)

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def revert_branches(repo):
    return [b for b in out(repo, "branch", "--list", "--format=%(refname:short)").splitlines() if b.startswith("merge-gate/revert-")]


def test_push_opens_revert_pr(repo, tmp_path, monkeypatch):
    sha = merge(repo, "pr/demo-1")
    bare = fake_remote(repo, tmp_path)
    fake = FakeGitHub(monkeypatch)
    calls = fake.calls

    result = rollback.rollback(repo, sha, push=True, github_repo="o/r")

    branch = f"merge-gate/revert-{sha[:12]}"
    assert remote_branches(bare) == [branch]  # really pushed, and only that branch
    assert out(bare, "rev-parse", branch) == out(repo, "rev-parse", branch)
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1] == "/repos/o/r/pulls"
    assert post[2]["head"] == branch and post[2]["base"] == "main"
    assert post[2]["title"] == f"Revert {sha[:12]}: blocked by Merge Gate"
    assert result["run_hash"] in post[2]["body"] and "R1_" in post[2]["body"]
    assert result["pr_url"] == "https://github.com/o/r/pull/9"


def test_push_never_forces(tmp_path, monkeypatch):
    no_token(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    branch, a, b = "merge-gate/revert-abc", ("A", "a@example.com"), ("B", "b@example.com")
    local = str(tmp_path / "local")
    subprocess.run(["git", "init", "-q", "-b", "main", local], check=True)
    git(local, "commit", "-q", "--allow-empty", "-m", "base", author=a)
    bare = fake_remote(local, tmp_path)
    git(local, "push", "-q", bare, "main")
    git(local, "checkout", "-q", "-b", branch)
    git(local, "commit", "-q", "--allow-empty", "-m", "ours", author=a)
    # someone else's commit already sits on the remote branch: only a force push could replace it
    other = str(tmp_path / "other")
    subprocess.run(["git", "clone", "-q", bare, other], check=True)
    git(other, "checkout", "-q", "-b", branch)
    git(other, "commit", "-q", "--allow-empty", "-m", "theirs", author=b)
    git(other, "push", "-q", "origin", branch)
    theirs = out(bare, "rev-parse", branch)

    seen, real_run = [], subprocess.run

    def spy_run(argv, *args, **kw):  # observe the git subprocess boundary; the real git still runs
        seen.append((list(argv), kw.get("env") or {}))
        return real_run(argv, *args, **kw)

    monkeypatch.setattr(subprocess, "run", spy_run)
    with pytest.raises(subprocess.CalledProcessError):  # non-fast-forward: rejected, never forced
        rollback.push_branch(local, "o/r", branch)
    monkeypatch.setattr(subprocess, "run", real_run)
    assert out(bare, "rev-parse", branch) == theirs  # remote branch untouched

    args, env = next((argv[3:], env) for argv, env in seen if argv[3:4] == ["push"])
    assert not any(x.startswith("-f") or x.startswith("--force") or x.startswith("+") for x in args)
    assert "t0k" not in " ".join(args)  # token travels in env config, not argv
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert args[-1] == f"refs/heads/{branch}:refs/heads/{branch}"

    git(other, "push", "-q", "origin", "--delete", branch)  # nothing in the way: a normal push lands
    rollback.push_branch(local, "o/r", branch)
    assert out(bare, "rev-parse", branch) == out(local, "rev-parse", branch)


def test_cli_rollback(repo, capsys):
    sha = merge(repo, "pr/demo-1")
    assert cli_main(["rollback", sha, "--repo", repo, "--no-llm"]) == 1
    assert f"merge-gate/revert-{sha[:12]}" in capsys.readouterr().out
    assert cli_main(["rollback", sha, "--repo", repo, "--push", "--no-llm"]) == 2  # --push without --github


# --- revert-of-revert loop ---

def test_gate_reverts_are_skipped(repo, capsys):
    sha = merge(repo, "pr/demo-1")
    branch = rollback.rollback(repo, sha)["branch"]
    revert_commit = out(repo, "rev-parse", branch)
    # the revert commit itself (rebase merge) and a GitHub-style merge of the revert branch
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge pull request #7 from o/{branch}\n\nRevert", branch,
        author=("Maintainer", "m@example.com"))
    merged = out(repo, "rev-parse", "HEAD")
    for target in (revert_commit, merged):
        result = rollback.rollback(repo, target)
        assert result["action"] == "skip" and result["verdict"] is None and "Merge Gate revert" in result["reason"]
    assert revert_branches(repo) == [branch]  # nothing new
    capsys.readouterr()
    assert cli_main(["rollback", merged, "--repo", repo, "--no-llm"]) == 0
    assert "revert-of-revert" in capsys.readouterr().err


def test_squash_merged_gate_revert_is_skipped():
    assert rollback.GATE_REVERT_RE.match("Revert 0123456789ab: blocked by Merge Gate (#12)\n\n...")
    assert rollback.GATE_REVERT_RE.match("Merge pull request #3 from acme/merge-gate/revert-0123456789ab\n")
    assert not rollback.GATE_REVERT_RE.match("Merge pull request #3 from acme/feature/revert-thing\n")
    assert not rollback.GATE_REVERT_RE.match("fix: revert: Merge Gate blocked nothing")


# --- owner override + PR inputs ---

def test_owner_override_is_respected(repo, monkeypatch):
    sha = merge(repo, "pr/demo-1")
    fake = FakeGitHub(monkeypatch, prs=[{"number": 4, "merge_commit_sha": sha, "head": {"sha": "abc"}, "body": "", "user": {"login": "x"}}],
                      statuses=[{"context": "merge-gate", "state": "success",
                                 "description": "BLOCK overridden: approved on GitHub by owner peter-gh"}])
    result = rollback.rollback(repo, sha, github_repo="o/r")
    assert result["action"] == "skip" and "PR #4" in result["reason"] and "overridden" in result["reason"]
    assert revert_branches(repo) == [] and not fake.posts()
    assert ("GET", "/repos/o/r/commits/abc/status", None) in fake.calls
    # --no-respect-override reverts anyway
    assert rollback.rollback(repo, sha, github_repo="o/r", respect_override=False)["action"] == "revert_branch"


def test_override_text_matches_what_ci_writes():
    import inspect

    from merge_gate import ci
    assert 'overridden: approved on GitHub by owner' in inspect.getsource(ci.main)


def test_found_pr_supplies_issue_text_and_author(repo, monkeypatch):
    from merge_gate import verify as verify_mod
    sha = merge(repo, "pr/demo-1")
    FakeGitHub(monkeypatch, prs=[{"number": 4, "merge_commit_sha": sha, "head": {"sha": "abc"}, "title": "Speed up discounts",
                                  "body": "Make apply_discount faster.", "user": {"login": "agent-bot"}}],
               statuses=[{"context": "merge-gate", "description": "BLOCK: R1_DELETED_TEST. Sent to Peter."}])
    seen, real = [], verify_mod.verify
    monkeypatch.setattr(verify_mod, "verify", lambda pr, **kw: seen.append(pr) or real(pr, **kw))
    assert rollback.rollback(repo, sha, github_repo="o/r")["verdict"] == "BLOCK"
    assert (seen[0].issue_text, seen[0].opened_by, seen[0].title) == ("Make apply_discount faster.", "agent-bot", "Speed up discounts")


def test_without_github_warns_and_uses_commit_message(repo, monkeypatch, capsys):
    from merge_gate import verify as verify_mod
    sha = merge(repo, "pr/demo-1")
    seen, real = [], verify_mod.verify
    monkeypatch.setattr(verify_mod, "verify", lambda pr, **kw: seen.append(pr) or real(pr, **kw))
    assert rollback.rollback(repo, sha)["action"] == "revert_branch"
    assert "override can't be checked" in capsys.readouterr().err
    assert seen[0].issue_text == out(repo, "log", "-1", "--format=%B", sha) and seen[0].opened_by == "Maintainer"


# --- multi-commit range ---

def test_range_verifies_whole_push(repo):
    before = out(repo, "rev-parse", "HEAD")
    before_tree = out(repo, "rev-parse", "HEAD^{tree}")
    merge(repo, "pr/demo-1")        # blocked, buried in the middle of the push
    head = merge(repo, "pr/demo-3")  # clean tip
    assert rollback.rollback(repo, head)["verdict"] != "BLOCK"  # the tip alone looks fine
    result = rollback.rollback(repo, head, base=before)
    assert result["verdict"] == "BLOCK" and result["base"] == before
    assert out(repo, "rev-parse", f"{result['branch']}^{{tree}}") == before_tree  # whole push undone
    assert out(repo, "rev-parse", f"{result['branch']}^1") == head


def test_cli_base_flag(repo):
    before = out(repo, "rev-parse", "HEAD")
    merge(repo, "pr/demo-1")
    head = merge(repo, "pr/demo-3")
    assert cli_main(["rollback", head, "--repo", repo, "--base", before, "--no-llm"]) == 1


def test_all_zero_base_falls_back_to_first_parent(repo):
    sha = merge(repo, "pr/demo-1")
    result = rollback.rollback(repo, sha, base="0" * 40)
    assert result["base"] == out(repo, "rev-parse", f"{sha}^1") and result["verdict"] == "BLOCK"


# --- root commit ---

def test_root_commit_has_nothing_to_compare(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    r = str(tmp_path / "solo")
    subprocess.run(["git", "init", "-q", "-b", "main", r], check=True)
    (tmp_path / "solo" / "a.py").write_text("x = 1\n")
    git(r, "add", "a.py")
    git(r, "commit", "-q", "-m", "init", author=("A", "a@example.com"))
    assert cli_main(["rollback", "HEAD", "--repo", r, "--no-llm"]) == 0
    err = capsys.readouterr().err
    assert "nothing to compare: root commit" in err and "Traceback" not in err


# --- branch hygiene ---

def test_preflight_fails_before_any_branch(repo, monkeypatch):
    sha = merge(repo, "pr/demo-1")  # the repo fixture leaves no GITHUB_TOKEN
    assert cli_main(["rollback", sha, "--repo", repo, "--push", "--github", "o/r", "--no-llm"]) == 2
    assert cli_main(["rollback", sha, "--repo", repo, "--push", "--github", "not a repo", "--no-llm"]) == 2
    FakeGitHub(monkeypatch, fail={"/repos/o/r"})  # token ok, default-branch lookup fails
    assert cli_main(["rollback", sha, "--repo", repo, "--push", "--github", "o/r", "--no-llm"]) == 2
    assert revert_branches(repo) == [] and store.read(kind="rollback") == []


def test_failed_push_deletes_local_branch(repo, tmp_path, monkeypatch):
    sha = merge(repo, "pr/demo-1")
    FakeGitHub(monkeypatch)
    fake_remote(repo, tmp_path, exists=False)  # the real git push fails
    with pytest.raises(subprocess.CalledProcessError):
        rollback.rollback(repo, sha, push=True, github_repo="o/r")
    assert revert_branches(repo) == []


def test_failed_commit_leaves_no_branch_at_blocked_sha(repo, tmp_path):
    sha = merge(repo, "pr/demo-1")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hooks))  # the real git commit fails after the worktree branch exists
    with pytest.raises(subprocess.CalledProcessError):
        rollback.rollback(repo, sha)
    assert revert_branches(repo) == [] and len(out(repo, "worktree", "list").splitlines()) == 1


def test_existing_remote_branch_is_reused(repo, tmp_path, monkeypatch):
    sha = merge(repo, "pr/demo-1")
    bare = fake_remote(repo, tmp_path)
    fake = FakeGitHub(monkeypatch, remote_branch=True)  # pushed earlier, PR creation failed
    result = rollback.rollback(repo, sha, push=True, github_repo="o/r")
    assert result["action"] == "revert_pr" and result["pr_url"] == "https://github.com/o/r/pull/9"
    assert remote_branches(bare) == [] and len(fake.posts()) == 1 and revert_branches(repo) == []  # nothing pushed
    fake = FakeGitHub(monkeypatch, remote_branch=True, open_prs=[{"html_url": "https://github.com/o/r/pull/8"}])
    assert rollback.rollback(repo, sha, push=True, github_repo="o/r")["pr_url"] == "https://github.com/o/r/pull/8"
    assert not fake.posts()


def test_existing_local_branch_is_reused(repo):
    sha = merge(repo, "pr/demo-1")
    first = rollback.rollback(repo, sha)
    tip = out(repo, "rev-parse", first["branch"])
    assert rollback.rollback(repo, sha)["branch"] == first["branch"]
    assert out(repo, "rev-parse", first["branch"]) == tip


# --- logging ---

def test_verdict_and_action_are_logged_on_one_chain(repo):
    sha = merge(repo, "pr/demo-1")
    result = rollback.rollback(repo, sha)
    verdict = store.read(kind="verdict")[-1]["data"]
    assert verdict["source"] == "rollback" and verdict["sha"] == sha and verdict["run_hash"] == result["run_hash"]
    action = store.read(kind="rollback")[-1]["data"]
    assert action["action"] == "revert_branch" and action["branch"] == result["branch"] and "pr_url" in action
    assert store.verify_chain() == (True, -1)
