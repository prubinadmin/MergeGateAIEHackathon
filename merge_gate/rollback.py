"""`python -m merge_gate rollback <sha>`: re-verify commits already on the branch; on BLOCK, revert them.

The pushed range is checked exactly like a PR: base = --base (the push's `before`; all-zero or missing
falls back to <sha>^1), head = <sha>, one diff. A merge commit is judged on what the merged PR brought
in. Skipped with exit 0: Merge Gate's own reverts (no revert-of-revert loop), root commits, and PRs a
code owner overrode (looked up on GitHub when GITHUB_TOKEN and --github are available). When the PR is
found, its body and author are the gate's inputs, the same as in the PR run.

On BLOCK the tree is reset to the merge-base on a new local branch merge-gate/revert-<short sha>,
built in a temporary `git worktree` so the user's checkout is never touched. With --push it pushes that
branch (never force) and opens a revert PR, reusing a branch left by an earlier attempt. Merging that
PR stays a human decision.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile

from .pr import PullRequest
from .schema import VerdictReport

log = logging.getLogger(__name__)

BRANCH_PREFIX = "merge-gate/revert-"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# A Merge Gate revert, landed as: the revert commit itself (rebase), a merge of the revert branch, or a
# squash merge (subject = the revert PR's title).
GATE_REVERT_RE = re.compile(
    r"^(revert: Merge Gate blocked "
    r"|Merge pull request #\d+ from [^/\s]+/" + re.escape(BRANCH_PREFIX)
    + r"|Merge branch '" + re.escape(BRANCH_PREFIX)
    + r"|Revert \S+: blocked by Merge Gate)"
)


class PreflightError(ValueError):
    """Bad flags or no GitHub access, found before any branch is created (CLI exit 2)."""


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


def resolve_base(repo: str, sha: str, base: str | None) -> str | None:
    """--base if usable, else the first parent of <sha>; None for a root commit."""
    if base and not re.fullmatch(r"0+", base):
        try:
            return _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
        except subprocess.CalledProcessError:
            log.warning("base %s is not in this clone; falling back to %s^1", base, sha[:12])
    parents = _git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    return parents[0] if parents else None


def delete_local_branch(repo: str, branch: str) -> None:
    if branch.startswith(BRANCH_PREFIX):
        subprocess.run(["git", "-C", repo, "branch", "-D", branch], capture_output=True)


def make_revert_branch(repo: str, base: str, sha: str, report: VerdictReport) -> tuple[str, bool]:
    """Branch at <sha> + one commit restoring merge-base(base, sha). Returns (branch, created_now).

    Built in a throwaway worktree. If anything fails the branch is deleted, so it never points at <sha>.
    """
    short = sha[:12]
    branch = BRANCH_PREFIX + short
    target = _git(repo, "merge-base", base, sha)
    if subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                      capture_output=True).returncode == 0:
        # A previous run's branch: reuse it only if it is exactly that revert.
        if (_git(repo, "rev-parse", f"{branch}^1") == sha
                and _git(repo, "rev-parse", f"{branch}^{{tree}}") == _git(repo, "rev-parse", f"{target}^{{tree}}")):
            return branch, False
        raise RuntimeError(f"branch {branch} already exists and is not the revert of {short}; not overwriting it")
    tmp = tempfile.mkdtemp(prefix="merge-gate-revert-")
    wt = os.path.join(tmp, "wt")
    ok = False
    try:
        _git(repo, "worktree", "add", "-q", "-b", branch, wt, sha)
        # Reset the tree to what was there before the range. Based on <sha>, so it never conflicts and a
        # merge commit needs no -m; the PR into the default branch merges it forward.
        _git(wt, "read-tree", "-u", "--reset", target)
        _git(wt, "-c", "user.name=Merge Gate", "-c", "user.email=merge-gate@users.noreply.github.com",
             "commit", "-q", "-F", "-", stdin=commit_message(short, report))
        ok = True
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
        if not ok:
            delete_local_branch(repo, branch)
    return branch, True


def push_branch(repo_path: str, github_repo: str, branch: str) -> None:
    """Push with the token in git's env config (not argv, not .git/config). Never --force."""
    from .github import _token

    auth = base64.b64encode(f"x-access-token:{_token()}".encode()).decode()
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}", GIT_TERMINAL_PROMPT="0")
    _git(repo_path, "push", f"https://github.com/{github_repo}.git", f"refs/heads/{branch}:refs/heads/{branch}", env=env)


def _github_access(github_repo: str) -> bool:
    from . import github

    if not REPO_RE.match(github_repo or ""):
        return False
    try:
        github._token()
        return True
    except github.GitHubError:
        return False


