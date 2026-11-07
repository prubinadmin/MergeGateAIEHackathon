# Merge Gate: pitch, video script, Q&A

Every number here is copied from the frozen run in [`benchmark/RESULTS.md`](../benchmark/RESULTS.md)
(2026-11-07, 30 cases: 22 bad, 8 clean; 15 held-out: 11 bad, 4 clean). Never say a number on stage that
isn't in that file. Judges can read it.

## The honest frame (say it before they ask)

On our own 30-case benchmark, a plain LLM that reads the diff and answers BLOCK/PASS catches **22/22** bad
PRs with **1/8** false blocks. Merge Gate v2 catches **17/22** with **2/8** false blocks (held-out: 8/11, 0/4).
The planted problems are visible in short diffs, and the baseline was told which categories to look for.
We are not claiming a higher catch rate. We are claiming five things the diff reader cannot do:

1. **Independence.** The gate's tests come from the spec and the public interface. The PR's diff, tests and
   description never reach the test writer, so a PR cannot prompt its own reviewer. The LLM baseline reads
   the diff; a diff can say "this is fine".
2. **Evidence, not opinion.** Every BLOCK carries a rule id or a failing test with output. The baseline
   returns one word.
3. **Routing to the author.** Line-level blame routed **30/30**; the repo's own CODEOWNERS routed **17/30**
   (held-out: 15/15 vs 7/15).
4. **Learning from the author.** The owner's text becomes a test under their name. Gate v1 → v2 was adopted
   only because held-out catch rose **0.55 → 0.73** with held-out false blocks staying at **0.00**.
5. **Reproducibility and rollback.** Hash-chained log, cached model responses (re-runs are exact replays),
   and `rollback` re-verifies what already merged and opens a revert PR.

Also say: **Merge Gate runs on its own repo as a GitHub check. It blocked or sent to review several of our
own PRs today. We fixed the code, not the rules.**

## Built vs claimed (re-checked against `claude/integration`, 15:00)

- [x] SubQ Snap 1.1 picks the owner and the urgency (`merge_gate/subq.py`); eligible owners only, confidence ≥ 0.80, urgency never below the plain-code floor.
- [x] BLOCK accepted only from the owner's verified phone, through a webhook that checks a secret token and fails closed without one (`merge_gate/imessage.py`, `POST /api/sendblue?token=...`).
- [x] Held-out adopt/rollback learning (`merge_gate/learn.py`): v1 → v2 adopted in round 2, 0.55/0.00 → 0.73/0.00 held-out.
- [x] Owner free-text reply → test, end to end (`merge_gate/owner_tests.py`, TEACH / FORGET); teaching only via the verified phone.
- [x] Plain-LLM reviewer and CODEOWNERS baselines scored (`merge_gate/baselines.py`, `benchmark/RESULTS.md`).
- [x] Agentic auto-paging: `serve` texts the owner on every verdict without a click (`MERGE_GATE_AUTO_PAGE`).
- [x] Replies worded by Muse Spark from the verdict's facts; a regex refuses approved / merged / LGTM / ship it.
- [x] Rollback command and workflow (`merge_gate/rollback.py`, `templates/merge-gate-rollback.yml`).
- [x] Hash-chained run log mirrored to MongoDB Atlas (`merge_gate/store.py`).
- [x] Fetch.ai: 5 uAgents, orchestrator on ASI:One with Chat Protocol + Interactive card
      (`agent1qdzxevq4yxvlevawy50n0syq39snynxc00l0xsjuyvlhy3v2jhyecymc4sj`). Pending: Agentverse mailbox connect on the presenter laptop (manual step in `agents/README.md`).
- [x] Gate enforced on this repo's own PRs (`.github/workflows/merge-gate.yml`).

## 3-minute live demo (agentic flow)

