"""Ownership resolver (owner: Michael): who wrote the lines this PR changes.

git blame on the base ref for every changed/removed line, weighted by lines and recency.
CODEOWNERS is only the fallback.
"""

from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from datetime import datetime, timezone

from .pr import PullRequest
from .schema import Owner

_FILE = re.compile(r"^--- (?:a/(.+)|/dev/null)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
HALF_LIFE_DAYS = 180  # a line last touched 180 days before the newest touch counts half


def base_line_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    """Base-side (start, count) ranges per file for removed/modified lines only (context lines skipped).
    A pure insertion blames the base line it follows."""
    lines: dict[str, list[int]] = defaultdict(list)
    path, base, removed_in_block = None, 0, False
    for line in diff.splitlines():
        if m := _FILE.match(line):
            path = m[1]  # None for new files: nothing to blame
        elif m := _HUNK.match(line):
            # in a zero-count hunk (-U0 insertions) git's start is the line the insertion follows
            base, removed_in_block = int(m[1]) + (m[2] == "0"), False
        elif path and line.startswith("-"):
            lines[path].append(base)
            base, removed_in_block = base + 1, True
        elif path and line.startswith("+") and not line.startswith("+++"):
            if not removed_in_block:  # pure insertion: blame the line above (or the first line)
                anchor = max(base - 1, 1)
                if anchor not in lines[path]:
                    lines[path].append(anchor)
                removed_in_block = True
        elif line.startswith(" "):
            base, removed_in_block = base + 1, False
    return {f: _to_ranges(sorted(set(ns))) for f, ns in lines.items() if ns}


def _to_ranges(ns: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for n in ns:
        if ranges and ranges[-1][0] + ranges[-1][1] == n:
            ranges[-1] = (ranges[-1][0], ranges[-1][1] + 1)
        else:
            ranges.append((n, 1))
    return ranges


def _blame(pr: PullRequest, path: str, start: int, count: int) -> list[tuple[str, str, int]]:
    """(name, email, author_time) per line."""
    out = pr.git("blame", "--line-porcelain", "-L", f"{start},+{count}", pr.base_ref, "--", path)
    rows, name, email = [], "", ""
    for line in out.splitlines():
        if line.startswith("author "):
            name = line[7:]
        elif line.startswith("author-mail "):
            email = line[12:].strip("<>")
        elif line.startswith("author-time "):
            rows.append((name, email, int(line[12:])))
    return rows


def codeowners(pr: PullRequest, paths: list[str]) -> list[Owner]:
    """Fallback: last matching CODEOWNERS pattern wins; only email owners can be messaged."""
    text = next((t for p in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
                 if (t := pr.file_at(pr.base_ref, p))), "")
    rules = [l.split() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    emails: list[str] = []
    for path in paths:
        hit = [r[1:] for r in rules if fnmatch.fnmatch(path, r[0].lstrip("/").rstrip("/") + ("*" if r[0].endswith("/") else ""))
               or fnmatch.fnmatch(path, r[0].lstrip("/"))]
        for e in (hit[-1] if hit else []):
            if "@" in e and not e.startswith("@") and e not in emails:
                emails.append(e)
    return [Owner(name=e.split("@")[0], email=e, lines=0, last_touched="") for e in emails]


def resolve_owners(pr: PullRequest) -> list[Owner]:
    """Owners sorted by score, highest first. owners[0] gets the iMessage."""
    rows = [r for path, rs in base_line_ranges(pr.diff()).items() for s, c in rs for r in _blame(pr, path, s, c)]
    if not rows:
        return codeowners(pr, pr.changed_files())

    newest = max(t for _, _, t in rows)
    acc: dict[str, dict] = {}
    for name, email, t in rows:
        o = acc.setdefault(email, {"name": name, "lines": 0, "score": 0.0, "t": 0})
        o["lines"] += 1
        o["score"] += 0.5 ** ((newest - t) / 86400 / HALF_LIFE_DAYS)
        o["t"] = max(o["t"], t)
    total = sum(o["score"] for o in acc.values())
    owners = [
        Owner(name=o["name"], email=email, lines=o["lines"],
              last_touched=datetime.fromtimestamp(o["t"], timezone.utc).date().isoformat(),
              score=round(o["score"] / total, 3))
        for email, o in acc.items()
    ]
    return sorted(owners, key=lambda o: (-o.score, o.email))
