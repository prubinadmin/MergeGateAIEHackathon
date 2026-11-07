# Merge Gate

Merge Gate checks every external or AI-written PR in a large codebase and sends what it finds to the
engineer who actually wrote the code being changed, as an iMessage on their phone.

Built by Michael, TAAZ and Peter at the AIE Code Summit 2026 Hackathon, Shack15 SF.

## Quick start

```bash
pip install -e ".[dev]"
python -m merge_gate verify --pr demo-1 --stub
pytest
```

## Who owns which file

| Area | Owner | Files | Status |
| --- | --- | --- | --- |
| Verdict contract | all (change by agreement) | `merge_gate/schema.py` | done |
| PR access (diff, files, refs) | Michael | `merge_gate/pr.py` | done |
| Deterministic verdict | Michael | `merge_gate/verify.py` (`decide`) | done |
| Rules R1-R9 (anti-gaming + SQL/eval/backdoor) | Michael | `merge_gate/rules.py` | done |
| Ownership resolver (line-level blame, recency-weighted) | Michael | `merge_gate/owners.py` | done |
| Sandbox runner (git archive, scrubbed env, timeout) | Michael | `merge_gate/sandbox.py` | done |
| Spec-only test writer + summary (Muse Spark) | Michael | `merge_gate/testgen.py`, `merge_gate/llm.py` | done |
| iMessage send / reply | TAAZ | `merge_gate/notify.py` (`Notifier`, `parse_reply`, `handle_reply`) | console stub works; plug in the iMessage provider |
| Benchmark cases + scoring | Peter | `benchmark/`, `merge_gate/bench.py` | format + scoring done; cases to build |

Run the three demo scenarios (builds a throwaway multi-author repo):

```bash
python -m merge_gate demo          # rules + ownership only, no API
python -m merge_gate demo --llm    # adds Muse Spark tests and summaries (needs MUSE_API_KEY in .env.local)
```

Try the whole loop without any API:

```bash
python -m merge_gate verify --pr demo-1 --stub > report.json
python -m merge_gate notify report.json --reply BLOCK
```

## The verdict contract

Every component exchanges one JSON report, defined in `merge_gate/schema.py`:

```json
{
  "pr_id": "demo-1",
  "verdict": "BLOCK | REVIEW | PASS",
  "evidence": [{"type": "failing_test | rule", "id": "R1_DELETED_TEST", "detail": "...", "file": "...", "line": 41}],
  "owners": [{"name": "Peter", "email": "...", "lines": 18, "last_touched": "2026-03-14", "score": 0.82}],
  "summary": "plain-English text for the iMessage",
  "run_hash": "sha256:...",
  "gate_version": "v1"
}
```

- `owners[0]` is the person to message.
- A BLOCK always carries at least one piece of evidence.
- `python -m merge_gate validate report.json` checks a report against the contract.

## Built during the hackathon

Everything in this repository was written on Nov 7, 2026, after 10:45.

- Verdict contract and CLI (`merge_gate/schema.py`, `merge_gate/cli.py`)
- PR access over git, deterministic verdict (`merge_gate/pr.py`, `merge_gate/verify.py`)
- iMessage contract with a console notifier (`merge_gate/notify.py`)
- Benchmark case format and scoring (`benchmark/README.md`, `merge_gate/bench.py`)
- Deterministic rules R1-R9 (`merge_gate/rules.py`)
- Line-level ownership resolver (`merge_gate/owners.py`)
- Sandboxed pytest runner (`merge_gate/sandbox.py`)
- Muse Spark client, spec-only test writer, iMessage summary (`merge_gate/llm.py`, `merge_gate/testgen.py`, `merge_gate/verify.py`)
- Demo repo with three PRs; authors are simulated in commit metadata only (`merge_gate/demo.py`)