| Time | Who | Say / do |
|---|---|---|
| 0:00 | TAAZ | "At a big company, a PR from an agent lands on whoever is on rotation. They've never touched that code, so they rubber-stamp it or lose an hour. The one person who could judge it in a minute, the engineer who wrote those lines, is never asked." |
| 0:20 | TAAZ | Opens the agent PR on screen: it changes Peter's pricing function and deletes a failing test. "The PR's own tests are green." Does **nothing else**. The gate is already running: War Room shows rules, blame, SubQ, Muse Spark writing tests, the sandbox. |
| 0:40 | Peter | **Phone buzzes by itself.** Nobody clicked send. Reads the iMessage aloud: verdict, failing spec-only test, rule R1_DELETED_TEST, "wrote 5 of the changed lines". Replies **BLOCK**. The GitHub check turns red on screen. |
| 1:10 | TAAZ | Two test files side by side, five seconds: the implementer's tests (green), the gate's spec-only test (red). **"Their tests passed. Ours didn't. Ours never saw theirs. A PR cannot prompt its own reviewer."** |
| 1:30 | Michael | A clean PR touches Michael's code: his phone gets a one-line FYI, it goes through. TAAZ replies **OK** to another PR: the reply is a GitHub link, not a merge. **"A text can stop a merge. It can never approve one."** |
| 1:50 | Peter | Texts, in his own words: "pricing must never round before tax." Screen: Muse Spark turns the sentence into one pytest test, it passes on base, it is stored under Peter's name, it runs on the next PR. **"The codebase just learned something only Peter knew. And only Peter's phone could teach it."** |
| 2:20 | TAAZ | Learning slide: gate v1 → v2, held-out catch 0.55 → 0.73, held-out false blocks 0.00 → 0.00. **"Adopted only because held-out confirmed. Round 1 and round 3 proposed nothing, so nothing changed."** |
| 2:35 | TAAZ | Numbers slide, honest: "A plain LLM reading the diff catches 22 of 22 on our benchmark, we catch 17. We route 30 of 30, CODEOWNERS 17 of 30. Our edge is not catch rate. It's that nobody can prompt us, we page the author, we learn from the author, and every run replays." |
| 2:50 | TAAZ | "Merge Gate blocked our own PRs today. We fixed the code. **The right engineer, on their phone, with proof.**" |

