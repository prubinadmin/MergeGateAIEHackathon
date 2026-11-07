# Benchmark results (frozen, run of 2026-11-07)

Every number below was printed by the commands in [Reproduce](#reproduce), run on 2026-11-07 against the
30 cases in `benchmark/cases/` (target repo built by `benchmark/build_cases.py`). Muse Spark model: `muse-spark-1.3`.
The six repo authors are simulated (commit metadata only, every commit made at build time).

## Gate vs baselines (all 30 cases: 22 bad, 8 clean)

| System | Catch rate (bad blocked) | False-block rate (clean blocked) | Routing accuracy |
| --- | --- | --- | --- |
| merge-gate v1, rules only (`--no-llm`) | 9/22 = 0.41 | 0/8 = 0.00 | 30/30 = 1.00 |
| merge-gate v1, full (rules + Muse Spark spec-only tests) | 13/22 = 0.59 | 0/8 = 0.00 | 30/30 = 1.00 |
| merge-gate v2 (after learning), full | 17/22 = 0.77 | 2/8 = 0.25 | 30/30 = 1.00 |
| Baseline: Muse Spark reads the diff, answers BLOCK/PASS | 22/22 = 1.00 | 1/8 = 0.125 | n/a |
| Baseline: CODEOWNERS folder routing | n/a | n/a | 17/30 = 0.57 |

Held-out split only (15 cases: 11 bad, 4 clean):

| System | Catch | False-block | Routing |
| --- | --- | --- | --- |
| merge-gate v1, full | 6/11 = 0.55 | 0/4 = 0.00 | 15/15 = 1.00 |
| merge-gate v2, full | 8/11 = 0.73 | 0/4 = 0.00 | 15/15 = 1.00 |
| LLM reads the diff | 11/11 = 1.00 | 0/4 = 0.00 | n/a |
| CODEOWNERS | n/a | n/a | 7/15 = 0.47 |

A REVIEW verdict counts as "not blocked" (`merge_gate/bench.py`). The CODEOWNERS baseline routes to the
first owner of the first changed file (`merge_gate/baselines.py`).

## Learning rounds (train → held-out, `python -m merge_gate learn --llm`)

Proposals come from train-split misses; each is scored on held-out only and adopted only if held-out
catch does not drop, false-block does not rise, and one of them improves (`merge_gate/learn.py`).

| Round | Learner | Candidates proposed | Decision | Held-out catch / false-block |
| --- | --- | --- | --- | --- |
| 1 | as on `main` | none | no change (v1 stays) | 0.55 / 0.00 → 0.55 / 0.00 |
| 2 | spec-test classes tunable (this PR) | `gate::test_issue` review → block (from pr21, hardcoded_output, train) | **adopted**, v1 → v2 | 0.55 / 0.00 → 0.73 / 0.00 |
| 3 | same | none | no change (v2 stays) | 0.73 / 0.00 → 0.73 / 0.00 |

No proposal was rolled back in these runs: round 2 had a single candidate and it improved held-out.
Rollback is covered by `tests/test_learn.py` but was not triggered on this data.

Why round 1 proposed nothing: the learner on `main` only tunes rules, but every train case that got
through had only spec-test evidence (`gate::test_issue_*`, review severity) or no evidence at all. This PR
lets the learner treat the two spec-test classes (`gate::test_issue`, `gate::test_invariant`) as settings,
like a rule id (`knob()` in `merge_gate/learn.py`).

## What these numbers say (and don't)

- **The plain LLM reviewer catches more than the gate on this benchmark** (22/22 vs 13/22 for v1, 17/22 for v2).
  The planted problems are visible in short diffs (a hardcoded token, `assert True`, an f-string query), and
  the diff reviewer is told which categories to look for. The gate's verdicts come with evidence: a rule hit
  or a failing spec-only test. The LLM baseline returns one word.
- **Learning v1 → v2 helped held-out without new held-out false blocks, but it cost false blocks on train**:
  the two clean train cases (pr09, pr13) with a failing `test_issue` now BLOCK, so v2's false-block rate on
  all 30 is 2/8. The rule only checks held-out, by design, and held-out has 4 clean cases. That is too few to see this cost.
- **Routing**: line-level blame routed 30/30, CODEOWNERS 17/30. The label is *defined* as the author of most
  changed base lines (`benchmark/README.md`), which is what the gate's blame measures, so 30/30 shows the
  resolver works as specified. It doesn't measure taste. The repo's CODEOWNERS is folder-level, and 4 of 10 source files
  were written by someone other than the folder owner. That was a deliberate design choice and it explains the 13 misses.
- One team wrote the cases, the gate and the baselines. 30 cases is small: one case moves a held-out
  rate by 9 points (bad) or 25 points (clean).

## Reproduce

```bash
python benchmark/build_cases.py                     # target repo + cases (delete benchmark/target_repo/ first to rebuild)
python -m merge_gate bench --no-llm                 # gate v1, rules only
python -m merge_gate bench --llm                    # gate v1, full (needs MUSE_API_KEY in .env)
python -m merge_gate bench --baseline llm           # Muse Spark reads the diff
python -m merge_gate bench --baseline codeowners    # CODEOWNERS routing
python -m merge_gate learn --llm                    # round 2 (adopts v2); run again for round 3
python -m merge_gate bench --llm                    # gate v2 (bench uses gate_versions/current.json)
# add --split heldout to any bench command for the held-out table
```

Runs used a clean working directory (no `gate_versions/`, so the gate started at v1, and an empty
`runs/log.jsonl`, so there were no FALSE ALARM replies), `--root` pointing at `benchmark/`, and
`MONGODB_URI` unset. `learn` writes `gate_versions/` and `bench` reads it, so delete `gate_versions/`
to start again from v1. Round 1 ran the learner from `main`; with this PR's learner the first round is the one that adopts v2.

Muse Spark responses are cached on disk by request hash (`.cache/llm/`). Re-runs with that cache are
exact replays. Without it the model writes new tests and verdicts, so the numbers can differ.
Wall time of today's run, all commands, cold cache: about 9 minutes. That was 418 s for the full-gate bench
(60 model calls plus 60 sandboxed pytest runs, 6 workers), 42 s for the LLM baseline, 10 to 32 s per learn
round, 3 s for rules only. The full-gate bench and the LLM baseline ran at the same time.
