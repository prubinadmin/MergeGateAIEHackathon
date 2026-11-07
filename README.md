# Merge Gate

Merge Gate checks every external or AI-written PR in a large codebase and sends what it finds to the
engineer who actually wrote the code being changed, as an iMessage on their phone.

Built by Michael, TAAZ and Peter (with Claude writing code) at the AIE Code Summit 2026 Hackathon, Shack15 SF.  
**Core design rule:** *Easy to stop, hard to approve.* A text can stop a merge. It can never approve one.

Live UI (replays a recorded real run; the presenter laptop runs it live): https://dist-phi-five-99.vercel.app  
Benchmark numbers: [`benchmark/RESULTS.md`](benchmark/RESULTS.md). Pitch and Q&A: [`docs/PITCH.md`](docs/PITCH.md).

How a PR goes through the gate:

1. Muse Spark (Meta) writes **spec-only tests** from the issue and the public interface. It never sees the PR's tests.
2. The sandbox runs them on base, then on head (`git archive` copy, scrubbed env, timeout).
3. Deterministic rules **R1–R14** look for gaming (deleted or skipped tests, weakened asserts, mocked subject, hardcoded outputs, out-of-scope test edits), dangerous calls, backdoor literals, unparseable files, and quality regressions.
4. Plain code (`decide()` in `merge_gate/verify.py`) turns the evidence into **BLOCK / REVIEW / PASS**. No LLM decides.
5. Line-level `git blame` finds the engineers who wrote the changed lines; **SubQ Snap 1.1** picks who to page and how urgently, only among eligible owners and only at confidence ≥ 0.80 (injection-safe: it routes, it never decides).
6. The gate **texts the owner by itself** over iMessage (Sendblue) the moment it decides: a full page for BLOCK/REVIEW, an FYI for PASS.
7. The owner replies `BLOCK`, `WHY`, `OK`, `FALSE ALARM`, or a free-text rule. A rule becomes a test stored under the owner's name and run on every PR that touches those files (`TEACH` / `FORGET`). Replies are worded by Muse Spark from the verdict's facts only; they never claim approval.
8. Every run is appended to a hash-chained log, mirrored to MongoDB Atlas when `MONGODB_URI` is set.

---

## Quick demo

```bash
pip install -e ".[dev,agent]"
python -m merge_gate serve              # terminal 1: the real gate's API on 127.0.0.1:8787 (auto-pages owners)
npm run dev                             # terminal 2: War Room UI on http://localhost:3000 (bun install first)
python -m agents.merge_gate_agent       # terminal 3: the Fetch.ai agent team; chat with it in ASI:One
```

