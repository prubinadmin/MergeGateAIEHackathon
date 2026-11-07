"""`python -m merge_gate rollback <sha>`: re-verify a commit already on the branch; on BLOCK, revert it.

The commit is checked exactly like a PR: base = <sha>^1 (first parent), head = <sha>, so a merge commit
is judged on what the merged PR brought in. On BLOCK a revert commit is made on a new local branch
merge-gate/revert-<short sha>, built in a temporary `git worktree` so the user's checkout and current
branch are never touched. With --push it pushes that branch (never force, never the default branch)
and opens a revert PR. Merging that PR stays a human decision.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile

from .pr import PullRequest
from .schema import VerdictReport

BRANCH_PREFIX = "merge-gate/revert-"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _git(repo: str, *args: str, stdin: str | None = None, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
        check=True, env=env,
    ).stdout.strip()


def blocking_ids(report: VerdictReport) -> list[str]:
    return list(dict.fromkeys(e.id for e in report.evidence if e.severity == "block"))


def commit_message(short: str, report: VerdictReport) -> str:
    lines = [f"revert: Merge Gate blocked {short} ({', '.join(blocking_ids(report))})", ""]
    lines += [f"- [{e.severity}] {e.id}: {e.detail}" for e in report.evidence]
    lines += ["", f"run_hash: {report.run_hash}"]
    return "\n".join(lines) + "\n"


def make_revert_branch(repo: str, sha: str, report: VerdictReport) -> str:
    """Revert <sha> on a new branch based on <sha>, in a throwaway worktree. Returns the branch name."""
    short = sha[:12]
    branch = BRANCH_PREFIX + short
    if subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                      capture_output=True).returncode == 0:
        raise RuntimeError(f"branch {branch} already exists; not overwriting it")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    tmp = tempfile.mkdtemp(prefix="merge-gate-revert-")
    wt = os.path.join(tmp, "wt")
    try:
        _git(repo, "worktree", "add", "-q", "-b", branch, wt, sha)
        # Based on <sha> itself, so the revert can never conflict; the PR into the default branch merges it forward.
        _git(wt, "revert", "--no-commit", *(["-m", "1"] if len(parents) > 1 else []), sha)
        _git(wt, "-c", "user.name=Merge Gate", "-c", "user.email=merge-gate@users.noreply.github.com",
             "commit", "-q", "-F", "-", stdin=commit_message(short, report))
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return branch


def push_branch(repo_path: str, github_repo: str, branch: str) -> None:
    """Push with the token in git's env config (not argv, not .git/config). Never --force."""
    from .github import _token

    auth = base64.b64encode(f"x-access-token:{_token()}".encode()).decode()
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}", GIT_TERMINAL_PROMPT="0")
    _git(repo_path, "push", f"https://github.com/{github_repo}.git", f"refs/heads/{branch}:refs/heads/{branch}", env=env)


def rollback(repo_path: str, sha: str, use_llm: bool = False, push: bool = False, github_repo: str = "") -> dict:
    from . import github, store
    from .verify import verify

    if push and not REPO_RE.match(github_repo or ""):
        raise ValueError("--push needs --github owner/repo")
    sha = _git(repo_path, "rev-parse", "--verify", f"{sha}^{{commit}}")
    short = sha[:12]
    pr = PullRequest(
        pr_id=f"commit-{short}", repo_path=repo_path, base_ref=f"{sha}^1", head_ref=sha,
        issue_text=_git(repo_path, "log", "-1", "--format=%B", sha), title=_git(repo_path, "log", "-1", "--format=%s", sha),
        opened_by=_git(repo_path, "log", "-1", "--format=%an", sha),
    )
    report = verify(pr, use_llm=use_llm)
    result: dict = {"pr_id": pr.pr_id, "sha": sha, "verdict": report.verdict, "run_hash": report.run_hash,
                    "evidence": [e.id for e in report.evidence], "branch": None, "pr_url": None}

    if report.verdict != "BLOCK":
        result["action"] = "none"
        result["reason"] = f"verdict {report.verdict}: rollback only reverts BLOCK" + (
            f" (findings for the owner: {', '.join(result['evidence'])})" if report.evidence else "")
    else:
        branch = make_revert_branch(repo_path, sha, report)
        if not branch.startswith(BRANCH_PREFIX):  # belt and braces: never push anything else
            raise RuntimeError(branch)
        result.update(action="revert_branch", branch=branch)
        if push:
            base = github.default_branch(github_repo)
            if branch == base:
                raise RuntimeError("refusing to push to the default branch")
            push_branch(repo_path, github_repo, branch)
            body = commit_message(short, report).split("\n", 2)[2]
            resp = github.open_pr(github_repo, branch, base, f"Revert {short}: blocked by Merge Gate",
                                  f"Merge Gate re-verified {sha} after it landed and blocked it.\n\n{body}")
            result.update(action="revert_pr", pr_url=resp.get("html_url"))

    store.append("rollback", result)
    return result


def main(sha: str, repo_path: str, use_llm: bool, push: bool, github_repo: str) -> int:
    import json

    result = rollback(repo_path, sha, use_llm=use_llm, push=push, github_repo=github_repo)
    print(json.dumps(result, indent=2))
    msg = {"none": result.get("reason"), "revert_branch": f"created local branch {result['branch']}",
           "revert_pr": f"opened revert PR {result['pr_url']}"}[result["action"]]
    print(f"[merge-gate] {result['verdict']}: {msg}", file=sys.stderr)
    return 1 if result["verdict"] == "BLOCK" else 0
