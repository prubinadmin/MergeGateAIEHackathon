import asyncio
import json
from collections import deque

import pytest

import agents.merge_gate_agent as agent
from agents.merge_gate_agent import Command, format_verdict, handle, parse_command, seen_before, verdict_card
from merge_gate import store
from merge_gate.schema import Evidence, Owner, VerdictReport


@pytest.fixture(autouse=True)
def _own_run_log(tmp_path, monkeypatch):
    """handle() appends to the hash-chained run log (runs/log.jsonl, cwd-relative): keep it out of the repo."""
    monkeypatch.chdir(tmp_path)


def _report(verdict="BLOCK"):
    ev = [Evidence(type="rule", id="R1_DELETED_TEST", detail="deleted test_x", file="tests/t.py", line=3),
          Evidence(type="failing_test", id="tests/t.py::test_y", detail="fails on head")] if verdict != "PASS" else []
    return VerdictReport(pr_id="demo-1", verdict=verdict, evidence=ev, summary="It deletes a test.",
                         owners=[Owner("Peter", "peter@example.com", 7, "2026-01-01")], run_hash="sha256:abc")


@pytest.mark.parametrize("text,expected", [
    ("verify demo-1", Command("verify", "demo-1")),
    ("Check DEMO-2 please", Command("verify", "demo-2")),
    ("demo-3", Command("verify", "demo-3")),
    ("list PRs", Command("list")),
    ("why demo-1", Command("why", "demo-1")),
    ("why was demo-1 blocked?", Command("why", "demo-1")),
    ("block demo-2: breaks refunds", Command("block", "demo-2", "breaks refunds")),
    ("approve demo-1", Command("approve", "demo-1")),
    ("run merge gate on demo-1", Command("verify", "demo-1")),
    ("verify PR #7 in owner/repo", Command("github")),
    ('{"action": "why", "pr_id": "demo-1"}', Command("why", "demo-1")),
    ('{"action": "block", "pr_id": "demo-2"}', Command("block", "demo-2")),
    ('{"action": "approve", "pr_id": "demo-2"}', Command("approve", "demo-2")),  # card JSON can't approve either
    ("hello", Command("help")),
    ("", Command("help")),
    # negation is never a block
    ("don't block demo-1", Command("verify", "demo-1")),
    ("don’t block demo-1", Command("verify", "demo-1")),
    ("do not stop demo-2", Command("verify", "demo-2")),
    ("not block demo-1, why does it fail?", Command("why", "demo-1")),
    # a question beats an order
    ("check demo-1 and block it if bad", Command("verify", "demo-1")),
    ("why should I block demo-1", Command("why", "demo-1")),
    ("block demo-1 in merge gate", Command("block", "demo-1", "in merge gate")),  # "gate" is the product name
    ("show me demo-2", Command("verify", "demo-2")),
    ("is demo-1 approved?", Command("verify", "demo-1")),
    ("lgtm demo-1", Command("approve", "demo-1")),
])
def test_parse_command(text, expected):
    assert parse_command(text) == expected


def test_format_verdict_has_verdict_evidence_owner_hash():
    t = format_verdict(_report())
    for part in ("BLOCK: demo-1", "R1_DELETED_TEST", "tests/t.py::test_y", "failing test", "Routed to Peter", "sha256:abc"):
        assert part in t


def test_card_is_valid_custom_card_without_an_approve_button():
    meta = verdict_card(_report())
    assert all(isinstance(v, str) for v in meta.values())  # MetadataContent.metadata is dict[str, str]
    assert meta["card_protocol_version"] == "1" and meta["card_kind"] == "custom"
    payload = json.loads(meta["card_payload"])
    blob = json.dumps(payload)
    assert payload["root"]["type"] == "section" and "R1_DELETED_TEST" in blob
    actions = {b["action"]["selection"]["action"] for b in _buttons(payload["root"])}
    assert actions == {"why", "block"}
    assert {b["action"]["selection"]["action"] for b in _buttons(json.loads(verdict_card(_report("PASS"))["card_payload"])["root"])} == {"why"}


def _buttons(el):
    if el.get("type") == "button":
        yield el
    for c in el.get("children", []):
        yield from _buttons(c)


