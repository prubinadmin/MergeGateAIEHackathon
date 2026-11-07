"""Run the real gate on a LIVE pull request from any public GitHub repo (owner: Michael).

    python -m merge_gate github vllm                      # most-starred repo named vllm, its newest open PR
    python -m merge_gate github psf/requests              # that repo's newest open PR
    python -m merge_gate github psf/requests#6900         # one PR (also owner/repo/pull/N or the full URL)

resolve() turns the query into a PR via the GitHub API; materialize() makes a blame-capable partial clone
(`--filter=blob:none`: full history, blobs fetched on demand) with `origin/<base>` and `pr-<N>` as refs, so
PullRequest.diff(), blame-based owners and `git archive` for the sandbox all work; scan() runs verify() on it.

Safety. The gate's model-written tests import the repo's code inside merge_gate.sandbox: a `git archive` copy
in a temp dir, a scrubbed environment (no keys, tokens or phone numbers) and a subprocess with a timeout.
That is process isolation, not a security sandbox: with --llm, code from a public repo runs on this machine
as the current user. --no-llm (rules + blame owners) runs nothing from the repo. Owners of public repos are
not in OWNER_PHONES, so paging reports "no phone on file": expected, the UI shows who WOULD be paged.
Heavy repos: imports that fail in the sandbox (torch, CUDA) make the generated tests error on base, which
testgen reports as a note ("generated tests do not run on base"), never a verdict and never a crash.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import github
from .github import GitHubError
from .pr import PullRequest
from .schema import VerdictReport

MAX_REPO_KB = 2 * 1024 * 1024  # refuse repos the API reports above 2 GB
CLONE_TIMEOUT_S = 180

_PR = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?"
    r"(?:(?:#|/pulls?/)(\d+)(?:/[\w./-]*)?)?/?$"
)


@dataclass
class ResolvedPR:
    owner: str
    repo: str
    number: int
    title: str
    body: str
    author: str
    base_ref: str
    head_sha: str
    html_url: str
    size_kb: int = 0  # repo size as the API reports it (KB); 0 = unknown

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def pr_id(self) -> str:
        return f"gh:{self.full_name}#{self.number}"


def parse_query(query: str) -> tuple[str, str, int | None] | None:
    """owner/repo[#N | /pull/N | full URL] -> (owner, repo, N or None); a bare word -> None (search it)."""
    m = _PR.match(query.strip())
    if not m:
        return None
    owner, repo, num = m.groups()
    return owner, repo, int(num) if num else None


def _api(path: str) -> dict | list:
    """GET api.github.com; authenticated through github._call when a token is set, anonymous otherwise."""
    try:
        github._token()
    except GitHubError:
        req = urllib.request.Request(f"{github.API}{path}", headers={"Accept": "application/vnd.github+json", "User-Agent": "merge-gate"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise GitHubError(f"GET {path}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}") from None
    return github._call("GET", path)


def _from_api(pr: dict) -> ResolvedPR:
    base_repo = (pr.get("base") or {}).get("repo") or {}
    full = base_repo.get("full_name") or ""
    owner, _, repo = full.partition("/")
    return ResolvedPR(
        owner=owner, repo=repo, number=int(pr["number"]), title=pr.get("title") or "", body=pr.get("body") or "",
        author=(pr.get("user") or {}).get("login", ""), base_ref=pr["base"]["ref"], head_sha=pr["head"]["sha"],
        html_url=pr.get("html_url") or f"https://github.com/{full}/pull/{pr['number']}", size_kb=int(base_repo.get("size") or 0),
    )


def resolve(query: str) -> ResolvedPR:
    """owner/repo#N -> that PR; owner/repo -> its newest open PR; a bare word -> the most-starred repo of that name."""
    query = query.strip()
    if not query:
        raise GitHubError("empty query")
    parsed = parse_query(query)
    if parsed is None:
        if re.search(r"[\s/]", query):
            raise GitHubError(f"cannot read {query!r}: use owner/repo, owner/repo#N, a PR URL or one word to search")
        found = _api(f"/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc&per_page=1")
        items = found.get("items") or [] if isinstance(found, dict) else []
        if not items:
            raise GitHubError(f"no GitHub repository matches {query!r}")
        full = items[0]["full_name"]
        owner, _, repo = full.partition("/")
        number = None
    else:
        owner, repo, number = parsed
    if number is None:
        prs = _api(f"/repos/{owner}/{repo}/pulls?state=open&sort=created&direction=desc&per_page=1")
        if not prs:
            raise GitHubError(f"{owner}/{repo} has no open pull requests")
        return _from_api(prs[0])
    return _from_api(_api(f"/repos/{owner}/{repo}/pulls/{number}"))


def default_clone_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def materialize(r: ResolvedPR, workdir: str | None = None, clone_url=default_clone_url,
                timeout_s: int = CLONE_TIMEOUT_S) -> PullRequest:
    """Blame-capable partial clone in a fresh temp dir; base_ref=origin/<base>, head_ref=pr-<N>. Cleans up on failure."""
    if r.size_kb > MAX_REPO_KB:
        raise GitHubError(f"{r.full_name} is {r.size_kb // 1024} MB on GitHub; the gate refuses repos over 2 GB")
    dest = tempfile.mkdtemp(prefix=f"mergegate-gh-{r.repo}-", dir=workdir)
    deadline = time.monotonic() + timeout_s
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}

    def git(*args: str) -> None:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(args, timeout_s)
        proc = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=left, env=env)
        if proc.returncode:
            raise GitHubError(f"git {args[0]} failed for {r.full_name}: {proc.stderr.strip()[-300:]}")

    try:
        # Checking out <base> prefetches every blob of the base tree in one request; blame's history blobs
        # and the PR's own files arrive on demand. ponytail: blame on a 1000-commit file is one fetch per
        # revision; batch-prefetch the touched files' history if that shows up in timings.
        git("clone", "--quiet", "--filter=blob:none", "--single-branch", "--branch", r.base_ref, clone_url(r.owner, r.repo), dest)
        git("-C", dest, "fetch", "--quiet", "--no-tags", "origin", f"pull/{r.number}/head:pr-{r.number}")
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitHubError(f"cloning {r.full_name} took longer than {timeout_s}s") from None
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return PullRequest(
        pr_id=r.pr_id, repo_path=dest, base_ref=f"origin/{r.base_ref}", head_ref=f"pr-{r.number}",
        issue_text=r.body, title=r.title, opened_by=r.author,
    )


def scan(query: str, use_llm: bool = False, use_subq: bool = False, on_stage=None,
         workdir: str | None = None) -> tuple[VerdictReport, PullRequest, ResolvedPR]:
    """resolve -> materialize -> verify, with the same flags the CLI passes to verify()."""
    from .verify import verify

    resolved = resolve(query)
    if on_stage:
        on_stage("clone", "start", {"url": resolved.html_url, "repo": resolved.full_name})
    t0 = time.monotonic()
    pr = materialize(resolved, workdir)
    if on_stage:
        on_stage("clone", "done", {"ms": int((time.monotonic() - t0) * 1000), "repo_path": pr.repo_path})
    return verify(pr, use_llm=use_llm, use_subq=use_subq, on_stage=on_stage), pr, resolved
