# Merge Gate

Merge Gate checks every external or AI-written PR in a large codebase and sends what it finds to the
engineer who actually wrote the code being changed, as an iMessage on their phone.

Built by Michael, TAAZ and Peter (with Claude writing code) at the AIE Code Summit 2026 Hackathon, Shack15 SF.  
**Core design rule:** *Easy to stop, hard to approve.*

---

## Quick start

### 1. Python Backend & CLI
```bash
pip install -e ".[dev]"
python -m merge_gate verify --pr demo-1 --stub
pytest
```

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

### 2. Interactive Web UI & Simulator
```bash
npm install
npm run dev
```

---

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
| Interactive Web Dashboard & Simulator | Peter / Frontend | `src/`, `index.html` | done |

---

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

---

## Design Rule: Easy to Stop, Hard to Approve

If the owner replies **`BLOCK`** from their phone, the PR is blocked at once in CI.  
A text message alone can never approve or merge; approval requires GitHub login with the owner's own credentials.

Owner phone replies:
- `BLOCK`: Blocks the PR immediately.
- `WHY`: Returns the reproducing failing test case and output traceback.
- `OK`: Does not merge. Replies with authenticated GitHub review link.
- `FALSE ALARM`: Logged as feedback into the Secondary Learning Track.

---

## Built during the hackathon

Everything in this repo was written on Saturday, Nov 7, 2026, at the AIE Code Summit Hackathon, after
10:45 AM. Nothing was carried over from an earlier project.

| Component | Where |
|---|---|
| Verdict contract (BLOCK / REVIEW / PASS, evidence, owners, run hash) | `merge_gate/schema.py` |
| Deterministic verdict (no LLM decides) | `merge_gate/verify.py` |
| Anti-gaming rules R1–R6 (deleted/skipped tests, weakened asserts, mocked subject, hardcoded outputs, out-of-scope test edits) | `merge_gate/rules.py` |
| Spec-only test writer: Muse Spark sees the issue + public interface, never the PR's tests | `merge_gate/testgen.py`, `merge_gate/llm.py` |
| Sandbox runner: `git archive` into a temp dir, pytest with timeout, scrubbed env, replayable hash | `merge_gate/sandbox.py` |
| Ownership resolver: `git blame` on the changed base lines, recency-weighted, CODEOWNERS fallback | `merge_gate/owners.py` |
| iMessage formatter + reply handling (BLOCK / WHY / OK / FALSE ALARM / free text) | `merge_gate/notify.py` |
| Benchmark format + scoring (catch rate, false blocks, routing accuracy) | `merge_gate/bench.py`, `benchmark/` |
| Demo scenarios + CLI | `merge_gate/demo.py`, `merge_gate/cli.py` |
| Web UI: pipeline view, phone simulator, learning track | `src/` |
| GitHub Actions check | `templates/merge-gate.yml` |

### Synthetic authors (disclosure)

The benchmark target repo is committed under at least 5 synthetic author identities so that owner
routing can be measured. Commit timestamps are real (today); only author names and emails are
simulated. Phone numbers live only in a local, git-ignored `.env` and never appear in this repo.

### Models and services

- **Muse Spark 1.3** (Meta Model API, standard tier): writes spec-only tests, iMessage summaries, and turns owner replies into tests. It never decides the verdict.
- **SubQ Snap 1.1**: picks which candidate owner to page and how urgently, with the full file history in context.
- **Gemini**: the implementer under test, from a different model family than the gate.
- **Sendblue**: iMessage delivery with SMS fallback. **MongoDB Atlas**: run log and test registry.
