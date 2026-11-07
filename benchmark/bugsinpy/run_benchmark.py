"""Score Merge Gate against baselines on the BugsInPy cases; write benchmark/bugsinpy/RESULTS.md and results.json.

Systems compared on the same cases:
  gate (rules only)   deterministic rules + decide(), no model
  gate (full)         rules + Muse Spark spec-only tests run in the sandbox, decide() in plain code
  plain LLM reviewer  Muse Spark reads the diff (plus title and issue) and answers BLOCK or PASS

Usage (BugsInPy cases need the 3.8 sandbox interpreter):
  MERGE_GATE_SANDBOX_PYTHON=benchmark/bugsinpy/.venv38/Scripts/python.exe python benchmark/bugsinpy/run_benchmark.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # repo root

from merge_gate import llm  # noqa: E402
from merge_gate.bench import Case, load_cases, score  # noqa: E402
from merge_gate.schema import Evidence, VerdictReport  # noqa: E402
from merge_gate.verify import verify  # noqa: E402

REVIEWER_PROMPT = """You are a senior engineer reviewing a pull request before merge.
Read the title, the issue it claims to address, and the diff. Decide whether it is safe to merge.
Answer with exactly one word on the first line: BLOCK if the change introduces a bug, a security hole,
or games the tests; PASS otherwise. Then one sentence of reasoning."""

MAX_DIFF = 30000


def plain_llm_review(case: Case) -> VerdictReport:
    pr = case.pr
    user = f"TITLE: {pr.title}\nISSUE: {pr.issue_text}\n\nDIFF:\n{pr.diff()[:MAX_DIFF]}"
    try:
        text = llm.complete(REVIEWER_PROMPT, user).strip()
    except llm.LLMError as e:
        return VerdictReport(pr_id=pr.pr_id, verdict="REVIEW", evidence=[Evidence("rule", "LLM_ERROR", str(e), severity="review")])
    first = (text.split() or ["PASS"])[0].upper().strip(".:*")
    verdict = "BLOCK" if first.startswith("BLOCK") else "PASS"
    ev = [Evidence("rule", "LLM_REVIEW", text[:300], severity="block")] if verdict == "BLOCK" else []
    return VerdictReport(pr_id=pr.pr_id, verdict=verdict, evidence=ev, summary=text[:300])


def run_system(name: str, cases: list[Case], fn, workers: int = 6) -> dict[str, VerdictReport]:
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        reports = list(pool.map(fn, cases))
    print(f"{name}: {len(cases)} cases in {time.monotonic() - t0:.0f}s", flush=True)
    return {c.pr.pr_id: r for c, r in zip(cases, reports)}


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def main() -> int:
    cases = [c for c in load_cases(HERE) if c.pr.pr_id.startswith(sys.argv[1] if len(sys.argv) > 1 else "")]
    if not cases:
        print("no cases")
        return 1
    systems = {
        "gate (rules only)": lambda c: verify(c.pr, use_llm=False, config=None),
        "gate (full)": lambda c: verify(c.pr, use_llm=True, config=None),
        "plain LLM reviewer": plain_llm_review,
    }
    results = {name: run_system(name, cases, fn) for name, fn in systems.items()}

    splits = {"heldout": [c for c in cases if c.label.split == "heldout"],
              "train": [c for c in cases if c.label.split == "train"],
              "all": cases}
    table = {name: {s: score(cs, reps) for s, cs in splits.items()} for name, reps in results.items()}

    per_case = []
    for c in cases:
        row = {"case": c.pr.pr_id, "kind": c.label.kind, "truth": c.label.true_verdict, "split": c.label.split}
        for name, reps in results.items():
            r = reps[c.pr.pr_id]
            row[name] = r.verdict
            row[name + " evidence"] = [e.id for e in r.evidence]
        per_case.append(row)

    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": dt.datetime.now().isoformat(timespec="seconds"), "scores": table, "cases": per_case}, f, indent=2)

    bad = sum(c.label.true_verdict == "BLOCK" for c in cases)
    lines = [
        "# Benchmark results",
        "",
        f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `benchmark/bugsinpy/run_benchmark.py`. {len(cases)} cases "
        f"({bad} bad, {len(cases) - bad} clean) from real bugs in BugsInPy; every label was checked against "
        "BugsInPy's own test, which no system sees. A REVIEW counts as not blocked.",
        "",
        "| System | Held-out catch | Held-out false blocks | All catch | All false blocks |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in results:
        h, a = table[name]["heldout"], table[name]["all"]
        lines.append(f"| {name} | {pct(h['catch_rate'])} of {h['bad']} | {pct(h['false_block_rate'])} of {h['clean']} | "
                     f"{pct(a['catch_rate'])} of {a['bad']} | {pct(a['false_block_rate'])} of {a['clean']} |")
    lines += ["", "Routing is not scored here: on real projects the true owner can only come from git blame,",
              "which is what the gate uses. Routing is shown on the synthetic demo repo instead.", "",
              "| Case | Truth | " + " | ".join(results) + " |", "| --- | --- | " + " | ".join("---" for _ in results) + " |"]
    for row in per_case:
        lines.append(f"| {row['case']} | {row['truth']} | " + " | ".join(row[n] for n in results) + " |")
    with open(os.path.join(HERE, "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:10 + len(results)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
