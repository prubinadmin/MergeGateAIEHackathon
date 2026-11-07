"""GitHub enforcement (owner: Michael).

Merge Gate posts a commit status named `merge-gate` on the PR's head commit. Make it a required
status check in branch protection, and a BLOCK makes the merge button unusable.

  BLOCK  -> status "failure"
  REVIEW -> status "pending"  (waiting for the code owner)
  PASS   -> status "success"

An owner replying BLOCK by text calls block_pr(): the status turns "failure" at once.
Nothing in this module can turn a status to "success" because of a text message: success only
comes from a gate run that found nothing (easy to stop, hard to approve).

Needs GITHUB_TOKEN (Actions provides it; locally put a token with repo:status scope in .env.local).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .llm import load_dotenv
from .schema import VerdictReport

API = "https://api.github.com"
CONTEXT = "merge-gate"
STATE_FOR = {"BLOCK": "failure", "REVIEW": "pending", "PASS": "success"}


class GitHubError(RuntimeError):
    pass


def _token() -> str:
    load_dotenv()
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not tok:
        raise GitHubError("GITHUB_TOKEN is not set")
    return tok


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "merge-gate",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise GitHubError(f"{method} {path}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None


def head_sha(repo: str, pr_number: int) -> str:
    return _call("GET", f"/repos/{repo}/pulls/{pr_number}")["head"]["sha"]


def set_status(repo: str, sha: str, state: str, description: str, target_url: str = "") -> dict:
    if state not in ("failure", "pending", "success", "error"):
        raise ValueError(state)
    body = {"state": state, "context": CONTEXT, "description": description[:140]}
    if target_url:
        body["target_url"] = target_url
    return _call("POST", f"/repos/{repo}/statuses/{sha}", body)


def comment(repo: str, pr_number: int, text: str) -> dict:
    return _call("POST", f"/repos/{repo}/issues/{pr_number}/comments", {"body": text})


def default_branch(repo: str) -> str:
    return _call("GET", f"/repos/{repo}")["default_branch"]


def open_pr(repo: str, head: str, base: str, title: str, body: str) -> dict:
    return _call("POST", f"/repos/{repo}/pulls", {"title": title, "head": head, "base": base, "body": body})


def status_line(report: VerdictReport) -> str:
    owner = report.owners[0].name if report.owners else "code owner"
    if report.verdict == "PASS":
        return f"Passed. FYI sent to {owner}."
    top = report.evidence[0].id if report.evidence else ""
    return f"{report.verdict}: {top}. Sent to {owner}."[:140]


def comment_body(report: VerdictReport) -> str:
    icon = {"BLOCK": "BLOCKED", "REVIEW": "NEEDS OWNER REVIEW", "PASS": "PASSED"}[report.verdict]
    lines = [f"### Merge Gate: {icon}", "", report.summary, ""]
    if report.owners:
        o = report.owners[0]
        lines.append(f"**Routed to {o.name}**, who wrote {o.lines} of the changed lines (last touched {o.last_touched}).")
        lines.append("")
    if report.evidence:
        lines += ["| Severity | Check | Evidence |", "| --- | --- | --- |"]
        for e in report.evidence:
            where = f" (`{e.file}:{e.line}`)" if e.file and e.line else (f" (`{e.file}`)" if e.file else "")
            lines.append(f"| {e.severity} | `{e.id}` | {e.detail.replace('|', '/')}{where} |")
        lines.append("")
    lines.append(f"<sub>gate {report.gate_version} · run `{report.run_hash}` · a text reply can block this PR, never approve it</sub>")
    return "\n".join(lines)


def publish(report: VerdictReport, repo: str, pr_number: int, sha: str | None = None) -> None:
    sha = sha or head_sha(repo, pr_number)
    set_status(repo, sha, STATE_FOR[report.verdict], status_line(report))
    comment(repo, pr_number, comment_body(report))


def block_pr(repo: str, pr_number: int, owner: str, reason: str = "") -> None:
    """Owner said BLOCK by text: fail the required check now."""
    sha = head_sha(repo, pr_number)
    set_status(repo, sha, "failure", f"Blocked by {owner} from their phone" + (f": {reason}" if reason else ""))
    comment(repo, pr_number, f"### Merge Gate: BLOCKED by {owner}\n\n{owner} replied BLOCK from their phone." + (f"\n\n> {reason}" if reason else ""))
