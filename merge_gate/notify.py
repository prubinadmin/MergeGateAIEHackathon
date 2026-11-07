"""Owner notification over iMessage (owner: TAAZ).

Contract:
  1. format_message(report)          -> the text sent to owners[0]
  2. Notifier.send(phone, text)      -> provider message id   (TAAZ: the iMessage provider)
  3. parse_reply(text)               -> Reply                  (the owner texts back; a rule = TEACH)
  4. handle_reply(report, reply)     -> Action                 (what the gate does next)

Design rule: easy to stop, hard to approve. A text can BLOCK a PR. A text can never approve or merge one:
OK only answers with the GitHub link, where approval needs the owner's own login.
A text that reads like a rule (must, never, always...) or starts with RULE: teaches the gate (owner_tests.py);
any block/stop/hold/reject/revert or "don't merge" wording is BLOCK first. FORGET <test> removes a rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from .owners import eligible
from .schema import Owner, VerdictReport, owner_key

Command = Literal["BLOCK", "WHY", "OK", "FALSE_ALARM", "TEACH", "FORGET", "UNKNOWN"]
ActionKind = Literal["block_pr", "send_text", "log_false_alarm", "teach", "forget", "none"]


@dataclass
class Reply:
    command: Command
    raw: str
    note: str = ""  # anything the owner wrote after the command word


@dataclass
class Action:
    kind: ActionKind
    text: str = ""  # message to send back to the owner, if any


class Notifier(Protocol):
    def send(self, phone: str, text: str) -> str: ...


class ConsoleNotifier:
    """Prints instead of sending. Lets the whole pipeline run before iMessage works."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> str:
        self.sent.append((phone, text))
        print(f"--- to {phone} ---\n{text}\n")
        return f"console-{len(self.sent)}"


_ALIASES: dict[str, Command] = {
    "BLOCK": "BLOCK",
    "STOP": "BLOCK",
    "WHY": "WHY",
    "OK": "OK",
    "APPROVE": "OK",
    "FALSE": "FALSE_ALARM",
    "FALSE_ALARM": "FALSE_ALARM",
    "FP": "FALSE_ALARM",
    "FORGET": "FORGET",
}

# Easy to stop: any of these anywhere in a non-command text (or after OK) means BLOCK, never a rule.
_BLOCK_INTENT = re.compile(r"\b(block|stop|hold|reject|revert)\b|\b(don'?t|dont|do\s+not)\s+merge\b", re.I)
# Only text that reads like a rule is taught; "looks good thanks" is not.
_RULE_WORDS = re.compile(r"\b(must|never|always|should|only|cannot|can'?t|at\s+least|at\s+most)\b|>=|<=", re.I)


def parse_reply(text: str) -> Reply:
    norm = text.replace("’", "'")  # iMessage sends curly apostrophes
    words = norm.strip().split()
    if not words:
        return Reply("UNKNOWN", text)
    first = words[0].upper().strip(".!,?:")
    if words[0].upper().startswith("RULE:") or first == "RULE":
        return _explicit_rule(text, norm)
    if first == "FALSE" and len(words) > 1 and words[1].upper().strip(".!,?") == "ALARM":
        return Reply("FALSE_ALARM", text, " ".join(words[2:]))
    cmd = _ALIASES.get(first)
    if cmd and cmd != "OK":
        return Reply(cmd, text, " ".join(words[1:]))
    return _free_text(text, norm, words, cmd == "OK")


def _explicit_rule(text: str, norm: str) -> Reply:
    """RULE: <sentence> always teaches (an empty one is UNKNOWN)."""
    note = norm.strip()[4:].lstrip(": ").strip()
    return Reply("TEACH", text, note) if note else Reply("UNKNOWN", text)


def _free_text(text: str, norm: str, words: list[str], is_ok: bool) -> Reply:
    """OK or no command word: stop wording wins (BLOCK), then OK, then rule-shaped text (TEACH)."""
    if _BLOCK_INTENT.search(norm):
        return Reply("BLOCK", text, norm.strip())
    if is_ok:
        return Reply("OK", text, " ".join(words[1:]))
    if _RULE_WORDS.search(norm):
        return Reply("TEACH", text, norm.strip())
    return Reply("UNKNOWN", text)


def blame_order(owners: list[Owner]) -> list[Owner]:
    """resolve_owners' ranking, recovered from scores whatever order routing left the list in."""
    return sorted(owners, key=lambda o: (-o.score, -o.lines, o.email))


def authorized_owners(report: VerdictReport) -> list[Owner]:
    """Who may act on this PR. The blame-top owner always; SubQ's routed owners[0] only if eligible,
    so a prompt-injected route can never hand authority to a 1-line author or the PR's own opener."""
    if not report.owners:
        return []
    by_blame = blame_order(report.owners)
    top = next((o for o in report.owners if owner_key(o) == report.blame_owner), by_blame[0])  # old reports: top share
    routed = report.owners[0]
    return [top] + ([routed] if routed is not top and eligible(routed, report.opened_by) else [])


def format_message(report: VerdictReport, pr_url: str = "") -> str:
    if report.urgency == "fyi" and report.verdict == "PASS":
        return f"FYI: {report.pr_id} touched your code; gate says {report.verdict}, no action needed." + (f" {pr_url}" if pr_url else "")
    owner = report.owners[0].name if report.owners else "there"
    head = {
        "BLOCK": "Merge Gate BLOCKED a PR on your code",
        "REVIEW": "Merge Gate wants your eyes on a PR",
        "PASS": "FYI: a PR touched your code and passed",
    }[report.verdict]
    lines = [f"{head} ({report.pr_id}).", f"Hi {owner}: {report.summary}".rstrip(": ")]
    for e in report.evidence[:2]:
        lines.append(f"- {e.detail}")
    if report.verdict != "PASS":
        lines.append("Reply BLOCK, WHY, OK or FALSE ALARM, or text me a rule this code must follow.")
    if pr_url:
        lines.append(pr_url)
    return "\n".join(lines)


def handle_reply(report: VerdictReport, reply: Reply, pr_url: str = "") -> Action:
    if reply.command == "BLOCK":
        return Action("block_pr", f"Blocked {report.pr_id}.")
    if reply.command == "WHY":
        details = [f"{e.id}: {e.detail}" for e in report.evidence] or ["No evidence recorded."]
        return Action("send_text", "\n".join(details + [f"run {report.run_hash}"]))
    if reply.command == "OK":
        # Never merges from a text. Approval happens on GitHub.
        return Action("send_text", f"Approve on GitHub with your own login: {pr_url or report.pr_id}")
    if reply.command == "FALSE_ALARM":
        return Action("log_false_alarm", "Thanks, logged. The gate will learn from it if held-out PRs agree.")
    if reply.command == "TEACH":
        return Action("teach", "Got it — turning that into a test…")
    if reply.command == "FORGET":
        return Action("forget")  # serve.py removes the owner's rule and texts what it removed
    return Action("none", "Reply BLOCK, WHY, OK or FALSE ALARM.")
