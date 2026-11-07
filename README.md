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
python -m merge_gate demo          # Muse Spark ON if MUSE_API_KEY is in .env.local, else rules + ownership only
python -m merge_gate demo --no-llm # force rules + ownership only, no API calls
```

Try the whole loop without any API:
```bash
python -m merge_gate verify --pr demo-1 --stub > report.json
python -m merge_gate notify report.json --reply BLOCK
```

### 2. Test Suite & Issue Ticket Analyzer (Unsafe AI Code Detection)
Analyze all sample test cases or a specific file to detect broken, slow, over-complex, or non-conforming AI code:
```bash
python scripts/analyze_test_cases.py
# Or analyze a single test case:
python scripts/analyze_test_cases.py test_cases/02_performance_latency_slowdown.py
```

### 3. Real gate on GitHub, API, log, learning

```bash
python -m merge_gate serve            # HTTP API on 127.0.0.1:8787 for the web UI and the iMessage webhook
python -m merge_gate log              # run log; checks the hash chain
python -m merge_gate learn            # one learning round on benchmark/ (needs Peter's cases)
python -m merge_gate ci               # inside GitHub Actions: see templates/merge-gate.yml
```

API (all JSON):

| Endpoint | Body | Returns |
| --- | --- | --- |
| `GET /api/demo` | | the three demo PRs with diffs |
| `POST /api/verify` | `{"pr_id": "demo-1"}` | real verdict report |
| `POST /api/message` | `{"pr_id": "demo-1"}` | `{"to": owner, "text": iMessage text}` |
| `POST /api/reply` | `{"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}}` | action; BLOCK fails the PR's `merge-gate` check |
| `GET /api/log` | | log records, `chain_ok` |

To enforce on a repo: copy `templates/merge-gate.yml` to `.github/workflows/`, add `MUSE_API_KEY` as a
secret, and make `merge-gate` a required status check. BLOCK -> failure, REVIEW -> pending,
PASS -> success. Only a code owner's GitHub approval (`OWNER_GITHUB` variable) overrides a finding.

### Rollback

Something already landed? Re-verify it with the same rules, owners and Muse flags as a PR
(base = `<sha>^1`, head = `<sha>`; works for merge commits and plain commits):

```bash
python -m merge_gate rollback <sha> [--repo PATH]                       # BLOCK -> local branch merge-gate/revert-<sha>
python -m merge_gate rollback <sha> --push --github owner/repo          # also push it and open a revert PR (GITHUB_TOKEN)
```

PASS/REVIEW does nothing and says why. The revert is built in a temporary `git worktree`, so your
checkout is never touched; it never pushes to the default branch and never force-pushes. Each run is
logged as kind `rollback`. To run it on every push to main: `templates/merge-gate-rollback.yml`.

### 3. War Room UI (live, real gate) and the concept simulator
```bash
python -m merge_gate serve           # terminal 1: the real gate's API on 127.0.0.1:8787
bun install                          # or: npm install --legacy-peer-deps
npm run dev                          # terminal 2: http://localhost:3000
```

The War Room streams every real stage (`GET /api/run`, Server-Sent Events): rules, owner finder,
Muse Spark tests + sandbox, `decide()`, the owner's message. The phone panel's BLOCK / WHY / OK /
FALSE ALARM buttons call `/api/reply`. Nothing on that page is simulated. The older concept simulator
is still available under its own tab (`#simulator`).

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
| GitHub status check, PR comment, owner BLOCK | Michael | `merge_gate/github.py`, `merge_gate/ci.py`, `templates/merge-gate.yml` | done |
| HTTP API for UI + iMessage webhook | Michael | `merge_gate/serve.py` | done |
| Hash-chained run log (Mongo mirror optional) | Michael | `merge_gate/store.py` | done |
| Learning loop, held-out adoption | Michael | `merge_gate/learn.py`, `gate_versions/` | done; needs benchmark cases |
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

Everything in this repository was written on Nov 7, 2026, after 10:45, at the AIE Code Summit 2026 Hackathon.

- Verdict contract and CLI (`merge_gate/schema.py`, `merge_gate/cli.py`)
- PR access over git, deterministic verdict (`merge_gate/pr.py`, `merge_gate/verify.py`)
- Deterministic rules R1-R9 (`merge_gate/rules.py`)
- Line-level ownership resolver (`merge_gate/owners.py`)
- Sandboxed pytest runner (`merge_gate/sandbox.py`)
- Muse Spark client, spec-only test writer, iMessage summary (`merge_gate/llm.py`, `merge_gate/testgen.py`)
- GitHub status check, PR comment, owner BLOCK, Actions entry point (`merge_gate/github.py`, `merge_gate/ci.py`, `templates/merge-gate.yml`)
- HTTP API (`merge_gate/serve.py`), hash-chained run log (`merge_gate/store.py`)
- Learning loop with held-out adoption (`merge_gate/learn.py`)
- iMessage contract with a console notifier (`merge_gate/notify.py`)
- Benchmark case format and scoring (`benchmark/README.md`, `merge_gate/bench.py`)
- Demo repo with three PRs; authors are simulated in commit metadata only (`merge_gate/demo.py`)
- War Room UI on the real API (`src/warroom/`) and the concept simulator (`src/`, `index.html`)
