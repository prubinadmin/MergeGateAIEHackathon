"""War Room cases from a real GitHub repo's open pull requests (owner: Michael).

Set MERGE_GATE_DEMO_GITHUB=owner/name (e.g. Michaelwei08/merge-gate-demo-shop) and `serve` lists that
repo's open PRs as demo-<number>, runs the real gate on a local clone, and publishes each verdict back to
the PR (merge-gate status + comment). Nothing here depends on GitHub Actions firing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from . import github
from .pr import PullRequest

ROOT = os.path.join("runs", "demo-github")


@dataclass
class GithubPr:
    pr: PullRequest
    number: int
    sha: str
    url: str


def _git(repo_dir: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def sync(repo: str, root: str | None = None) -> str:
    """Clone once, then fetch main and every PR head. Returns the local clone path."""
    root = root or ROOT
    path = os.path.join(root, repo.replace("/", "__"))
    if not os.path.isdir(os.path.join(path, ".git")):
        os.makedirs(root, exist_ok=True)
        subprocess.run(["git", "clone", "-q", f"https://github.com/{repo}.git", path], check=True, capture_output=True)
    _git(path, "fetch", "-q", "--force", "origin",
         "+refs/heads/*:refs/remotes/origin/*", "+refs/pull/*/head:refs/remotes/origin/pull/*")
    return path


def open_prs(repo: str, path: str) -> list[GithubPr]:
    out = []
    for p in github._call("GET", f"/repos/{repo}/pulls?state=open&per_page=30"):
        sha = p["head"]["sha"]
        try:
            author = _git(path, "log", "-1", "--format=%an", sha).strip()
        except subprocess.CalledProcessError:
            continue  # head not fetched (should not happen after sync)
        opened_by = {"coding-agent": "A coding agent", "outside-contributor": "An outside contributor"}.get(author, author)
        out.append(GithubPr(
            pr=PullRequest(pr_id=f"demo-{p['number']}", repo_path=path, base_ref=f"origin/{p['base']['ref']}",
                           head_ref=sha, issue_text=p.get("body") or "", title=p.get("title") or "", opened_by=opened_by),
            number=int(p["number"]), sha=sha, url=p["html_url"]))
    return sorted(out, key=lambda g: g.number)
