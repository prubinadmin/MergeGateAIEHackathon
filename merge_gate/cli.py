"""merge-gate CLI.

    python -m merge_gate verify --pr demo-1 --stub          # fixed BLOCK report, for wiring iMessage / benchmark
    python -m merge_gate verify --case benchmark/cases/pr01 # run the gate on one benchmark case
    python -m merge_gate validate report.json               # check a report against the contract
    python -m merge_gate notify report.json --reply "WHY"   # dry-run the owner message and a reply
    python -m merge_gate bench --split heldout [--stub]     # score the gate on the benchmark
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


def _load_report(path: str) -> VerdictReport:
    with open(path, encoding="utf-8") as f:
        return VerdictReport.from_dict(json.load(f))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="merge-gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify a PR and print a verdict report as JSON")
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", help="PR id (with --stub)")
    g.add_argument("--case", help="benchmark case directory")
    v.add_argument("--stub", action="store_true", help="return a fixed BLOCK report")

    c = sub.add_parser("validate", help="validate a report JSON file against the contract")
    c.add_argument("path")

    n = sub.add_parser("notify", help="dry-run: print the owner message, optionally handle a reply")
    n.add_argument("report")
    n.add_argument("--reply", default=None, help="simulate the owner's text reply")
    n.add_argument("--pr-url", default="")

    b = sub.add_parser("bench", help="run the gate on benchmark cases and print metrics")
    b.add_argument("--root", default="benchmark")
    b.add_argument("--split", choices=["train", "heldout"], default=None)
    b.add_argument("--stub", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "verify":
        if args.stub:
            print(stub_report(args.pr or args.case).to_json())
            return 0
        if not args.case:
            print("without --stub, pass --case", file=sys.stderr)
            return 2
        from .bench import load_case
        from .verify import verify

        print(verify(load_case(args.case)).to_json())
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

    if args.cmd == "notify":
        from .notify import ConsoleNotifier, format_message, handle_reply, parse_reply

        report = _load_report(args.report)
        notifier = ConsoleNotifier()
        notifier.send("<owner phone>", format_message(report, args.pr_url))
        if args.reply is not None:
            action = handle_reply(report, parse_reply(args.reply), args.pr_url)
            print(f"action: {action.kind}")
            if action.text:
                notifier.send("<owner phone>", action.text)
        return 0

    if args.cmd == "bench":
        from .bench import load_cases, score
        from .verify import verify

        cases = load_cases(args.root, args.split)
        if not cases:
            print(f"no cases under {args.root}/cases", file=sys.stderr)
            return 1
        reports = {
            c.pr.pr_id: (stub_report(c.pr.pr_id) if args.stub else verify(c.pr)) for c in cases
        }
        print(json.dumps(score(cases, reports), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
