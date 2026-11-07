# Merge Gate: pitch, video script, Q&A

Numbers marked `[TBD]` are filled from the frozen benchmark run at 3:45. Never say a number on stage that
isn't in that run.

**Say it only once it's built.** As of 12:30 these are not in the Python code. Tick each one before
3:45, or cut the matching line:

- [ ] SubQ picks the owner and the urgency (no SubQ call exists yet; today it's git blame + recency only). Affects: routing, paging, "Why Muse Spark and SubQ" answers.
- [ ] BLOCK accepted only from the owner's verified number, plus a webhook secret token (not in `notify.py` yet). Affects: spoofing answer.
- [ ] Owner reply → test → held-out adopt/rollback (learning loop not built yet). Affects: demo beat 2:00, "How does it get better".
- [ ] Plain-LLM reviewer and CODEOWNERS baselines scored. Affects: every `[TBD]`.

## 3-minute live demo

| Time | Who | Say / do |
|---|---|---|
| 0:00 | TAAZ | "At a big company, a PR from an agent or an outside contributor lands on whoever is on rotation. They've never touched that code, so they rubber-stamp it or lose an hour. The one person who could judge it in a minute, the engineer who wrote those lines, is never asked." |
| 0:20 | TAAZ | Opens the agent PR: it changes Peter's pricing function and deletes a failing test. "The PR's own tests are green." Runs the gate. |
| 0:35 | Peter | Phone buzzes on stage. Reads the iMessage aloud: verdict, failing test, rule R1_DELETED_TEST. Replies **BLOCK**. The PR turns red on screen. |
| 1:15 | TAAZ | Two test files side by side, five seconds: the implementer's tests (green), the gate's spec-only test (red). **"Their tests passed. Ours didn't. Ours never saw theirs."** |
| 1:35 | Michael | A clean PR touches Michael's code: he gets a one-line FYI, it goes through. TAAZ replies **OK** to another PR: the reply is a GitHub link, not a merge. **"A text can stop a merge. It can never approve one."** |
| 2:00 | Peter | Texts "pricing must never round before tax." The sentence becomes a test, runs on held-out PRs, is adopted under Peter's name. **"The codebase just learned something only Peter knew."** |
| 2:30 | TAAZ | Numbers: catch rate `[TBD]` vs `[TBD]` for a plain LLM reviewer; false blocks `[TBD]` vs `[TBD]`; routing to the true owner `[TBD]` vs `[TBD]` for CODEOWNERS. **"The right engineer, on their phone, with proof."** |

Backup: if the phone or Wi-Fi fails, cut to the recorded 3:30 run and keep talking over it. Don't debug live.

## 1-minute video script

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:08 | An agent opens a PR | "AI writes PRs faster than anyone can check them, and they land on whoever's on rotation." |
| 0:08–0:20 | Gate runs: spec-only tests, sandbox, rules | "Merge Gate writes its own tests from the issue alone. It never sees the implementer's tests, so it doesn't share their blind spots." |
| 0:20–0:32 | Peter's phone: iMessage with the failing test | "Then it finds the engineer who actually wrote those lines and texts them the proof." |
| 0:32–0:42 | Peter replies BLOCK; the PR turns red | "One word stops the merge. A text can never approve one." |
| 0:42–0:52 | Peter's rule becomes an adopted test | "What the owner texts back becomes a permanent test, kept only if held-out PRs confirm it." |
| 0:52–1:00 | Numbers + name | "Merge Gate. The right engineer, on their phone, with proof." |

## Likely Q&A

**Isn't this just another AI code reviewer?**
No. No LLM decides the verdict: it's plain code over failing tests and rule hits. The LLM writes tests from the spec only, and the final call goes to the human who wrote the code.

**Why trust the generated tests?**
They're written from the issue and the public interface, never from the PR's tests or the implementer's reasoning. A failing test is shown with its output, and the owner decides. The run hash lets anyone replay it.

**What stops someone spoofing a BLOCK text?**
Only the owner's verified number can block, and the webhook checks a secret token. A spoofed BLOCK only delays a merge. Approval needs the owner's own GitHub login, so a text can never approve anything.

**What if the PR author games the tests (deletes them, loosens asserts, mocks the code)?**
That's what rules R1–R6 catch, deterministically: deleted or skipped tests, weakened asserts, the code under test mocked out, hardcoded outputs, test edits outside the issue's scope.

**What if blame points to the wrong person?**
We show the line-level blame evidence and SubQ's confidence with the page, fall back to CODEOWNERS, and report routing accuracy as measured: `[TBD]` vs `[TBD]` for CODEOWNERS.

**What if the owner left the company?**
Blame weights recency, so the person who touched the code most recently wins. Departed authors drop out once they're removed from the directory, and CODEOWNERS is the fallback.

**Doesn't this page people too much?**
SubQ scores urgency: only BLOCK-grade findings page now. Clean PRs get a one-line FYI and go through.

**Isn't running PR code dangerous?**
It runs in a throwaway copy with a timeout and a scrubbed environment, so no API keys or phone numbers reach PR code. In production it goes in a container with networking off.

**How does it get better?**
Owner replies become proposed tests and rule tweaks. A change is adopted only if the held-out catch rate rises with no new false blocks; otherwise it's rolled back. Every version and score is logged.

**Why Muse Spark and SubQ, not one model?**
Muse Spark generates: tests, summaries, reply-to-test. SubQ decides: who to page and how urgently, as calibrated probabilities over the full file history. Gemini is the implementer, a different family, so the gate doesn't share its blind spots.

**Is the demo real or simulated?**
The demo shows the real gate on a real PR (Python CLI + sandbox) and a real iMessage. The web UI's phone simulator is only a fallback if delivery fails, and we say so if we use it.

**Was any of this built before today?**
No. Every commit is timestamped today after 10:45; the README lists every component. The benchmark's author identities are synthetic and disclosed.
