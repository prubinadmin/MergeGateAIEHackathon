"""A pull request as the gate sees it: a git repo plus a base and a head ref."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class PullRequest:
    pr_id: str
    repo_path: str  # local clone of the target repo
    base_ref: str  # what the PR merges into
    head_ref: str  # the PR's tip
    issue_text: str = ""  # the issue the PR claims to fix; the test writer sees ONLY this + the interface
    title: str = ""
    opened_by: str = ""  # who opened it (outside contributor, agent name)

    def git(self, *args: str) -> str:
        out = subprocess.run(
            ["git", "-C", self.repo_path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return out.stdout

    def diff(self) -> str:
        """Unified diff, base...head (changes the PR introduces)."""
        return self.git("diff", "--unified=3", f"{self.base_ref}...{self.head_ref}")

    def changed_files(self) -> list[str]:
        out = self.git("diff", "--name-only", f"{self.base_ref}...{self.head_ref}")
        return [line for line in out.splitlines() if line]

    def file_at(self, ref: str, path: str) -> str | None:
        """File contents at a ref, or None if the file does not exist there."""
        try:
            return self.git("show", f"{ref}:{path}")
        except subprocess.CalledProcessError:
            return None
