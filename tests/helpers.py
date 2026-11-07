"""Build throwaway git repos with a base branch and a PR branch."""

from __future__ import annotations

import os
import subprocess

from merge_gate.pr import PullRequest


def git(repo: str, *args: str, author: tuple[str, str] | None = None) -> None:
    env = dict(os.environ)
    if author:
        env.update(
            GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
            GIT_COMMITTER_NAME=author[0], GIT_COMMITTER_EMAIL=author[1],
        )
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def write(repo: str, files: dict[str, str | None]) -> None:
    for path, src in files.items():
        full = os.path.join(repo, path)
        if src is None:
            if os.path.exists(full):
                os.remove(full)
            continue
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)


def make_pr(tmp_path, base: dict[str, str], head: dict[str, str | None], issue: str = "") -> PullRequest:
    """base: files at main. head: files changed on pr/1 (None = delete)."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "base@example.com")
    git(repo, "config", "user.name", "Base")
    write(repo, base)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "pr/1")
    write(repo, head)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pr")
    git(repo, "checkout", "-q", "main")
    return PullRequest(pr_id="t", repo_path=repo, base_ref="main", head_ref="pr/1", issue_text=issue)