def _preflight(push: bool, github_repo: str) -> str:
    """Everything that can fail before a branch exists. Returns the default branch when pushing."""
    from . import github

    if not push:
        return ""
    if not REPO_RE.match(github_repo or ""):
        raise PreflightError("--push needs --github owner/repo")
    try:
        github._token()
        return github.default_branch(github_repo)
    except github.GitHubError as e:
        raise PreflightError(f"--push preflight failed: {e}") from None


def merged_pr(github_repo: str, sha: str) -> dict | None:
    from . import github

    prs = github.pulls_for_commit(github_repo, sha)
    return next((p for p in prs if p.get("merge_commit_sha") == sha), prs[0] if prs else None)


def override_status(github_repo: str, pr: dict) -> str:
    """The `merge-gate` status description if ci.py marked the PR head as owner-overridden, else ''."""
    from . import github

    for s in github.statuses(github_repo, pr["head"]["sha"]):
        if s.get("context") == github.CONTEXT and "overridden" in (s.get("description") or ""):
            return s["description"]
    return ""


LOGGED = ("pr_id", "sha", "base", "verdict", "run_hash", "action", "reason", "branch", "pr_url",
          "revert_sha", "revert_tree", "note")


def _log(result: dict, action: str, reason: str = "", **extra) -> dict:
    """Record the outcome on the audit chain and return the finished result."""
    from . import store

    result.update(action=action, reason=reason, **extra)
    store.append("rollback", {k: result[k] for k in LOGGED})
    return result


def _revert_ids(repo: str, branch: str) -> dict:
    """What identifies this revert once it lands on the default branch: the revert commit and its tree."""
    return {"branch": branch, "revert_sha": _git(repo, "rev-parse", f"refs/heads/{branch}"),
            "revert_tree": _git(repo, "rev-parse", f"refs/heads/{branch}^{{tree}}")}


def _logged_revert(repo: str, sha: str) -> bool:
    """True if <sha> is a revert this gate made and logged, landed by rebase (the revert commit itself), merge
    (its second parent is the revert commit) or squash (same parent as the revert, i.e. the blocked commit, and
    the same tree). The commit message never counts on its own: anyone can write 'revert: Merge Gate blocked'.
    A tree match alone is not enough either: an old revert's tree would let a forged rollback to a stale state
    through."""
    from . import store

    reverts = [r["data"] for r in store.read(kind="rollback") if r["data"].get("revert_tree")]
    if not reverts:
        return False
    parents = _git(repo, "rev-list", "--parents", "-n", "1", sha).split()
    for c in parents[:1] + parents[2:3]:  # the commit, and a merge commit's second parent
        c_parents, tree = _git(repo, "rev-list", "--parents", "-n", "1", c).split()[1:], _git(repo, "rev-parse", f"{c}^{{tree}}")
        for r in reverts:
            if c == r.get("revert_sha") or (c_parents[:1] == [r["sha"]] and tree == r["revert_tree"]):
                return True
    return False


def _lookup_pr(github_repo: str, sha: str, respect_override: bool) -> tuple[dict | None, str]:
    """The merged GitHub PR for <sha> (None without GitHub access) and, if a code owner overrode the gate on
    it, the reason to skip. A failed lookup warns and proceeds without the PR."""
    from . import github

    if not _github_access(github_repo):
        if respect_override:
            log.warning("owner override can't be checked without GITHUB_TOKEN and --github owner/repo; proceeding")
        return None, ""
    gh_pr = None
    try:
        gh_pr = merged_pr(github_repo, sha)
        if respect_override and gh_pr and (why := override_status(github_repo, gh_pr)):
            return gh_pr, f"PR #{gh_pr['number']} was merged after a code-owner override ({why}); not reverting"
    except github.GitHubError as e:
        log.warning("could not look up the PR for %s on GitHub: %s", sha[:12], e)
    return gh_pr, ""


def _verify(repo_path: str, result: dict, base_sha: str, message: str, gh_pr: dict | None, use_llm: bool) -> VerdictReport:
    """Run the gate on base_sha..sha exactly like a PR; the GitHub PR, when found, supplies body, title and
    author, otherwise the commit does. Logs the verdict and records it in `result`."""
    from . import store
    from .verify import verify

    sha = result["sha"]
    pr = PullRequest(
        pr_id=result["pr_id"], repo_path=repo_path, base_ref=base_sha, head_ref=sha,
        issue_text=(gh_pr.get("body") or "") if gh_pr else message,
        title=gh_pr.get("title", "") if gh_pr else _git(repo_path, "log", "-1", "--format=%s", sha),
        opened_by=(gh_pr.get("user") or {}).get("login", "") if gh_pr else _git(repo_path, "log", "-1", "--format=%an", sha),
    )
    report = verify(pr, use_llm=use_llm)
    store.log_report(report, source="rollback", sha=sha, base=base_sha)
    result.update(verdict=report.verdict, run_hash=report.run_hash, evidence=[e.id for e in report.evidence])
    return report


