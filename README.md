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
