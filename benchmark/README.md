# Benchmark (owner: Peter)

## Layout

```
benchmark/
  target_repo/            # the multi-author Python service, its own git repo
  cases/
    pr01_deleted_test/
      case.json
    pr02_clean/
      case.json
```

Every PR is a branch in `target_repo` (e.g. `pr/01`). `base_ref` is what it merges into.
`target_repo/` is a nested git repo, so it is git-ignored: generate it with a script
(`benchmark/build_target_repo.py`) and commit the script, so anyone can rebuild the same repo.
`target_repo` needs at least 5 author identities so routing can be tested. Commit timestamps stay
today; only author name/email are simulated (say so in the main README).

## case.json

```json
{
  "pr_id": "pr01",
  "repo": "target_repo",
  "base_ref": "main",
  "head_ref": "pr/01",
  "title": "Speed up apply_discount",
  "issue_text": "apply_discount is slow for bulk orders ...",
  "opened_by": "agent:gemini",
  "label": {
    "kind": "deleted_test",
    "true_verdict": "BLOCK",
    "true_owner_email": "peter@example.com",
    "split": "train"
  }
}
```

- `repo` is relative to `benchmark/`.
- `kind`: clean, security_hole, logic_bug, deleted_test, weakened_assert, hardcoded_output, backdoor.
- `true_verdict`: BLOCK for every planted problem, PASS for clean.
- `true_owner_email`: the author who wrote most of the lines the PR changes.
- `split`: 15 `train`, 15 `heldout`. The gate's rules are never tuned on `heldout`.
- `issue_text` is all the spec-only test writer sees. Do not describe the planted bug in it.

## Commands

```bash
python -m merge_gate bench --split heldout          # run the gate on every case, print metrics
python -m merge_gate bench --split heldout --stub   # same, with the stub verifier
```

Metrics: catch rate, false-block rate, routing accuracy (`merge_gate/bench.py`).