Backup: if the phone or Wi-Fi fails, the public site replays the recorded run (https://dist-phi-five-99.vercel.app).
Keep talking over it and say it is a replay. Don't debug live.

## 1-minute video script

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:08 | An agent opens a PR | "AI writes PRs faster than anyone can check them, and they land on whoever's on rotation." |
| 0:08–0:20 | War Room: rules, blame, SubQ, Muse Spark tests, sandbox | "Merge Gate writes its own tests from the issue alone. It never sees the PR's tests or its diff, so a PR can't talk its way past it." |
| 0:20–0:32 | Peter's phone lights up on its own: iMessage with the failing test | "Then it finds the engineer who wrote those lines and texts them the proof. Nobody clicks send." |
| 0:32–0:42 | Peter replies BLOCK; the GitHub check turns red | "One word stops the merge. A text can never approve one." |
| 0:42–0:52 | Peter texts a rule; it becomes a test under his name; held-out 0.55 → 0.73 | "What the owner texts back becomes a permanent test, kept only if held-out PRs confirm it." |
| 0:52–1:00 | 30/30 vs 17/30 routing; the name | "Merge Gate. The right engineer, on their phone, with proof." |

## Likely Q&A

**Isn't this just another AI code reviewer?**
No. No LLM decides the verdict: it's plain code over failing tests and rule hits. The LLM writes tests from
the spec only, and the final call goes to the human who wrote the code.

**Why trust the generated tests?**
They're written from the issue and the public interface, never from the PR's tests, diff or description. A
failing test is shown with its output, and the owner decides. Model responses are cached by request hash,
so a re-run is an exact replay, and the run hash lets anyone check it.

**What stops someone spoofing a BLOCK text?**
Only the owner's verified phone can act, the webhook checks a secret token, and it fails closed if no secret
is configured. A spoofed BLOCK only delays a merge. Approval needs the owner's own GitHub login, so a text
can never approve anything. Teaching a rule is accepted only from that same verified phone, never from the
web UI.

**What if the PR author games the tests (deletes them, loosens asserts, mocks the code)?**
Rules R1–R6 catch that deterministically: deleted or skipped tests, weakened asserts, the code under test
mocked out, hardcoded outputs, test edits outside the issue's scope. R7–R9 catch dangerous calls, backdoor
literals and unparseable files. R10–R14 are quality rules and only ask for review.

**What if blame points to the wrong person?**
SubQ picks among eligible blame candidates only, never the PR's opener, and only at confidence ≥ 0.80;
otherwise the blame ranking stands. We show the line-level evidence with the page. Measured: 30/30 vs
17/30 for the repo's CODEOWNERS. The label is defined as the author of most changed base lines, so 30/30
shows the resolver does what it says; it doesn't measure taste.

**What if the owner left the company?**
Blame weights recency, so the most recent toucher wins. Departed authors drop out once they're removed from
`OWNER_PHONES`, and CODEOWNERS is the fallback.

**Doesn't this page people too much?**
SubQ scores urgency, with a floor set in plain code: anything but PASS pages. Clean PRs get a one-line FYI.

**Isn't running PR code dangerous?**
It runs in a throwaway `git archive` copy with a timeout and a scrubbed environment, so no API keys or phone
numbers reach PR code. Owner-taught tests run the same way, and only if their sha256 still matches the one
recorded when they were validated. In production it goes in a container with networking off.

**How does it get better?**
Owner replies become tests under the owner's name, and misses on the train split become proposed knob
changes. A change is adopted only if held-out catch doesn't drop, held-out false blocks don't rise, and one
of them improves. v1 → v2: 0.55 → 0.73 catch, 0.00 → 0.00 false blocks. Every version is in `gate_versions/`.

**Why Muse Spark and SubQ, not one model?**
Muse Spark generates: tests, summaries, reply wording, sentence-to-test. SubQ decides: who to page and how
urgently, as calibrated probabilities with a confidence we can threshold. Neither decides the verdict.

**Is the demo real or simulated?**
Real: Muse Spark, SubQ, Sendblue iMessages, MongoDB Atlas, the GitHub check, the Agentverse agents.
Simulated: the commit author identities in the demo and benchmark repos (commit metadata only, disclosed).
Recorded: the public site replays a real run. If we fall back to the replay on stage, we say so.

**Was any of this built before today?**
No. Every commit is timestamped today after 10:45; the README lists every component with its file.

## The benchmark question, five savage-but-true answers

Expect: "Your own table says the plain LLM beats you. Why does Merge Gate exist?"

1. **"Yes. 22 of 22 versus our 17. We wrote that line ourselves and put it in the repo.** Now ask the diff
   reader to show you the failing test. It can't. It returned one word. We return the test, the output and
   the rule id, and a hash you can replay."

2. **"The diff reader was told what to look for and read a diff we planted the bug in.** Our tests never saw
   the diff. The day a coding agent learns to write 'all tests pass, no security impact' in the PR body, the
   diff reader is reading the attacker's prompt. Ours isn't reading anything the attacker wrote."

3. **"Catch rate isn't the product. Routing is.** CODEOWNERS sent 13 of 30 PRs to the wrong person on a
   repo where 4 of 10 files were written by someone outside the folder owner. We sent 30 of 30 to the person
   whose lines changed. The diff reader has no idea who to tell."

4. **"We got better during the hackathon and we can prove it wasn't luck.** v1 to v2: held-out catch 0.55 to
   0.73, held-out false blocks stayed at zero, adopted because held-out confirmed. Rounds 1 and 3 proposed
   nothing and we changed nothing. The diff reader has no learning loop; it has a prompt."

5. **"Thirty cases, written by us. One case moves a held-out rate nine points.** v2 costs two false blocks on
   train that held-out couldn't see, and we wrote that down too. Anyone who shows you a hackathon benchmark
   without a line like that is selling you something."