No keys: rules, ownership, console notifier. With `MUSE_API_KEY`: spec-only tests and worded replies. With
`SUBQ_API_KEY`: SubQ routing. With `SENDBLUE_*` + `OWNER_PHONES`: real iMessages. With `MONGODB_URI`: the
run log is mirrored to Atlas. Secrets go in `.env` / `secrets/.env` (gitignored).

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
python -m merge_gate learn --llm      # one learning round on benchmark/ (results: benchmark/RESULTS.md)
python -m merge_gate bench --llm      # score the gate on the 30 benchmark cases; --baseline llm|codeowners
python -m merge_gate owner-tests list # rules owners taught the gate by text; `remove <id>` forgets one
python -m merge_gate ci               # inside GitHub Actions: see templates/merge-gate.yml
```

API (all JSON):

| Endpoint | Body | Returns |
| --- | --- | --- |
| `GET /api/health` | | ok |
| `GET /api/demo` | | the three demo PRs with diffs |
| `POST /api/verify` | `{"pr_id": "demo-1"}` or `{"repo_path", "base_ref", "head_ref", "issue_text", ...}` | real verdict report; texts the code owner automatically |
| `GET /api/run?pr_id=demo-1&llm=1` | | Server-Sent Events, one per real stage (`rules`, `owners`, `routing`, `testgen`, `owner_tests`, `decide`, `summary`, `page`), then the report; texts the owner automatically |
| `POST /api/message` | `{"pr_id": "demo-1", "send": true}` | `{"to": owner, "text": iMessage text}`; `send` delivers it via Sendblue |
| `POST /api/reply` | `{"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}}` | action; BLOCK fails the PR's `merge-gate` check. A rule to teach is refused here (403) |
| `POST /api/sendblue?token=SECRET` | Sendblue inbound webhook | acts only if the reply comes from the PR owner's verified phone; fails closed without `SENDBLUE_WEBHOOK_SECRET` |
| `GET /api/log` | | log records, `chain_ok` |
| `GET /api/stats` | | counters for the header bar, from the run log |

**Agentic paging.** `/api/verify` and `/api/run` text the code owner the moment the verdict is decided, with no
click: the full page (verdict, evidence, failing test) on BLOCK or REVIEW, a one-line FYI on PASS. The SSE
stream reports it as the `page` stage (`start`, then `done` with `to`, `text`, `urgency`, `sent`). Delivery is
Sendblue when `SENDBLUE_*` and `OWNER_PHONES` are set, otherwise the console notifier. Set
`MERGE_GATE_AUTO_PAGE=0` to turn automatic texting off.

To enforce on a repo: copy `templates/merge-gate.yml` to `.github/workflows/`, add `MUSE_API_KEY` as a
secret, and make `merge-gate` a required status check. BLOCK -> failure, REVIEW -> pending,
PASS -> success. Only a code owner's GitHub approval (`OWNER_GITHUB` variable) overrides a finding.

Merge Gate runs on its own repository (`.github/workflows/merge-gate.yml`). It blocked or sent to review
several of our own PRs today. We fixed the code, not the rules.

### Rollback

Something already landed? Re-verify it with the same rules, owners and Muse flags as a PR
(base = `<sha>^1`, head = `<sha>`; works for merge commits and plain commits):

```bash
python -m merge_gate rollback <sha> [--repo PATH]                       # BLOCK -> local branch merge-gate/revert-<sha>
python -m merge_gate rollback <sha> --push --github owner/repo          # also push it and open a revert PR (GITHUB_TOKEN)
python -m merge_gate rollback <sha> --base <before>                     # verify a multi-commit push as one diff
```

PASS/REVIEW does nothing and says why. Skipped (exit 0): Merge Gate's own reverts (no revert-of-revert
loop), root commits, and PRs a code owner overrode on GitHub (`--no-respect-override` to revert anyway;
needs GITHUB_TOKEN + `--github`, else it warns and proceeds). When the PR is found on GitHub, its body
and author are the gate's inputs, the same as in the PR run. The revert is built in a temporary
`git worktree`, so your checkout is never touched; it never pushes to the default branch and never
force-pushes; a failed push/PR leaves no local branch, and a remote branch from an earlier attempt is
reused. Each run logs the verdict (source `rollback`) and a `rollback` action record on the same hash chain.

To run it on every push to main: `templates/merge-gate-rollback.yml`. A PR opened with the Actions
`GITHUB_TOKEN` does not trigger `pull_request` workflows, so if `merge-gate` is a required check the
revert PR could never pass it. Add a fine-grained PAT as secret `MERGE_GATE_TOKEN` (Contents + Pull
requests: write, Commit statuses: read); the template uses `${{ secrets.MERGE_GATE_TOKEN || secrets.GITHUB_TOKEN }}`.

### Fetch.ai agents: run the gate inside an ASI:One chat
```bash
pip install -e ".[agent]"
export MERGE_GATE_AGENT_SEED="<long random phrase>"
python -m agents.merge_gate_agent    # then follow agents/README.md to connect the mailbox and chat in ASI:One
```

Five uAgents in one process (`agents/merge_gate_agent.py`, `agents/team.py`): the **orchestrator** faces
ASI:One with the Agent Chat Protocol and an Interactive verdict card (Why / Block buttons); the specialists
**TestWriter**, **Sandbox**, **Rules** and **OwnerRouter** only answer the orchestrator. The verdict is never
delegated: the same `decide()` runs in the orchestrator, so an agent run has the same `run_hash` as an
in-process run.

Orchestrator address (ASI:One-facing):
`agent1qdzxevq4yxvlevawy50n0syq39snynxc00l0xsjuyvlhy3v2jhyecymc4sj`

Try in ASI:One: `list PRs`, `verify demo-1` (BLOCK on R1_DELETED_TEST, routed to Peter), `why demo-1`,
`verify demo-3` (PASS), `approve demo-1` (refused: approval happens on GitHub). A chat `block` is recorded
as a request from the sender's agent address; it is not an owner action.

