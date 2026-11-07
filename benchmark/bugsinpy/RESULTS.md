# Benchmark results

Generated 2026-11-07 14:30 by `benchmark/bugsinpy/run_benchmark.py`. 24 cases (12 bad, 12 clean) from real bugs in BugsInPy; every label was checked against BugsInPy's own test, which no system sees. A REVIEW counts as not blocked.

| System | Held-out catch | Held-out false blocks | All catch | All false blocks |
| --- | --- | --- | --- | --- |
| gate (rules only) | 0% of 6 | 0% of 6 | 0% of 12 | 0% of 12 |
| gate (full) | 17% of 6 | 0% of 6 | 42% of 12 | 0% of 12 |
| plain LLM reviewer | 100% of 6 | 67% of 6 | 100% of 12 | 50% of 12 |

## What these numbers say (and do not)

- **Every BLOCK from the full gate was right (5 of 5), and each came with a test that passes on base and
  fails on the PR. It blocked no correct fix (0 of 12).** It missed 7 of 12 re-introduced bugs.
- The plain LLM reviewer blocked every bad PR (12 of 12) but also blocked 6 of the 12 real fixes (50%).
- Rules alone caught nothing here: these are pure logic bugs with no test gaming, which is what the
  spec-only tests are for.
- The full gate sent 7 clean PRs to REVIEW (the owner is asked, nothing is blocked). That is noise for the owner.
- Small sample: 12 real bugs from 3 projects, 6 held out. Treat the percentages as rough.
- Possible bias in the baseline: the bad PRs' issue text asks to "remove special cases that look
  unnecessary" and their diffs delete code, which may cue the reviewer toward BLOCK; the clean PRs say
  "there is a bug". The gate's test writer sees the same issue texts.

Routing is not scored here: on real projects the true owner can only come from git blame,
which is what the gate uses. Routing is shown on the synthetic demo repo instead.

| Case | Truth | gate (rules only) | gate (full) | plain LLM reviewer |
| --- | --- | --- | --- | --- |
| bip-PySnooper-1-bad | BLOCK | REVIEW | REVIEW | BLOCK |
| bip-PySnooper-1-clean | PASS | REVIEW | REVIEW | PASS |
| bip-cookiecutter-4-bad | BLOCK | PASS | PASS | BLOCK |
| bip-cookiecutter-4-clean | PASS | PASS | PASS | BLOCK |
| bip-thefuck-1-bad | BLOCK | PASS | PASS | BLOCK |
| bip-thefuck-1-clean | PASS | PASS | REVIEW | PASS |
| bip-thefuck-2-bad | BLOCK | PASS | PASS | BLOCK |
| bip-thefuck-2-clean | PASS | PASS | REVIEW | PASS |
| bip-thefuck-22-bad | BLOCK | PASS | BLOCK | BLOCK |
| bip-thefuck-22-clean | PASS | PASS | PASS | PASS |
| bip-thefuck-24-bad | BLOCK | PASS | PASS | BLOCK |
| bip-thefuck-24-clean | PASS | PASS | REVIEW | BLOCK |
| bip-thefuck-25-bad | BLOCK | PASS | BLOCK | BLOCK |
| bip-thefuck-25-clean | PASS | PASS | REVIEW | PASS |
| bip-thefuck-26-bad | BLOCK | PASS | PASS | BLOCK |
| bip-thefuck-26-clean | PASS | PASS | PASS | BLOCK |
| bip-thefuck-27-bad | BLOCK | PASS | BLOCK | BLOCK |
| bip-thefuck-27-clean | PASS | PASS | PASS | BLOCK |
| bip-thefuck-29-bad | BLOCK | PASS | BLOCK | BLOCK |
| bip-thefuck-29-clean | PASS | PASS | REVIEW | BLOCK |
| bip-thefuck-31-bad | BLOCK | PASS | BLOCK | BLOCK |
| bip-thefuck-31-clean | PASS | PASS | REVIEW | BLOCK |
| bip-thefuck-32-bad | BLOCK | PASS | PASS | BLOCK |
| bip-thefuck-32-clean | PASS | PASS | PASS | PASS |
