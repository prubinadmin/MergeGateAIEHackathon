# Merge Gate agent for ASI:One (Fetch.ai)

`merge_gate_agent.py` is a uAgent that speaks the **Agent Chat Protocol**. In an ASI:One chat you ask it to
check a PR. It runs the **real** Merge Gate by orchestrating four specialist uAgents. It replies with the
verdict, the evidence (rule ids and failing tests), the engineer the finding is routed to, the `run_hash`,
and which agent did each step. You also get an **ASI:One Interactive Card** with **Why** and **Block**
buttons.

## Architecture

```
 ASI:One chat
     |  Agent Chat Protocol (mailbox via Agentverse)
     v
 +------------------------------+   StepRequest / StepResult (typed uAgents Models)
 | merge-gate  (orchestrator)   |--------------------------------------------------+
 |  ack, parse, reply, card     |---------------------------------+                |
 |  verify(): decide() in code  |----------------+                |                |
 +------------------------------+                |                |                |
     |  in parallel                              |                |                |
     v                                           v                v                v
  Rules                                    OwnerRouter       TestWriter  --source-->  Sandbox
  merge_gate.rules                         git blame +       Muse Spark writes        runs those tests
  (deleted tests, ...)                     CODEOWNERS        spec-only tests          on base, then head
```

- All five agents run in one process (`uagents.Bureau`). Each has its own address, derived from
  `MERGE_GATE_AGENT_SEED`. Only the orchestrator has `mailbox=True` and `publish_agent_details=True` and
  faces ASI:One. The specialists only answer the orchestrator's address. A request carries a repo path and
  test code to run, so requests from anyone else are refused.
- The orchestrator fans out: Rules and OwnerRouter run in parallel with the TestWriter -> Sandbox chain.
  Each call has a timeout (30 s; TestWriter 120 s; Sandbox 180 s) and one retry. If a specialist still
  fails, the orchestrator runs that step in-process. The reply then says so, for example: "OwnerRouter agent
  failed twice (Timeout waiting for response); ran that step in-process instead".
- The verdict is never delegated. The specialists' results go into the same `merge_gate.verify()`
  (`decide()`, summary, `run_hash`) through its `steps=` hook. A run through the agents therefore has the
  same `run_hash` as an in-process run (tested).
- TestWriter and Sandbox run when `MUSE_API_KEY` is set, the same rule `merge_gate demo` uses. Turn them off
  with `MERGE_GATE_AGENT_LLM=0`.
