"""Verdict contract shared by the verifier (Michael), iMessage (TAAZ) and benchmark (Peter).

Change this file only by team agreement: every other component reads it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Verdict = Literal["BLOCK", "REVIEW", "PASS"]
EvidenceType = Literal["failing_test", "rule"]
Severity = Literal["block", "review"]

VERDICTS: tuple[str, ...] = ("BLOCK", "REVIEW", "PASS")
EVIDENCE_TYPES: tuple[str, ...] = ("failing_test", "rule")
SEVERITIES: tuple[str, ...] = ("block", "review")


@dataclass
class Evidence:
    type: EvidenceType
    id: str  # rule id like "R1_DELETED_TEST", or a test node id
    detail: str  # one human-readable line
    file: str | None = None
    line: int | None = None
    severity: Severity = "block"  # "review" = worth a human look, not enough to block


@dataclass
class Owner:
    name: str
    email: str
    lines: int  # changed lines this person last authored
    last_touched: str  # ISO date, YYYY-MM-DD
    score: float = 0.0  # routing weight; owners[0] is the one we message


@dataclass
class VerdictReport:
    pr_id: str
    verdict: Verdict
    evidence: list[Evidence] = field(default_factory=list)
    owners: list[Owner] = field(default_factory=list)
    summary: str = ""
    run_hash: str = ""
    gate_version: str = "v1"
    # routing (SubQ Snap); optional so older reports still load
    routed_by: str = "blame"  # "subq" when SubQ picked owners[0]
    route_confidence: float | None = None  # SubQ's confidence in owners[0]
    urgency: str = ""  # "page" | "fyi"; "" when not assessed
    urgency_p: float | None = None  # SubQ's probability of paging; None = plain-code fallback
    blame_owner: str = ""  # owner_key() of the blame-top owner; always authorized, whoever SubQ routed to
    opened_by: str = ""  # the PR's author; never authorized as a routed owner

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerdictReport":
        validate(d)
        return cls(
            pr_id=d["pr_id"],
            verdict=d["verdict"],
            evidence=[Evidence(**e) for e in d.get("evidence", [])],
            owners=[Owner(**o) for o in d.get("owners", [])],
            summary=d.get("summary", ""),
            run_hash=d.get("run_hash", ""),
            gate_version=d.get("gate_version", "v1"),
            routed_by=d.get("routed_by", "blame"),
            route_confidence=d.get("route_confidence"),
            urgency=d.get("urgency", ""),
            urgency_p=d.get("urgency_p"),
            blame_owner=d.get("blame_owner", ""),
            opened_by=d.get("opened_by", ""),
        )


def owner_key(o: Owner) -> str:
    return o.email.lower() or o.name


def validate(d: dict[str, Any]) -> None:
    """Raise ValueError if d does not match the contract."""
    for key in ("pr_id", "verdict"):
        if key not in d:
            raise ValueError(f"missing field: {key}")
    if d["verdict"] not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {d['verdict']!r}")
    for e in d.get("evidence", []):
        if e.get("type") not in EVIDENCE_TYPES:
            raise ValueError(f"evidence type must be one of {EVIDENCE_TYPES}")
        if not e.get("id"):
            raise ValueError("evidence needs an id")
        if e.get("severity", "block") not in SEVERITIES:
            raise ValueError(f"evidence severity must be one of {SEVERITIES}")
    if d["verdict"] == "BLOCK" and not d.get("evidence"):
        raise ValueError("a BLOCK verdict must carry at least one piece of evidence")


def run_hash(payload: Any) -> str:
    """sha256 over canonical JSON, so any run can be compared and replayed."""
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()
