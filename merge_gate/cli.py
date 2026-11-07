"""merge-gate CLI.

    python -m merge_gate verify --pr demo-1 --stub     # fixed BLOCK report, for wiring iMessage / benchmark
    python -m merge_gate validate report.json          # check a report against the contract
"""

from __future__ import annotations

import argparse
import json
import sys

from .schema import Evidence, Owner, VerdictReport, run_hash, validate


def stub_report(pr_id: str) -> VerdictReport:
    report = VerdictReport(
        pr_id=pr_id,
        verdict="BLOCK",
        evidence=[
            Evidence(
                type="rule",
                id="R1_DELETED_TEST",
                detail="PR deletes test_discount_never_negative from tests/test_pricing.py",
                file="tests/test_pricing.py",
                line=41,
            ),
            Evidence(
                type="failing_test",
                id="gate::test_discount_capped_at_price",
                detail="apply_discount(price=10, pct=150) returned -5.0, expected 0.0",
                file="shop/pricing.py",
                line=27,
            ),
        ],
        owners=[
            Owner(name="Peter", email="peter@example.com", lines=18, last_touched="2026-03-14", score=0.82),
            Owner(name="TAAZ", email="taaz@example.com", lines=4, last_touched="2026-06-02", score=0.18),
        ],
        summary=(
            "An agent's PR changes apply_discount(), which you wrote. It deletes the test that kept "
            "discounts from going negative, and a 150% discount now returns -5.0."
        ),
        gate_version="stub",
    )
    report.run_hash = run_hash({"pr_id": pr_id, "stub": True})
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="merge-gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify a PR and print a verdict report as JSON")
    v.add_argument("--pr", required=True, help="PR id")
    v.add_argument("--stub", action="store_true", help="return a fixed BLOCK report")

    c = sub.add_parser("validate", help="validate a report JSON file against the contract")
    c.add_argument("path")

    args = p.parse_args(argv)

    if args.cmd == "verify":
        if not args.stub:
            print("real verifier not built yet; use --stub", file=sys.stderr)
            return 2
        print(stub_report(args.pr).to_json())
        return 0

    if args.cmd == "validate":
        with open(args.path, encoding="utf-8") as f:
            data = json.load(f)
        try:
            validate(data)
        except ValueError as e:
            print(f"INVALID: {e}", file=sys.stderr)
            return 1
        print("OK")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
