# Benchmark 2: real bugs from BugsInPy

This complements the synthetic 30-PR benchmark in `benchmark/` (which also measures routing).

The cases in `cases/` come from **real bugs in real open-source projects**, taken from
[BugsInPy](https://github.com/soarsmu/BugsInPy) (Widyasari et al., ESEC/FSE 2020). Results are in
[RESULTS.md](RESULTS.md) and `results.json`.

## How a case is made (`build_bugsinpy.py`)

Each BugsInPy bug gives a buggy commit, a fixed commit, the source patch, and a test that fails on the
buggy code and passes on the fixed code. For every bug we create two pull requests in a clone of the
upstream project:

| Case | Base | Head | Label |
| --- | --- | --- | --- |
| `bip-<project>-<n>-bad` | the fixed commit | the patch reverted: the real bug comes back | BLOCK |
| `bip-<project>-<n>-clean` | the buggy commit | the patch applied: the real fix | PASS |

**Every label is checked before it is kept.** BugsInPy's own test (from the fixed commit) must pass on
the bad PR's base and not pass on its head, and not pass on the clean PR's base and pass on its head.
Bugs that do not reproduce in this environment are skipped and listed by the builder, never forced.
No system under test ever sees that test.

- Projects: PySnooper (MIT), cookiecutter (BSD-3-Clause), thefuck (MIT), cloned from upstream at build time.
- The projects date from 2019 and need Python 3.8, so the sandbox runs them with
  `MERGE_GATE_SANDBOX_PYTHON` pointing at a 3.8 venv; the gate itself runs on 3.11+.
- Issue texts are ours (BugsInPy has none). They never describe the bug: the bad PR says "simplify,
  behaviour must not change"; the clean PR says "there is a bug in <file>, fix it".
- Splits alternate bug by bug: train for the learning loop, heldout for scoring.
- `true_owner_email` comes from git blame, so **routing is not scored on these cases** (it would grade
  blame with blame). Routing is shown on the synthetic demo repo instead.
- Commit authors of the generated PR commits are `coding-agent` / `outside-contributor`.

## Rebuild and rerun

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/soarsmu/BugsInPy.git benchmark/bugsinpy/_bugsinpy/meta
git -C benchmark/bugsinpy/_bugsinpy/meta sparse-checkout set projects/PySnooper projects/cookiecutter projects/thefuck
git clone https://github.com/cool-RR/PySnooper benchmark/bugsinpy/target_repos/PySnooper   # and cookiecutter, thefuck
uv python install 3.8   # then: <python3.8> -m venv benchmark/bugsinpy/.venv38 and install the projects' requirements
MERGE_GATE_SANDBOX_PYTHON=benchmark/bugsinpy/.venv38/Scripts/python.exe python benchmark/bugsinpy/build_bugsinpy.py
MERGE_GATE_SANDBOX_PYTHON=benchmark/bugsinpy/.venv38/Scripts/python.exe python benchmark/bugsinpy/run_benchmark.py
```

`_bugsinpy/`, `target_repos/` and the venvs are git-ignored; `cases/` is committed.

## case.json

```json
{
  "pr_id": "bip-thefuck-1-bad",
  "repo": "target_repos/thefuck",
  "base_ref": "<fixed commit>",
  "head_ref": "<revert commit>",
  "title": "Simplify thefuck/rules/pip_unknown_command.py",
  "issue_text": "Clean up ...: simplify the implementation ... Behaviour must not change.",
  "opened_by": "A coding agent",
  "label": {"kind": "logic_bug", "true_verdict": "BLOCK", "true_owner_email": "...", "split": "train"},
  "source": {"dataset": "BugsInPy", "project": "thefuck", "bug": 1, "buggy_commit": "...", "fixed_commit": "...",
             "ground_truth_test": "tests/rules/test_pip_unknown_command.py::test_get_new_command"}
}
```

`repo` is relative to `benchmark/`. `kind` is one of the kinds in `merge_gate/bench.py`.