class FakeState:
    def __init__(self, fail=None):
        self.reports, self.calls, self.fail = {}, [], fail
        self.prs = {f"demo-{i}": type("PR", (), {"pr_id": f"demo-{i}", "title": f"t{i}", "opened_by": "x"})()
                    for i in (1, 2, 3)}

    def demo(self):
        return list(self.prs.values())

    def verify(self, body, *a, **kw):
        self.calls.append((body, kw))
        if self.fail:
            raise self.fail
        self.reports[body["pr_id"]] = _report()
        return self.reports[body["pr_id"]]


def _run(text, state, **kw):
    out = []

    async def send(t, card):
        out.append((t, card))

    asyncio.run(handle(text, state, send, **kw))
    return out


SENDER = "agent1qexamplesenderaddress000000000000000000000000000000abcd"


def test_verify_sends_running_then_verdict_card():
    s = FakeState()
    out = _run("verify demo-1", s)
    assert out[0][0].startswith("Running the gate on demo-1") and out[0][1] is None
    assert "BLOCK" in out[1][0] and out[1][1]["card_kind"] == "custom"
    assert s.calls[0][1] == {"source": "asi-one"}  # chat runs are logged as asi-one, not api


def test_chat_block_is_a_recorded_request_not_an_owner_block(monkeypatch):
    logged = []
    monkeypatch.setattr("agents.merge_gate_agent.store.log_reply", lambda *a: logged.append(a))
    s = FakeState()  # no cached report: block must not run the gate
    out = _run("block demo-1 no", s, sender=SENDER)
    assert s.calls == [] and len(out) == 1
    assert out[0][0] == ("Recorded a block request from agent1qexamp...abcd. Only the code owner's verified "
                         "phone or GitHub approval changes the gate.")
    assert logged == [("demo-1", SENDER, "chat_block_request", "BLOCK no", "block_request_recorded")]


def test_block_of_unknown_pr_records_nothing(monkeypatch):
    logged = []
    monkeypatch.setattr("agents.merge_gate_agent.store.log_reply", lambda *a: logged.append(a))
    out = _run("block demo-9", FakeState(), sender=SENDER)
    assert logged == [] and "Unknown PR" in out[0][0]


def test_why_without_a_verdict_does_not_run_the_gate():
    s = FakeState()
    out = _run("why demo-2", s)
    assert s.calls == [] and out == [("No verdict yet for demo-2 — say 'verify demo-2' first.", None)]


def test_approve_is_refused_without_running_anything():
    s = FakeState()
    out = _run("approve demo-1", s)
    assert s.calls == [] and "never approve" in out[0][0]


def test_errors_become_a_clear_reply(caplog):
    s = FakeState()
    assert "Unknown PR" in _run("verify demo-9", s)[-1][0] and s.calls == []
    last = _run("verify demo-1", FakeState(fail=RuntimeError("git exploded")))[-1][0]
    assert last == "The gate failed: RuntimeError: git exploded. Try again or 'list PRs'."
    # a KeyError from inside the gate is a gate failure, not "Unknown PR"
    assert "The gate failed: KeyError" in _run("verify demo-1", FakeState(fail=KeyError("base_ref")))[-1][0]
    assert "gate failed" in caplog.text  # and it is logged


def test_gate_runs_in_background_and_chat_stays_responsive():
    """While a run is in flight, 'list PRs' and 'why' (cached) answer at once; the run's reply comes later."""
    async def scenario():
        s, out, release, jobs = FakeState(), [], asyncio.Event(), []
        s.reports["demo-2"] = _report()

        async def send(t, card):
            out.append(t)

        async def slow_run(pr_id):
            await release.wait()
            return _report(), []

        await handle("verify demo-1", s, send, run=slow_run, background=lambda c: jobs.append(asyncio.create_task(c)))
        assert out == ["Running the gate on demo-1: rules, code owners, sandbox..."]  # handler returned already
        await asyncio.wait_for(handle("list PRs", s, send), 1)
        await asyncio.wait_for(handle("why demo-2", s, send), 1)
        assert out[1].startswith("Demo PRs:") and "R1_DELETED_TEST" in out[2] and len(out) == 3  # cached report
        release.set()
        await asyncio.wait_for(jobs[0], 1)
        assert out[3].startswith("BLOCK: demo-1")

    asyncio.run(scenario())


def test_run_over_budget_is_a_timeout_failure_reply(monkeypatch):
    monkeypatch.setattr(agent, "GATE_BUDGET_S", 0.05)

    async def hung_run(pr_id):
        await asyncio.Event().wait()  # a specialist that never answers

    out = _run("verify demo-1", FakeState(), run=hung_run)
    assert out[0][0].startswith("Running the gate") and out[-1][0].startswith("The gate failed: TimeoutError")
    assert len(out) == 2  # the failure is the reply: no silence, no verdict card