### 4. War Room UI (live, real gate) and the concept simulator
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
| Rules R1-R14 (anti-gaming, dangerous calls, backdoors, quality regressions) | Michael | `merge_gate/rules.py` | done |
| Ownership resolver (line-level blame, recency-weighted) | Michael | `merge_gate/owners.py` | done |
| SubQ Snap 1.1 routing: who to page, how urgently | Michael | `merge_gate/subq.py` | done; eligible owners only, confidence ≥ 0.80 |
| Sandbox runner (git archive, scrubbed env, timeout) | Michael | `merge_gate/sandbox.py` | done |
| Spec-only test writer + summary (Muse Spark) | Michael | `merge_gate/testgen.py`, `merge_gate/llm.py` | done |
| GitHub status check, PR comment, owner BLOCK | Michael | `merge_gate/github.py`, `merge_gate/ci.py`, `templates/merge-gate.yml` | done |
| Rollback: re-verify merged commits, revert PR on BLOCK | Michael | `merge_gate/rollback.py`, `templates/merge-gate-rollback.yml` | done |
| HTTP API for UI + iMessage webhook + auto-paging | Michael | `merge_gate/serve.py` | done |
| Hash-chained run log (MongoDB Atlas mirror) | Michael | `merge_gate/store.py` | done |
| Learning loop, held-out adoption (rules + spec-test knobs) | Michael | `merge_gate/learn.py`, `gate_versions/` | done; rounds in `benchmark/RESULTS.md` |
| iMessage over Sendblue, worded replies, verified-phone webhook | TAAZ | `merge_gate/imessage.py`, `merge_gate/notify.py` | done |
| Owner replies become tests (TEACH / FORGET) | TAAZ | `merge_gate/owner_tests.py` | done |
| Benchmark cases + scoring + baselines | Peter | `benchmark/`, `merge_gate/bench.py`, `merge_gate/baselines.py` | 30 cases (simulated authors), `benchmark/RESULTS.md` |
| Fetch.ai agent team for ASI:One | Michael | `agents/merge_gate_agent.py`, `agents/team.py` | done; Agentverse mailbox connect is a manual step |
| War Room UI, replay, concept simulator | Peter / Frontend | `src/warroom/`, `src/`, `index.html` | done |

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
- `BLOCK` (also stop / hold / reject / revert / "don't merge"): blocks the PR at once. Stop wins over teach.
- `WHY`: the reproducing failing test and its output.
- `OK`: does not merge. Replies with the GitHub review link, where approval needs the owner's own login.
- `FALSE ALARM`: logged as feedback for the learning loop.
- A sentence that reads like a rule ("pricing must never round before tax", or `RULE: ...`): Muse Spark turns it
  into one pytest test against the public interface. Kept only if it passes on base; stored under the owner's
  name in the gate's data dir, never in the target repo; run on every PR touching those files.
- `FORGET <test>`: removes a taught rule. `python -m merge_gate owner-tests list|remove` does the same from the CLI.

Replies are worded by Muse Spark from the verdict's facts only (blunt voice, roasts the code, never the
person). A regex refuses any reply that says approved, merged, LGTM or ship it. Teaching is accepted only
from the owner's verified phone through the Sendblue webhook, never from the web UI.

---

## Real vs simulated

| Real | Simulated | Recorded |
| --- | --- | --- |
| Muse Spark calls (spec-only tests, summaries, reply wording, sentence-to-test) | Commit author identities in the demo repo (`merge_gate/demo.py`) and the benchmark repo (`benchmark/build_cases.py`): commit metadata only, every commit made at build time | The public site https://dist-phi-five-99.vercel.app replays `src/warroom/recorded-run.json`, a real run captured from `GET /api/run` |
| SubQ Snap 1.1 Decisions API calls (`merge_gate/subq.py`) | | On the presenter laptop the same page runs against the live API |
| Sendblue iMessages to and from real phones (`merge_gate/imessage.py`) | | |
| MongoDB Atlas mirror of the hash-chained run log (`merge_gate/store.py`) | | |
| GitHub status check on this repo's own PRs (`.github/workflows/merge-gate.yml`) | | |
| Agentverse-registered uAgents (`agents/`) | | |

