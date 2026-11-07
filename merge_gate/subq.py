"""SubQ Snap 1.1: who to page and how urgently. It routes; it never decides a verdict.

Two decisions over the changed lines' full history (git log -L), the diff and the blame candidates:
  choose_owner -> a choice question over the candidates
  urgency      -> a score question, FYI (0) vs page now (1)
Any failure or a missing key falls back to the blame ranking (logged); the gate never fails because SubQ is down.

Docs: https://docs.subq.ai/markdown/endpoints/decisions-api.md
- POST https://api.subq.ai/v1/systemone, header "Authorization: Bearer <SUBQ_API_KEY>"
- body {"model", "state", "questions": {name: {"type": "choice"|"score"|"noul", "instructions", "criteria"}}}
- choice answer {"choice", "probabilities", "confidence"}; score answer {"score", "legend", "probabilities", "confidence"}
- 384K-token window; retry 429 and 5xx with backoff, fix 400/422 instead of retrying
"""

from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import time
import urllib.error
import urllib.request

from .llm import load_dotenv
from .pr import PullRequest
from .schema import Evidence, Owner

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.subq.ai/v1"
DEFAULT_MODEL = "subq-snap-1.1"
HISTORY_CHARS = 200_000
DIFF_CHARS = 50_000
MAX_CANDIDATES = 10


class SubQError(RuntimeError):
    pass


def has_key() -> bool:
    load_dotenv()
    return bool(os.environ.get("SUBQ_API_KEY"))


def decide(state, questions: dict, *, timeout_s: int = 30, retries: int = 2) -> dict:
    """One Decisions API call; returns the "answers" object."""
    load_dotenv()
    key = os.environ.get("SUBQ_API_KEY", "")
    if not key:
        raise SubQError("SUBQ_API_KEY is not set")
    base = (os.environ.get("SUBQ_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    body = {"model": os.environ.get("SUBQ_MODEL") or DEFAULT_MODEL, "state": state, "questions": questions}
    data = json.dumps(body).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{base}/systemone",
            data=data,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "merge-gate/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))["answers"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code != 429 and e.code < 500:
                raise SubQError(f"HTTP {e.code}: {detail}") from None
            last_err = SubQError(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
        if attempt < retries:
            time.sleep(min(10, 2**attempt) + random.random())
    raise SubQError(f"SubQ call failed after {retries + 1} attempts: {last_err}")


def _history(pr: PullRequest) -> str:
    """git log -p of every base-side line range the PR touches, newest first, bounded."""
    from .owners import _base_ranges

    parts: list[str] = []
    size = 0
    for path in pr.changed_files():
        if pr.file_at(pr.base_ref, path) is None:
            continue
        for a, b in _base_ranges(pr, path):
            try:
                out = pr.git("log", "--format=commit %h  %an <%ae>  %ad  %s", "--date=short", "-L", f"{a},{b}:{path}", pr.base_ref)
            except subprocess.CalledProcessError:
                continue
            chunk = f"=== {path} lines {a}-{b} ===\n{out}"
            parts.append(chunk[: HISTORY_CHARS - size])
            size += len(parts[-1])
            if size >= HISTORY_CHARS:
                return "\n".join(parts)
    return "\n".join(parts)


def _state(pr: PullRequest, **extra) -> dict:
    return {
        "pr": {"title": pr.title, "opened_by": pr.opened_by, "issue": pr.issue_text, "files": pr.changed_files()},
        "diff": pr.diff()[:DIFF_CHARS],
        "history_of_changed_lines": _history(pr),
        **extra,
    }


def choose_owner(pr: PullRequest, candidates: list[Owner]) -> tuple[Owner, float | None]:
    """Who to page. Returns (owner, SubQ confidence), or (candidates[0], None) on any failure."""
    if not candidates:
        raise ValueError("choose_owner needs at least one candidate")
    pool = candidates[:MAX_CANDIDATES]
    if len(pool) < 2:
        return pool[0], None
    try:
        opts = {
            f"c{i}": f"{o.name} <{o.email}>: last authored {o.lines} of the changed lines, last touched {o.last_touched or 'unknown'}, blame weight {o.score}"
            for i, o in enumerate(pool)
        }
        ans = decide(
            _state(pr, candidates=opts),
            {"owner": {
                "type": "choice",
                "instructions": "Which candidate should be paged about this pull request? Pick the person who best understands "
                                "the behaviour these changed lines implement and its intent, using the history of those lines.",
                "criteria": opts,
            }},
        )["owner"]
        return pool[int(ans["choice"][1:])], float(ans["confidence"])
    except Exception as e:  # any failure -> blame ranking; the gate must not depend on SubQ
        log.warning("SubQ choose_owner fell back to blame ranking: %s", e)
        return candidates[0], None


def urgency(pr: PullRequest, report_evidence: list[Evidence]) -> tuple[str, float | None]:
    """Page now or FYI. Returns (label, probability of paging), or a plain-code fallback with None."""
    fallback = "page" if any(e.severity == "block" for e in report_evidence) else "fyi"
    try:
        findings = [{"severity": e.severity, "id": e.id, "detail": e.detail, "file": e.file} for e in report_evidence]
        ans = decide(
            _state(pr, gate_findings=findings),
            {"urgency": {
                "type": "score",
                "instructions": "How urgently should the code owner hear about this pull request, given the gate's findings "
                                "and what the changed lines have protected historically?",
                "criteria": [
                    "FYI: nothing breaks if the owner reads it later",
                    "Page now: the owner should look before this merges",
                ],
            }},
        )["urgency"]
        p = float(ans["probabilities"]["1"])
        return ("page" if p >= 0.5 else "fyi"), p
    except Exception as e:
        log.warning("SubQ urgency fell back to plain code: %s", e)
        return fallback, None