- SubQ routing (PR #4) lives inside `verify()` once it is merged, so it applies the same way here. OwnerRouter
  does not call it a second time.

A real run (local Bureau, a client agent chatting with the orchestrator, Muse Spark on):

```
BLOCK: demo-1
A coding agent reworked your apply_discount code. A discount over 100 percent no longer comes out as free.
Evidence:
- [block] rule R1_DELETED_TEST: PR deletes test_discount_never_negative from tests/test_pricing.py (tests/test_pricing.py:8)
- [block] failing test gate::test_invariant_over_discount_clamped: ... AssertionError: over 100 pct is free
Routed to Peter <peter@example.com>, who wrote 5 of the changed lines.
run_hash sha256:38a1a38d... (gate v1)
Agents:
- Rules agent: done in 126 ms
- OwnerRouter agent: done in 153 ms
- TestWriter agent: done in 26677 ms
- Sandbox agent: done in 659 ms
```

Design rule: **a chat can stop a merge, never approve one.** `block` only records the block in the hash-chained
run log (`runs/log.jsonl`). The agent has no approve path. It never sends an iMessage and never calls GitHub.

| You say | Agent does |
| --- | --- |
| `list PRs` | lists demo-1..3 (builds the throwaway multi-author demo repo on first use) |
| `verify demo-1` | sends "Running the gate on demo-1..." right away, then verdict + evidence + owner + run_hash + card |
| `why demo-1` | every piece of evidence + run_hash |
| `block demo-1 deletes a test` | records an owner BLOCK in the run log |
| `approve demo-1` | refuses: approval happens on GitHub with the owner's own login |
| `verify PR #7 in owner/repo` | explains that real repos are gated by the GitHub Action (`templates/merge-gate.yml`) |

Every message gets a `ChatAcknowledgement`. Errors come back as a clear message with a recovery hint, for
example an unknown PR or a gate failure. You never get silence. Card button clicks come back as JSON
selections (`{"action": "why", "pr_id": "demo-1"}`) or as prose. The agent parses both.

## Run it (you)

```bash
pip install -e ".[agent]"            # uagents==0.26.1, uagents-core==0.4.12
export MERGE_GATE_AGENT_SEED="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# keep that value: same seed = same agent address. Put it in .env (gitignored) to reuse it.
# optional, turns on TestWriter + Sandbox: export MUSE_API_KEY (or: set -a; source secrets/.env; set +a)
python -m agents.merge_gate_agent    # from the repo root
```

It prints the specialists, then the orchestrator's address and inspector link:

```
[merge-gate] specialist merge-gate-rules: agent1q...
...
[merge-gate] orchestrator (ASI:One-facing): agent1q...
[merge-gate] Agent inspector: https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8001&address=agent1q...
INFO: [merge-gate]: Manifest published successfully: AgentChatProtocol
WARNING: [merge-gate]: Agent mailbox not found: create one using the agent inspector
```

The last warning is expected until step 2 below.

On macOS with the python.org installer, you may see `SSL: CERTIFICATE_VERIFY_FAILED`. Fix it by running
`/Applications/Python 3.11/Install Certificates.command` once, or start with
`SSL_CERT_FILE=$(python -m certifi) python -m agents.merge_gate_agent`.

Optional settings:
- `MERGE_GATE_AGENT_PORT` (default 8001).
- `MERGE_GATE_AGENT_LLM=0` skips TestWriter and Sandbox. They are on by default when `MUSE_API_KEY` is set. They add about 30 s per verify.

## Register and test in ASI:One (you; needs your Agentverse login)

These steps follow https://uagents.fetch.ai/docs/examples/asi-1.

1. Keep the agent running. Sign in at https://agentverse.ai and https://asi1.ai in the same browser.
2. Open the **Agent inspector** link from the log. Use the orchestrator's link; the specialists need no setup. Click **Connect**, choose **Mailbox**, and finish the prompts.
   The log should then show `Successfully registered as mailbox agent in Agentverse` and
   `Agent details updated in Agentverse`.
3. In the inspector, click **Agent Profile**. On the Agentverse dashboard:
   - Set the name to **Merge Gate** and pick a handle (e.g. `@merge-gate`).
   - Add a description: "Checks a PR with real rules, code ownership and a test sandbox; routes findings to the engineer who wrote the code. A chat can block a merge, never approve one."
   - Paste the table above as the README so ASI:One can discover the agent.
4. Click **Chat with Agent**. ASI:One opens a chat with the agent. Try:
   - `list PRs`
   - `verify demo-1` gives a BLOCK on rule R1_DELETED_TEST, routed to Peter. A card opens. Click **Why**, then **Block**.
   - `verify demo-3` gives a PASS.
   - `approve demo-1` is refused.
5. To check discoverability, start a new ASI:One chat without the @handle and ask something like
   "Can an agent check whether a pull request deletes tests?" Agentverse search ranking can take a while
   to pick up a new agent.
6. **AIE Summit submission:** in ASI:One, open the **AIE Summit ASI:One Submission Agent** (search for it in
   ASI:One or in the Agentverse marketplace). Give it this agent's address (`agent1q...`, printed at start),
   its Agentverse profile link, and the public repo URL
   https://github.com/prubinadmin/MergeGateAIEHackathon. Follow any extra fields it asks for.

The agent must be running whenever someone chats with it. The mailbox holds messages while it is offline.

## Tests

```bash
pytest tests/test_fetch_agent.py
```

The tests cover:
- command parsing, and reply and card formatting, with the gate mocked
- error replies, and BLOCK only recording the block
- one in-process run of the real gate on demo-1, which must return BLOCK with R1
- the five-agent build
- fan-out with a flaky specialist (retry) and a dead one (in-process fallback, same `run_hash`)
- the TestWriter -> Sandbox chain

The tests that need `uagents` are skipped when it is not installed.
