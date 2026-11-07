# Merge Gate Reviewer

> **Built by Michael, TAAZ and Peter (with Claude writing code) at the AIE Code Summit 2026 Hackathon, Shack15 SF.**  
> **Core design rule:** *Easy to stop, hard to approve.*

Merge Gate checks every external or AI-written PR in a large codebase. It routes what it finds to the engineer who actually wrote the code being changed, as an iMessage on their phone with evidence they can act on in 30 seconds.

---

## 1. Why Merge Gate?

- **The Problem:** An external PR arrives from an outside contributor, another team, or a coding agent. The company assigns it to whoever is on rotation. That engineer has never worked on this code, so they either rubber-stamp it or spend an hour learning it.
- **Who could judge it in minutes:** The engineer who wrote those lines. They are rarely asked, because `CODEOWNERS` maps folders to teams, not lines to people.
- **Where they are:** Not watching GitHub notifications. A PR that breaks their code should reach their phone, the way an on-call page does.

| Feature | Typical AI reviewer | CODEOWNERS / auto-assign | Merge Gate |
| --- | --- | --- | --- |
| **Who decides** | An LLM reading the diff | A team owning the folder | The engineer who wrote the changed lines |
| **What they receive** | A comment wall on GitHub | A review request | An iMessage with a reproducing test or the rule that fired |
| **Evidence** | LLM opinion | None | Failing test, run hash, rule ID |
| **Where it reaches them** | GitHub notifications | GitHub notifications | Their phone (SMS/iMessage) |

---

## 2. Design Rule: Easy to Stop, Hard to Approve

If the owner replies **`BLOCK`** from their phone, the PR is blocked at once in CI.  
A text message alone can never approve or merge; approval requires GitHub login with the owner's own credentials.

Owner phone replies:
- `BLOCK`: Blocks the PR immediately.
- `WHY`: Returns the reproducing failing test case and output traceback.
- `OK`: Does not merge. Replies with authenticated GitHub review link.
- `FALSE ALARM`: Logged as feedback into the Secondary Learning Track.

---

## 3. How It Works

1. **PR opened.** A GitHub webhook or the CLI starts a run.
2. **Independent tests.** Tests are written strictly from the issue text and public interface only. The test runner never sees the implementer's tests or reasoning.
3. **Sandboxed run.** Tests run in an isolated subprocess with timeouts and pinned dependencies. Every input and output is hashed (`run_hash`) so runs can be replayed.
4. **Anti-gaming checks.** Deterministic rules flag:
   - `AG-01: DELETED_TEST` — Deleted tests or test suites
   - `AG-02: SKIPPED_OR_DISABLED_TEST` — Tests marked `.skip`, `xit`, or `@pytest.mark.skip`
   - `AG-03: WEAKENED_ASSERT` — Strict asserts replaced with truthiness (`toBe` -> `toBeDefined`)
   - `AG-04: MOCKED_CODE_UNDER_TEST` — Mocking or spying on the target unit under test
   - `AG-05: HARDCODED_OUTPUT` — Literal constant returns injected to fake tests
   - `AG-06: SCOPE_CREEP_TEST_MUTATION` — Test changes outside issue scope
5. **Deterministic verdict.** Deterministic code returns `BLOCK`, `REVIEW`, or `PASS`. (No LLM decides the verdict).
6. **Find the owner.** `git blame` and `git log -L` weighted by recency decay ($e^{-\lambda \Delta t}$) and line count. `CODEOWNERS` is only a fallback.
7. **iMessage the owner.** 2–3 line summary with verdict, failing test or rule ID, and evidence link.
8. **Learning Track (vN+1).** Owner feedback trains Gate version $N+1$. Adopted only if catch rate rises and false blocks do not rise on held-out PRs; otherwise automatically rolled back.

---

## 4. Fixed Owner Interface Contract

```json
{
  "pr_id": "PR-412",
  "verdict": "BLOCK",
  "evidence": [
    {
      "type": "failing_test",
      "id": "IT-102",
      "detail": "test_enterprise_threshold_boundary failed: Expected volume discount 750000, got 0."
    }
  ],
  "owners": [
    {
      "name": "Peter",
      "lines": 42,
      "last_touched": "2026-03-14"
    }
  ],
  "summary": "PR #412 by copilot-agent[bot] broke your calculateTieredPrice(). The PR's own tests passed, but independent test IT-102 failed. Reply BLOCK to stop, or WHY for traceback.",
  "run_hash": "8f3b14a29c104e..."
}
```

---

## 5. CLI Usage & Starter Code

Run directly via the included Python script:

```bash
python scripts/merge_gate.py \
  --pr 412 \
  --diff pr_412.diff \
  --issue "Issue #1892: Tiered billing discounts"
```

Or run the interactive React & TypeScript application:

```bash
npm install
npm run dev
```
