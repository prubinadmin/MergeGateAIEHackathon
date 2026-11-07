# Submission drafts

Copy-paste material for the Cerebral Valley form, the Fetch.ai ASI:One Submission Agent, and the 60-second
video. Numbers come from [`benchmark/RESULTS.md`](../benchmark/RESULTS.md) only.

## Cerebral Valley form

**Project name:** Merge Gate

**One-liner:** An independent verifier for AI-written PRs that writes its own tests from the spec, decides
BLOCK/REVIEW/PASS in plain code, texts the engineer who wrote the lines, and learns from what they text back.

**Problem statements addressed**
- **Trust but Verify.** The gate never reads the PR's tests, diff or description when it writes tests, so a PR
  cannot prompt its own reviewer. Every verdict carries evidence: a rule id (R1–R14) or a failing spec-only
  test with output. No LLM decides the verdict. Each run is hash-chained and replayable.
- **The System That Gets Better.** The code owner's free-text reply becomes a pytest test stored under their
  name and run on every later PR. Proposed gate changes are adopted only if held-out PRs confirm: gate v1 → v2
  raised held-out catch from 0.55 to 0.73 with held-out false blocks staying at 0.00.

**Tracks**
- **Meta (Muse Spark):** writes spec-only tests, the owner's summary, the worded replies, and turns an owner's
  sentence into a test. Never decides.
- **SubQ (Snap 1.1):** one Decisions API call per verify picks who to page among eligible blame candidates
  and scores urgency; applied only at confidence ≥ 0.80, urgency never below the plain-code floor.
- **Fetch.ai:** five uAgents; the orchestrator faces ASI:One with the Agent Chat Protocol and an Interactive
  verdict card, four specialists (TestWriter, Sandbox, Rules, OwnerRouter) do the work. The verdict is never
  delegated. Address: `agent1qdzxevq4yxvlevawy50n0syq39snynxc00l0xsjuyvlhy3v2jhyecymc4sj`.
- **MongoDB:** the hash-chained run log is mirrored to MongoDB Atlas (`mergegate.runs`).

**Repo URL:** https://github.com/prubinadmin/MergeGateAIEHackathon

**Demo URL:** https://dist-phi-five-99.vercel.app (replays a recorded real run; the live gate runs on the
presenter laptop against the same page)

**What was built today** (everything; every commit is timestamped 2026-11-07 after 10:45)
- Spec-only test writer + sandbox runner + deterministic rules R1–R14 + plain-code verdict
- Line-level blame routing, SubQ Snap 1.1 owner/urgency pick, CODEOWNERS fallback
- Real iMessage over Sendblue with a verified-phone, token-checked webhook; agentic auto-paging on every
  verdict; replies worded by Muse Spark from the verdict's facts, never claiming approval
- Owner replies → tests (TEACH / FORGET), learning loop with held-out adoption (v1 → v2)
- 30-case benchmark (22 bad, 8 clean, 15 held-out), LLM-reads-the-diff and CODEOWNERS baselines, frozen results
- GitHub status check (the gate runs on its own repo and blocked several of our PRs today; we fixed the code),
  rollback command that re-verifies merged commits and opens revert PRs
- Hash-chained run log mirrored to MongoDB Atlas
- Fetch.ai agent team for ASI:One, War Room UI with per-stage streaming and a recorded-run replay

**Honest numbers** (all 30 cases / held-out 15)
- Merge Gate v2: catch 17/22, false blocks 2/8 / held-out 8/11, 0/4
- Merge Gate v1 (before learning): 13/22, 0/8 / 6/11, 0/4
- Plain LLM reads the diff: 22/22, 1/8 / 11/11, 0/4. It catches more on this small, self-authored benchmark.
  Our edge is independence from the diff, evidence per verdict, routing to the author (30/30 vs CODEOWNERS
  17/30), learning from the author, replayable runs and rollback.

**Team:** Michael, TAAZ, Peter (with Claude writing code). AIE Code Summit 2026 Hackathon, Shack15 SF.

**Simulated parts, disclosed:** commit author identities in the demo and benchmark repos exist in commit
metadata only and were created at build time. The public site replays a recorded run.

## Fetch.ai: ASI:One Submission Agent checklist

In ASI:One, open the **AIE Summit ASI:One Submission Agent** (search in ASI:One or the Agentverse
marketplace) and give it:

- [ ] Agent address: `agent1qdzxevq4yxvlevawy50n0syq39snynxc00l0xsjuyvlhy3v2jhyecymc4sj`
- [ ] Agentverse profile link: copy it from the agent's **Agent Profile** page on the Agentverse dashboard
      after the mailbox connect (`agents/README.md`, "Register and test in ASI:One", step 3). Name **Merge Gate**,
      handle `@merge-gate`, description: "Checks a PR with real rules, code ownership and a test sandbox;
      routes findings to the engineer who wrote the code. A chat can block a merge, never approve one."
- [ ] Repo: https://github.com/prubinadmin/MergeGateAIEHackathon
- [ ] Before submitting: the agent is running (`python -m agents.merge_gate_agent`) with the mailbox connected;
      `list PRs`, `verify demo-1` (BLOCK, R1_DELETED_TEST, routed to Peter, card with Why / Block),
      `verify demo-3` (PASS) and `approve demo-1` (refused) all answer in ASI:One.
- [ ] Any extra fields the submission agent asks for: use the one-liner and the Fetch.ai track paragraph above.

## 60-second video shot list

Screen-record the War Room (`npm run dev` against `python -m merge_gate serve`) and a phone camera on Peter's
iPhone. No narration over silence; every shot has one sentence.

| # | Seconds | Shot | One sentence |
|---|---|---|---|
| 1 | 0–6 | GitHub PR page: agent-authored PR, green checks, "deletes test_discount_never_negative" visible in the diff | "An agent opened this PR. Its own tests are green." |
| 2 | 6–14 | War Room stage stream: rules hit R1, blame finds Peter, SubQ picks Peter and "page now" | "Merge Gate finds the engineer who wrote those lines." |
| 3 | 14–22 | War Room: Muse Spark writes spec-only tests, sandbox runs base then head, one test fails | "It writes its own tests from the issue. It never saw the PR's." |
| 4 | 22–30 | Phone camera: iPhone on a desk lights up by itself with the verdict text | "Nobody clicked send. The owner's phone buzzes with the proof." |
| 5 | 30–37 | Phone camera: Peter types BLOCK; cut to GitHub check turning red | "One word stops the merge." |
| 6 | 37–43 | Phone camera: Peter types "pricing must never round before tax"; War Room shows the new test under his name | "His sentence just became a test that runs on every PR." |
| 7 | 43–50 | Slide: v1 → v2, held-out catch 0.55 → 0.73, false blocks 0.00 → 0.00; routing 30/30 vs CODEOWNERS 17/30 | "Adopted only because held-out PRs confirmed it." |
| 8 | 50–56 | Phone camera: TAAZ types OK; the reply is a GitHub link | "A text can stop a merge. It can never approve one." |
| 9 | 56–60 | Logo card: Merge Gate, repo URL, agent address | "The right engineer, on their phone, with proof." |

Capture notes: record the SSE run with `GET /api/run?pr_id=demo-1&llm=1` so the stages animate; put the
phone and the laptop in the same frame for shots 4–6 so the buzz is visibly unprompted; keep the GitHub check
tab open in advance so the red flip is one cut.