The older concept simulator (`#simulator` tab) is labelled as simulated data in the UI.

---

## Built during the hackathon

Everything in this repository was written on Nov 7, 2026, after 10:45, at the AIE Code Summit 2026 Hackathon.
Every commit is timestamped today.

Gate core
- Verdict contract and CLI (`merge_gate/schema.py`, `merge_gate/cli.py`, `merge_gate/__main__.py`)
- PR access over git, deterministic verdict `decide()` (`merge_gate/pr.py`, `merge_gate/verify.py`)
- Deterministic rules R1-R14 (`merge_gate/rules.py`): R1-R6 anti-gaming, R7 dangerous call, R8 backdoor literal, R9 unparseable, R10-R14 runtime integrity, performance, complexity, style, regulatory style (quality rules are REVIEW; debugger calls and broken imports BLOCK)
- Sandboxed pytest runner: `git archive` copy, scrubbed env, timeout (`merge_gate/sandbox.py`)
- Muse Spark client with on-disk response cache, spec-only test writer, iMessage summary (`merge_gate/llm.py`, `merge_gate/testgen.py`)

Routing and paging
- Line-level ownership resolver, recency-weighted, CODEOWNERS fallback (`merge_gate/owners.py`)
- SubQ Snap 1.1 picks who to page and the urgency; eligible owners only, confidence ≥ 0.80, urgency never below the plain-code floor (`merge_gate/subq.py`)
- iMessage over Sendblue, inbound webhook that only the owner's verified phone can act on, fails closed without a secret; replies worded by Muse Spark from the verdict's facts (`merge_gate/imessage.py`, `merge_gate/notify.py`)
- Agentic auto-paging: `serve` texts the owner on every verdict, full page for BLOCK/REVIEW, FYI for PASS (`merge_gate/serve.py`, `MERGE_GATE_AUTO_PAGE`)

Learning
- Owner replies become tests: one sentence → one pytest test, kept only if it passes on base, stored under the owner's name, TEACH / FORGET (`merge_gate/owner_tests.py`, `python -m merge_gate owner-tests`)
- Learning loop with held-out adoption; the learner tunes rule ids and the two spec-test evidence classes as knobs (`merge_gate/learn.py`, `gate_versions/`)
- Benchmark: 30 labelled PRs on a simulated six-author repo, 15 held-out; LLM-reads-the-diff and CODEOWNERS baselines; frozen results (`benchmark/build_cases.py`, `benchmark/cases/`, `merge_gate/bench.py`, `merge_gate/baselines.py`, `benchmark/RESULTS.md`)

Enforcement and audit
- GitHub status check, PR comment, owner BLOCK, Actions entry point; the gate runs outside the PR checkout so a PR cannot configure its own gate (`merge_gate/github.py`, `merge_gate/ci.py`, `templates/merge-gate.yml`, `.github/workflows/merge-gate.yml`)
- Rollback: re-verify merged commits or a pushed range, revert PR on BLOCK, never pushes to main (`merge_gate/rollback.py`, `templates/merge-gate-rollback.yml`)
- Hash-chained run log, mirrored to MongoDB Atlas (`merge_gate/store.py`, `python -m merge_gate log`)

Agents and UI
- Fetch.ai team: orchestrator on ASI:One with the Agent Chat Protocol and an Interactive verdict card, plus TestWriter, Sandbox, Rules and OwnerRouter specialists (`agents/merge_gate_agent.py`, `agents/team.py`, `agents/README.md`)
- HTTP API with Server-Sent Events per stage (`merge_gate/serve.py`)
- War Room UI on the real API, with a recorded-run replay for the public site (`src/warroom/`), and the concept simulator (`src/`, `index.html`)
- Standalone test-case suite and analyzer for broken, slow, over-complex and non-conforming AI code (`test_cases/`, `scripts/analyze_test_cases.py`, `merge_gate/agent_verifier.py`)
- Demo repo with three PRs (`merge_gate/demo.py`)

Tests: `tests/` (rules, owners, SubQ, sandbox, testgen, owner tests, iMessage, rollback, learn, benchmark, Fetch.ai agent, enforcement, schema).

Disclosure: the authors in the demo and benchmark repositories are synthetic. Names, emails and dates live in
commit metadata only, and every one of those commits was created at build time today.
