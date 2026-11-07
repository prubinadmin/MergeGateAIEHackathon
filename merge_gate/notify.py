"""Owner notification over iMessage (owner: TAAZ).

Contract:
  1. format_message(report)          -> the text sent to owners[0]
  2. Notifier.send(phone, text)      -> provider message id   (TAAZ: the iMessage provider)
  3. parse_reply(text)               -> Reply                  (the owner texts back; free text = TEACH)
  4. handle_reply(report, reply)     -> Action                 (what the gate does next)

Design rule: easy to stop, hard to approve. A text can BLOCK a PR. A text can never approve or merge one:
OK only answers with the GitHub link, where approval needs the owner's own login.
A sentence that is not a command is a rule the owner is TEACHING the gate (see owner_tests.rule_to_test).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .schema import VerdictReport

Command = Literal["BLOCK", "WHY", "OK", "FALSE_ALARM", "TEACH", "UNKNOWN"]
ActionKind = Literal["block_pr", "send_text", "log_false_alarm", "teach", "none"]


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
}


def parse_reply(text: str) -> Reply:
    words = text.strip().split()
    if not words:
        return Reply("UNKNOWN", text)
    first = words[0].upper().strip(".!,?")
    if first == "FALSE" and len(words) > 1 and words[1].upper().strip(".!,?") == "ALARM":
        return Reply("FALSE_ALARM", text, " ".join(words[2:]))
    cmd = _ALIASES.get(first)
    if cmd is None:  # not a command: a sentence is a rule the owner is teaching; "lol" or "thanks" is not
        return Reply("TEACH", text, text.strip()) if len(words) >= 3 else Reply("UNKNOWN", text)
    return Reply(cmd, text, " ".join(words[1:]))


def format_message(report: VerdictReport, pr_url: str = "") -> str:
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
    return Action("none", "Reply BLOCK, WHY, OK or FALSE ALARM.")
