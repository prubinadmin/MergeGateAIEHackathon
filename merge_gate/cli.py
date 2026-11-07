"""merge-gate CLI.

    python -m merge_gate verify --pr demo-1 --stub          # fixed BLOCK report, for wiring iMessage / benchmark
    python -m merge_gate verify --case benchmark/cases/pr01 # run the gate on one benchmark case
    python -m merge_gate validate report.json               # check a report against the contract
    python -m merge_gate notify report.json --reply "WHY"   # dry-run the owner message and a reply
    python -m merge_gate bench --split heldout [--stub]     # score the gate on the benchmark
    python -m merge_gate bench --baseline llm|codeowners    # score a baseline on the same cases
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


def _llm_flags(parser: argparse.ArgumentParser) -> None:
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--llm", dest="llm", action="store_true", default=None,
                   help="force Muse Spark tests and summary (default: on when MUSE_API_KEY is set)")
    g.add_argument("--no-llm", dest="llm", action="store_false", help="rules and ownership only, no API calls")
    parser.add_argument("--no-subq", dest="subq", action="store_false", default=True,
                        help="never call SubQ for routing (default: on when SUBQ_API_KEY is set, independent of Muse)")


def _use_llm(args: argparse.Namespace) -> bool:
    """Default: on when a Muse key is available (.env / .env.local / environment), else off."""
    from .llm import has_key

    on = has_key() if args.llm is None else args.llm
    print(f"[merge-gate] Muse Spark {'ON' if on else 'OFF (no MUSE_API_KEY; rules + ownership only)'}", file=sys.stderr)
    return on


def _use_subq(args: argparse.Namespace) -> bool:
    """SubQ routing runs iff SUBQ_API_KEY is present and --no-subq was not given; independent of Muse."""
    from .subq import has_key

    on = getattr(args, "subq", False) and has_key()
    print(f"[merge-gate] SubQ routing {'ON' if on else 'OFF'}", file=sys.stderr)
    return on


def _load_report(path: str) -> VerdictReport:
    with open(path, encoding="utf-8") as f:
        return VerdictReport.from_dict(json.load(f))


def _cmd_owner_tests(args: argparse.Namespace) -> int:
    from . import owner_tests

    if args.action == "list":
        for e in owner_tests.load_registry():
            print(f'{e.get("id") or e["file"]}  {e["owner"]}  "{e["sentence"]}"')
        return 0
    if not args.id:
        print("owner-tests remove needs an id (see owner-tests list)", file=sys.stderr)
        return 2
    gone = owner_tests.remove(args.id)
    for e in gone:
        print(f'removed {e.get("id") or e["file"]}  "{e["sentence"]}"')
    return 0 if gone else 1


def _bench_baseline(args: argparse.Namespace, cases: list) -> int:
    """bench --baseline: score a baseline on the cases. The llm baseline needs Muse Spark; a case with no report fails the run."""
    from .baselines import METRICS, run as run_baseline
    from .bench import score

    if args.baseline == "llm" and (args.stub or not _use_llm(args)):
        print("bench --baseline llm needs Muse Spark: it is off (--no-llm, --stub or no MUSE_API_KEY)", file=sys.stderr)
        return 1
    reports = run_baseline(args.baseline, cases)
    s = score(cases, reports)
    keep = ("cases", "bad", "clean", *METRICS[args.baseline], "missing_reports")
    print(json.dumps({"baseline": args.baseline, **{k: s[k] for k in keep}}, indent=2))
    if s["missing_reports"]:
        missing = sorted(c.pr.pr_id for c in cases if c.pr.pr_id not in reports)
        print(f"{s['missing_reports']} of {len(cases)} cases got no {args.baseline} report (call failed or unparseable): {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


def _cmd_github(args: argparse.Namespace) -> int:
    """Resolve a live GitHub PR, clone it and run the gate; progress on stderr, verdict JSON on stdout."""
    from .github_pr import scan

    def progress(name, status, data):
        extra = (f" {data['ms']}ms" if "ms" in data else "") + (f" {data['url']}" if "url" in data else "")
        print(f"[merge-gate] {name} {status}{extra}", file=sys.stderr)

    report, pr, resolved = scan(args.query, use_llm=_use_llm(args), use_subq=_use_subq(args), on_stage=progress)
    print(f"[merge-gate] {resolved.html_url} -> {pr.pr_id} (clone: {pr.repo_path})", file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report.to_json())
    print(report.to_json())
    return 0



def _cmd_log(args) -> int:
    """`merge-gate log` (moved out of main() so each subcommand stays small)."""
    from . import store

    ok, bad = store.verify_chain()
    for rec in store.read()[-args.tail:]:
        d = rec["data"]
        what = f"{d.get('pr_id')} {d.get('verdict') or d.get('command')}" + (f" -> {d['action']}" if "action" in d else "")
        print(f"{rec['at']} {rec['kind']:<8} {what}")
    print(f"hash chain: {'OK' if ok else f'BROKEN at record {bad}'}")
    return 0 if ok else 1


def _cmd_learn(args) -> int:
    """`merge-gate learn` (moved out of main() so each subcommand stays small)."""
    from .bench import load_cases
    from .learn import collect_raw, false_alarms_from_log, learn_round

    cases = load_cases(args.root)
    if not cases:
        print(f"no cases under {args.root}/cases", file=sys.stderr)
        return 1
    raw = collect_raw(cases, use_llm=_use_llm(args))
    result = learn_round(cases, raw, false_alarms_from_log())
    print(json.dumps({k: v for k, v in result.items() if k != "candidates"}, indent=2))
    for c in result["candidates"]:
        print(f"  {'KEEP' if c['adopted_so_far'] else 'roll back'}: {c['change']}  held-out {c['heldout']['catch_rate']:.2f} catch / {c['heldout']['false_block_rate']:.2f} false-block")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="merge-gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify a PR and print a verdict report as JSON")
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", help="PR id (with --stub)")
    g.add_argument("--case", help="benchmark case directory")
    v.add_argument("--stub", action="store_true", help="return a fixed BLOCK report")
    _llm_flags(v)

    gh = sub.add_parser("github", help="verify a live GitHub PR: owner/repo#N, owner/repo (newest open PR) or a repo name to search")
    gh.add_argument("query")
    gh.add_argument("--out", default=None, help="also write the report JSON here")
    _llm_flags(gh)

    d = sub.add_parser("demo", help="build the demo repo in a temp dir and run the gate on its PRs")
    _llm_flags(d)
    d.add_argument("--keep", default=None, help="build the demo repo here instead of a temp dir")

    c = sub.add_parser("validate", help="validate a report JSON file against the contract")
    c.add_argument("path")

    n = sub.add_parser("notify", help="dry-run: print the owner message, optionally handle a reply")
    n.add_argument("report")
    n.add_argument("--reply", default=None, help="simulate the owner's text reply")
    n.add_argument("--pr-url", default="")

    ci = sub.add_parser("ci", help="run inside GitHub Actions: verify the PR, post status + comment, exit 1 on BLOCK")
    _llm_flags(ci)
    ci.add_argument("--out", default="gate_result.json")
    ci.add_argument("--no-publish", action="store_true", help="do not call the GitHub API")
    ci.add_argument("--repo", default=".", help="path to the PR checkout; run the gate from a different, clean directory")

    rb = sub.add_parser("rollback", help="re-verify a merged commit; on BLOCK make a revert branch (and PR with --push)")
    rb.add_argument("sha")
    rb.add_argument("--repo", default=".", help="path to the repo; run the gate from a different, clean directory")
    rb.add_argument("--push", action="store_true", help="push the revert branch and open a PR (needs --github, GITHUB_TOKEN)")
    rb.add_argument("--github", default="", help="owner/repo on GitHub")
    rb.add_argument("--base", default=None, help="verify <base>..<sha> as one diff (a push's `before`; all-zero -> <sha>^1)")
    rb.add_argument("--respect-override", action=argparse.BooleanOptionalAction, default=True,
                    help="skip a PR a code owner overrode (looked up on GitHub; default on)")
    _llm_flags(rb)

    s = sub.add_parser("serve", help="HTTP API for the web UI and the iMessage webhook")
    _llm_flags(s)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)

    lg = sub.add_parser("log", help="show the run log and check its hash chain")
    lg.add_argument("--tail", type=int, default=10)

    ln = sub.add_parser("learn", help="one learning round: propose rule changes, keep them only if held-out PRs improve")
    _llm_flags(ln)
    ln.add_argument("--root", default="benchmark")

    b = sub.add_parser("bench", help="run the gate on benchmark cases and print metrics")
    b.add_argument("--root", default="benchmark")
    b.add_argument("--split", choices=["train", "heldout"], default=None)
    b.add_argument("--stub", action="store_true")
    b.add_argument("--baseline", choices=["llm", "codeowners"], default=None,
                   help="score a baseline instead of the gate (llm: Muse Spark reads the diff; codeowners: folder routing)")
    _llm_flags(b)

    ot = sub.add_parser("owner-tests", help="list or remove the rules owners taught the gate by iMessage")
    ot.add_argument("action", choices=["list", "remove"])
    ot.add_argument("id", nargs="?", help="rule id, file or test name (for remove)")

    args = p.parse_args(argv)

    if args.cmd == "owner-tests":
        return _cmd_owner_tests(args)

    if args.cmd == "verify":
        if args.stub:
            print(stub_report(args.pr or args.case).to_json())
            return 0
        if not args.case:
            print("without --stub, pass --case", file=sys.stderr)
            return 2
        from .bench import load_case
        from .verify import verify

        print(verify(load_case(args.case).pr, use_llm=_use_llm(args), use_subq=_use_subq(args)).to_json())
        return 0

    if args.cmd == "github":
        return _cmd_github(args)

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

    if args.cmd == "ci":
        from .ci import main as ci_main

        return ci_main(_use_llm(args), args.out, publish=not args.no_publish, use_subq=_use_subq(args),
                       repo_path=args.repo)

    if args.cmd == "rollback":
        import logging

        from .rollback import main as rollback_main

        logging.basicConfig(format="[merge-gate] %(levelname)s: %(message)s")  # rollback's warnings -> stderr
        code, out, err = rollback_main(args.sha, args.repo, _use_llm(args), args.push, args.github, args.base, args.respect_override)
        sys.stdout.write(out)
        print(err, file=sys.stderr)
        return code

    if args.cmd == "serve":
        from .serve import serve

        serve(args.host, args.port, _use_llm(args), _use_subq(args))
        return 0

    if args.cmd == "log":
        return _cmd_log(args)


    if args.cmd == "demo":
        import tempfile

        from .demo import build_demo_repo, demo_prs
        from .notify import format_message
        from .verify import verify

        from concurrent.futures import ThreadPoolExecutor

        root = args.keep or tempfile.mkdtemp(prefix="mergegate-demo-")
        repo = build_demo_repo(root)
        prs = demo_prs(repo)
        with ThreadPoolExecutor(max_workers=len(prs)) as pool:
            use, subq_on = _use_llm(args), _use_subq(args)
            results = list(pool.map(lambda p: verify(p, use_llm=use, use_subq=subq_on), prs))
        for pr, r in zip(prs, results):
            print(f"===== {pr.pr_id}: {pr.title} -> {r.verdict} (route to {r.owners[0].name if r.owners else '?'})")
            print(format_message(r))
            print()
        return 0

    if args.cmd == "learn":
        return _cmd_learn(args)


    if args.cmd == "bench":
        from .bench import load_cases, score
        from .verify import verify

        cases = load_cases(args.root, args.split)
        if not cases:
            print(f"no cases under {args.root}/cases", file=sys.stderr)
            return 1
        if args.baseline:
            return _bench_baseline(args, cases)

        from concurrent.futures import ThreadPoolExecutor

        use = False if args.stub else _use_llm(args)

        def run(c):
            return stub_report(c.pr.pr_id) if args.stub else verify(c.pr, use_llm=use, use_subq=False)  # benchmark: no routing calls

        with ThreadPoolExecutor(max_workers=6) as pool:
            reports = {c.pr.pr_id: r for c, r in zip(cases, pool.map(run, cases))}
        print(json.dumps(score(cases, reports), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