def _publish(repo_path: str, github_repo: str, default: str, base_sha: str, sha: str,
             report: VerdictReport) -> tuple[str, dict]:
    """Push the revert branch and open the PR. Returns (reason, fields for the result). A branch an earlier
    attempt pushed is reused (only its tree is known locally); a local branch made here is deleted again if the
    push or the PR fails."""
    from . import github

    short = sha[:12]
    branch = BRANCH_PREFIX + short
    title = f"Revert {short}: blocked by Merge Gate"
    body = (f"Merge Gate re-verified {base_sha[:12]}..{short} after it landed and blocked it.\n\n"
            + commit_message(short, report).split("\n", 2)[2])
    if github.branch_exists(github_repo, branch):
        existing = github.open_pr_for_branch(github_repo, branch)
        url = existing["html_url"] if existing else github.open_pr(github_repo, branch, default, title, body).get("html_url")
        tree = _git(repo_path, "rev-parse", _git(repo_path, "merge-base", base_sha, sha) + "^{tree}")
        return "reused the remote branch from an earlier attempt", {"branch": branch, "pr_url": url, "revert_tree": tree}
    branch, created = make_revert_branch(repo_path, base_sha, sha, report)
    try:
        push_branch(repo_path, github_repo, branch)
        url = github.open_pr(github_repo, branch, default, title, body).get("html_url")
    except Exception:
        if created:
            delete_local_branch(repo_path, branch)
        raise
    return "", {**_revert_ids(repo_path, branch), "pr_url": url}


def rollback(repo_path: str, sha: str, use_llm: bool = False, push: bool = False, github_repo: str = "",
             base: str | None = None, respect_override: bool = True) -> dict:
    """Re-verify <sha> and, on BLOCK, build the revert (pushed and opened as a PR with `push`). Raises
    PreflightError before anything is touched; otherwise returns the logged result dict."""
    default = _preflight(push, github_repo)
    sha = _git(repo_path, "rev-parse", "--verify", f"{sha}^{{commit}}")
    result: dict = {"pr_id": f"commit-{sha[:12]}", "sha": sha, "base": None, "verdict": None, "run_hash": None,
                    "evidence": [], "branch": None, "pr_url": None, "revert_sha": None, "revert_tree": None, "note": ""}
    message = _git(repo_path, "log", "-1", "--format=%B", sha)
    if GATE_REVERT_RE.match(message):  # cheap pre-filter; only the store decides (fail closed)
        if _logged_revert(repo_path, sha):
            return _log(result, "skip", "commit is a Merge Gate revert; not re-verifying it (no revert-of-revert loop)")
        result["note"] = "message claims to be a Merge Gate revert but no logged revert matches; re-verifying it"
        log.warning(result["note"])
    base_sha = resolve_base(repo_path, sha, base)
    if base_sha is None:
        return _log(result, "skip", "nothing to compare: root commit")
    result["base"] = base_sha
    gh_pr, overridden = _lookup_pr(github_repo, sha, respect_override)
    if overridden:
        return _log(result, "skip", overridden)
    report = _verify(repo_path, result, base_sha, message, gh_pr, use_llm)
    if report.verdict != "BLOCK":
        findings = f" (findings for the owner: {', '.join(result['evidence'])})" if report.evidence else ""
        return _log(result, "none", f"verdict {report.verdict}: rollback only reverts BLOCK{findings}")
    if not push:
        branch, _ = make_revert_branch(repo_path, base_sha, sha, report)
        return _log(result, "revert_branch", **_revert_ids(repo_path, branch))
    reason, published = _publish(repo_path, github_repo, default, base_sha, sha, report)
    return _log(result, "revert_pr", reason, **published)


def summary(result: dict) -> str:
    """The CLI's one-line stderr summary: the verdict (or SKIPPED) and what rollback did."""
    what = {"none": result["reason"], "skip": result["reason"],
            "revert_branch": f"created local branch {result['branch']}",
            "revert_pr": f"revert PR {result['pr_url']}" + (f" ({result['reason']})" if result["reason"] else "")}[result["action"]]
    return f"[merge-gate] {result['verdict'] or 'SKIPPED'}: {what}"
