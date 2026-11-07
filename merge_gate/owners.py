"""Ownership resolver (owner: Michael): who wrote the lines this PR changes.

For every hunk, git blame the base-side lines the PR modifies or deletes. A pure insertion is
charged to the function it lands in (or a few lines around it). Each author's share is weighted
by recency, so the person who wrote the code last year outranks the person who reformatted it in 2019.
Source files count more than test files. CODEOWNERS is only the fallback.
"""

from __future__ import annotations

import ast
import datetime as dt
import fnmatch
import math
import re
import subprocess
from dataclasses import dataclass

from .pr import PullRequest
from .rules import is_test_path
from .schema import Owner

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HALF_LIFE_DAYS = 365.0
TEST_WEIGHT = 0.3
INSERT_WINDOW = 3
MIN_SHARE = 0.25  # blame share below this never receives the page or authority over the PR


def is_opener(o: Owner, opened_by: str) -> bool:
    """opened_by (a login) matches the owner's name or email local-part, case-insensitively."""
    who = (opened_by or "").strip().lower()
    if not who:
        return False
    local = (o.email or "").lower().split("@")[0]
    return who in {(o.name or "").lower(), local, local.split("+")[-1]}  # 123+login@users.noreply.github.com


def eligible(o: Owner, opened_by: str) -> bool:
    """May this owner be routed to (and so authorized): a real blame share, and not the PR's own author."""
    return o.score >= MIN_SHARE and not is_opener(o, opened_by)


@dataclass
class _Acc:
    name: str
    email: str
    lines: int = 0
    weight: float = 0.0
    last: int = 0  # unix time


def _base_ranges(pr: PullRequest, path: str) -> list[tuple[int, int]]:
    """1-based inclusive line ranges at base that the PR touches."""
    diff = pr.git("diff", "-U0", f"{pr.base_ref}...{pr.head_ref}", "--", path)
    base_src = pr.file_at(pr.base_ref, path) or ""
    n_lines = base_src.count("\n") + (0 if base_src.endswith("\n") else 1)
    ranges: list[tuple[int, int]] = []
    for line in diff.splitlines():
        m = HUNK.match(line)
        if not m:
            continue
        start, count = int(m.group(1)), int(m.group(2) or "1")
        if count > 0:
            ranges.append((start, start + count - 1))
        else:  # insertion after line `start`
            ranges.append(_enclosing(base_src, max(start, 1)) or (max(1, start - INSERT_WINDOW + 1), start + INSERT_WINDOW))
    return [(max(1, a), min(b, n_lines)) for a, b in ranges if n_lines and a <= n_lines]


def _enclosing(src: str, line: int) -> tuple[int, int] | None:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= line <= (node.end_lineno or node.lineno):
            if best is None or node.lineno > best[0]:
                best = (node.lineno, node.end_lineno or node.lineno)
    return best


def _blame(pr: PullRequest, path: str, a: int, b: int) -> list[tuple[str, str, int]]:
    """(author, email, author-time) per line."""
    out = pr.git("blame", "--line-porcelain", "-w", "-L", f"{a},{b}", pr.base_ref, "--", path)
    rows: list[tuple[str, str, int]] = []
    name = email = ""
    t = 0
    for line in out.splitlines():
        if line.startswith("author "):
            name = line[len("author "):]
        elif line.startswith("author-mail "):
            email = line[len("author-mail "):].strip("<>")
        elif line.startswith("author-time "):
            t = int(line.split()[1])
        elif line.startswith("\t"):
            rows.append((name, email, t))
    return rows


def _codeowners(pr: PullRequest, paths: list[str]) -> list[Owner]:
    for loc in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        text = pr.file_at(pr.base_ref, loc)
        if text:
            break
    else:
        return []
    found: dict[str, Owner] = {}
    rules = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            pattern, *who = line.split()
            rules.append((pattern, who))
    for path in paths:
        owners: list[str] = []
        for pattern, who in rules:  # last match wins, like GitHub
            pat = pattern.lstrip("/")
            if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat.rstrip("/") + "/*") or path.startswith(pat.rstrip("*")):
                owners = who
        for w in owners:
            email = w if "@" in w and not w.startswith("@") else ""
            found.setdefault(w, Owner(name=w.lstrip("@"), email=email, lines=0, last_touched="", score=0.0))
    out = list(found.values())
    for o in out:
        o.score = round(1 / len(out), 3)
    return out


def resolve_owners(pr: PullRequest, now: float | None = None) -> list[Owner]:
    """Owners sorted by score, highest first. owners[0] gets the iMessage."""
    now = now or dt.datetime.now(dt.timezone.utc).timestamp()
    acc: dict[str, _Acc] = {}
    changed = pr.changed_files()
    for path in changed:
        if pr.file_at(pr.base_ref, path) is None:
            continue  # new file: nobody owns it yet
        weight = TEST_WEIGHT if is_test_path(path) else 1.0
        for a, b in _base_ranges(pr, path):
            try:
                rows = _blame(pr, path, a, b)
            except subprocess.CalledProcessError:
                continue
            for name, email, t in rows:
                key = email.lower() or name
                o = acc.setdefault(key, _Acc(name, email))
                age_days = max(0.0, (now - t) / 86400)
                o.lines += 1
                o.weight += weight * math.pow(0.5, age_days / HALF_LIFE_DAYS)
                o.last = max(o.last, t)
    if not acc:
        return _codeowners(pr, changed)
    total = sum(o.weight for o in acc.values()) or 1.0
    owners = [
        Owner(
            name=o.name,
            email=o.email,
            lines=o.lines,
            last_touched=dt.datetime.fromtimestamp(o.last, dt.timezone.utc).date().isoformat(),
            score=round(o.weight / total, 3),
        )
        for o in acc.values()
    ]
    owners.sort(key=lambda o: (-o.score, -o.lines, o.email))
    return owners
