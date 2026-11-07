"""`python -m merge_gate ci`: run the real gate inside GitHub Actions (owner: Michael).

Reads the PR from GITHUB_EVENT_PATH, verifies origin/<base>...<head sha> in the checked-out repo,
writes gate_result.json, posts the `merge-gate` status + a PR comment, and exits 1 on BLOCK.

Owner override: a BLOCK or REVIEW turns green only when a code owner approves the PR on GitHub with
their own login (pull_request_review event). OWNER_GITHUB maps owner email -> GitHub login, e.g.
OWNER_GITHUB={"peter@example.com": "peter-gh"}. A text message can never do this.
"""

from __future__ import annotations

import json
import os
import sys

from .pr import PullRequest
from .schema import VerdictReport


def _event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.exists(path):
        raise SystemExit("GITHUB_EVENT_PATH not set: run this inside GitHub Actions, or use `verify`")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pr_from_event(event: dict, repo_path: str = ".") -> tuple[PullRequest, int]:
    pr = event["pull_request"]
    return (
        PullRequest(
            pr_id=f"PR-{pr['number']}",
            repo_path=repo_path,
            base_ref=f"origin/{pr['base']['ref']}",
            head_ref=pr["head"]["sha"],
            issue_text=pr.get("body") or "",
            title=pr.get("title") or "",
            opened_by=(pr.get("user") or {}).get("login", ""),
        ),
        int(pr["number"]),
    )


def owner_approved(event: dict, report: VerdictReport) -> str:
    """Login of a code owner who approved this PR in this review event, else ''."""
    review = event.get("review") or {}
    if (review.get("state") or "").lower() != "approved":
        return ""
    login = (review.get("user") or {}).get("login", "")
    try:
        mapping = json.loads(os.environ.get("OWNER_GITHUB") or "{}")
    except json.JSONDecodeError:
        mapping = {}
    owner_logins = {mapping.get(o.email) for o in report.owners[:2]} - {None}
    return login if login and login in owner_logins else ""


def main(use_llm: bool, out_path: str = "gate_result.json", publish: bool = True) -> int:
    from . import github
    from .store import log_report
    from .verify import verify

    event = _event()
    pr, number = pr_from_event(event)
    report = verify(pr, use_llm=use_llm)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report.to_json())
    log_report(report, source="ci")
    print(report.to_json())

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    approver = owner_approved(event, report)
    if publish and repo:
        try:
            if approver and report.verdict != "PASS":
                github.set_status(repo, pr.head_ref, "success", f"{report.verdict} overridden: approved on GitHub by owner {approver}")
                github.comment(repo, number, f"### Merge Gate: approved by code owner @{approver} on GitHub\n\nGate findings were {report.verdict}; the owner reviewed and approved with their own login.")
            else:
                github.publish(report, repo, number, sha=pr.head_ref)
        except github.GitHubError as e:
            # Fork PRs get a read-only token: the exit code below still fails the check.
            print(f"[merge-gate] could not post to GitHub: {e}", file=sys.stderr)

    if approver:
        return 0
    return 1 if report.verdict == "BLOCK" else 0
