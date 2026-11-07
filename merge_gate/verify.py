"""The gate: run every check, then decide in plain code (owner: Michael)."""

from __future__ import annotations

from .pr import PullRequest
from .rules import check_rules
from .schema import Evidence, Owner, Verdict, VerdictReport, run_hash

GATE_VERSION = "v1"


def decide(evidence: list[Evidence]) -> Verdict:
    """Deterministic verdict. No LLM.

    Any block-severity evidence -> BLOCK; else any review-severity -> REVIEW; else PASS.
    """
    if any(e.severity == "block" for e in evidence):
        return "BLOCK"
    if evidence:
        return "REVIEW"
    return "PASS"


def verify(pr: PullRequest) -> VerdictReport:
    evidence: list[Evidence] = []
    evidence.extend(check_rules(pr))

    # Independent tests and the sandbox join here once built:
    #   tests = testgen.generate_tests(pr)
    #   result = sandbox.run_tests(pr.repo_path, pr.head_ref, tests)
    #   evidence.extend(failing_test evidence from result.failed)

    owners: list[Owner] = []
    try:
        from .owners import resolve_owners

        owners = resolve_owners(pr)
    except NotImplementedError:
        pass

    verdict = decide(evidence)
    report = VerdictReport(
        pr_id=pr.pr_id,
        verdict=verdict,
        evidence=evidence,
        owners=owners,
        gate_version=GATE_VERSION,
    )
    report.run_hash = run_hash(
        {
            "pr": [pr.pr_id, pr.base_ref, pr.head_ref, pr.issue_text],
            "verdict": verdict,
            "evidence": [e.__dict__ for e in evidence],
            "gate": GATE_VERSION,
        }
    )
    return report