def test_commands_and_traces_join_the_hash_chain():
    s = FakeState()

    async def run(pr_id):
        return _report(), ["Rules agent: done in 3 ms"]

    _run("why demo-2", s, sender=SENDER)
    _run("verify demo-1", s, run=run, sender=SENDER)
    recs = store.read()
    assert [r["kind"] for r in recs] == ["chat_command", "chat_command", "agent_trace"]
    assert recs[0]["data"] == {"sender": SENDER, "text": "why demo-2", "kind": "why", "pr_id": "demo-2"}
    assert recs[2]["data"] == {"pr_id": "demo-1", "trace": ["Rules agent: done in 3 ms"]}
    assert store.verify_chain() == (True, -1)


def test_redelivered_message_is_handled_once():
    seen = deque(maxlen=2)
    assert not seen_before(seen, "m1") and seen_before(seen, "m1")  # first delivery acts, the redelivery does not
    assert not seen_before(seen, "m2") and not seen_before(seen, "m3")
    assert not seen_before(seen, "m1")  # bounded memory: the oldest id is forgotten, not the newest


def test_per_sender_spawner_serializes_one_sender_only():
    from agents.merge_gate_agent import per_sender_spawner

    async def scenario():
        spawn, events = per_sender_spawner(), []
        gate = asyncio.Event()

        async def job(name, wait):
            events.append(f"{name} start")
            if wait:
                await gate.wait()
            events.append(f"{name} end")

        a1, a2, b = spawn("A", job("a1", True)), spawn("A", job("a2", False)), spawn("B", job("b", False))
        await asyncio.wait_for(b, 1)  # B is not held up by A's in-flight run
        assert events == ["a1 start", "b start", "b end"]  # a2 waits for a1
        gate.set()
        await asyncio.wait_for(asyncio.gather(a1, a2), 1)
        assert events[3:] == ["a1 end", "a2 start", "a2 end"]

    asyncio.run(scenario())


def _demo_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # demo repo + run log go to tmp
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from merge_gate.serve import State

    state = State(use_llm=False)
    state.notifier = None
    state.demo()
    return state


def test_real_gate_on_demo_1_through_the_handler(tmp_path, monkeypatch):
    state = _demo_state(tmp_path, monkeypatch)
    out = _run("verify demo-1", state)
    text, card = out[-1]
    assert text.startswith("BLOCK: demo-1") and "R1" in text and "run_hash sha256:" in text
    assert card is not None and "R1" in card["card_payload"]


def test_build_agents_orchestrator_plus_four_specialists():
    pytest.importorskip("uagents")
    from agents.merge_gate_agent import build_agents

    asyncio.set_event_loop(asyncio.new_event_loop())  # earlier asyncio.run() calls closed the default loop
    agents = build_agents("test-seed-not-secret-0123456789", port=8799)
    assert len({a.address for a in agents}) == 5 and all(a.address.startswith("agent1") for a in agents)
    assert [p.name for p in agents[0].protocols.values()] == ["AgentChatProtocol"]
    assert [a.name for a in agents[1:]] == ["merge-gate-rules", "merge-gate-ownerrouter", "merge-gate-testwriter", "merge-gate-sandbox"]


def test_agent_verdicts_are_logged_as_asi_one_with_fan_out_time(tmp_path, monkeypatch):
    import time

    from merge_gate import store

    state = _demo_state(tmp_path, monkeypatch)
    state.verify({"pr_id": "demo-1", "llm": False}, None, None, "asi-one", time.monotonic() - 5)
    rec = store.read(kind="verdict")[-1]["data"]
    assert rec["source"] == "asi-one" and rec["ms"] >= 5000


def test_stats_do_not_count_chat_block_requests_as_owner_actions(tmp_path, monkeypatch):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from merge_gate import store
    from merge_gate.serve import make_handler

    state = _demo_state(tmp_path, monkeypatch)
    store.log_reply("demo-1", SENDER, "chat_block_request", "BLOCK", "block_request_recorded")
    store.log_reply("demo-1", "+15550000000", "BLOCK", "BLOCK", "blocked")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        stats = json.load(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/stats"))
    finally:
        srv.shutdown()
    assert stats["owner_blocks"] == 1 and stats["owner_replies"] == 1
