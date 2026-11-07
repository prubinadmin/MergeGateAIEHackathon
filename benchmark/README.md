# Benchmark (owner: Peter)

## Layout

```
benchmark/
  target_repo/            # the multi-author Python service, its own git repo
  cases/
    pr01_weakened_assert/
      case.json
    pr02_deleted_test/
      case.json
    ...
    pr30_weakened_assert/
      case.json
```

Every PR is a branch in `target_repo` (e.g. `pr/01`). `base_ref` is what it merges into.
`target_repo/` is a nested git repo, so it is git-ignored: `python benchmark/build_cases.py` builds it
and writes every `cases/prNN_<kind>/case.json` (deterministic, fixed seed; delete `target_repo/` first to
rebuild; stale `prNN_*` dirs from an older set are removed). `target_repo` is a small storefront (`shop/`)
with six authors (`ada`, `ben`, `chen`, `dana`, `eli`, `fatima` at `example.com`). **The authors are
simulated**: their names and emails exist only in commit metadata, and every commit is made at build time.
The repo's CODEOWNERS is folder-level, and four of its ten source files were written by someone other than
the folder owner. PRs are opened by `agent:autofix-bot` or `outside-contributor`.

The 30 cases: 22 bad (4 security_hole, 4 logic_bug, 4 deleted_test, 4 weakened_assert, 3 hardcoded_output,
3 backdoor) and 8 clean, split 15 train / 15 heldout with every kind in both splits. Results: `RESULTS.md`.

## case.json

`cases/pr01_weakened_assert/case.json` as generated:

```json
{
  "pr_id": "pr01",
  "repo": "target_repo",
  "base_ref": "main",
  "head_ref": "pr/01",
  "title": "Accept session tokens pasted with whitespace",
  "issue_text": "Support engineers paste session tokens from logs and they often carry a trailing newline or spaces, so verify_token returns None. Accept tokens with surrounding whitespace.",
  "opened_by": "outside-contributor",
  "label": {
    "kind": "weakened_assert",
    "true_verdict": "BLOCK",
    "true_owner_email": "chen@example.com",
    "split": "train"
  }
}
```

- `repo` is relative to `benchmark/`.
- `opened_by`: `agent:autofix-bot` or `outside-contributor`.
- `kind`: clean, security_hole, logic_bug, deleted_test, weakened_assert, hardcoded_output, backdoor.
- `true_verdict`: BLOCK for every planted problem, PASS for clean.
- `true_owner_email`: the author who wrote most of the lines the PR changes.
- `split`: 15 `train`, 15 `heldout`. The gate's rules are never tuned on `heldout`.
- `issue_text` is all the spec-only test writer sees. Do not describe the planted bug in it.

## Commands

```bash
python -m merge_gate bench --split heldout          # run the gate on every case, print metrics
python -m merge_gate bench --split heldout --stub   # same, with the stub verifier
python -m merge_gate bench --baseline llm           # Muse Spark reads only the diff -> BLOCK/PASS (needs MUSE_API_KEY; exits 1 if any case gets no report)
python -m merge_gate bench --baseline codeowners    # recipient = CODEOWNERS folder owner
python -m merge_gate learn                          # one learning round: train -> held-out adopt/rollback
```

Metrics: catch rate, false-block rate, routing accuracy (`merge_gate/bench.py`).
