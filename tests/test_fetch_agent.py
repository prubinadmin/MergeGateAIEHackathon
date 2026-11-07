import asyncio
import json

import pytest

from agents.merge_gate_agent import Command, format_verdict, handle, parse_command, verdict_card
from merge_gate.schema import Evidence, Owner, VerdictReport


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


def test_real_gate_on_demo_1_through_the_handler(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # demo repo + run log go to tmp
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from merge_gate.serve import State

    state = State(use_llm=False)
    state.notifier = None
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


class FakeCtx:
    """Stands in for the orchestrator's Context: 'delivers' each StepRequest to the real specialist code."""

    def __init__(self, dead=(), flaky=(), stale=()):
        self.dead, self.flaky, self.stale, self.calls, self.timeouts = set(dead), set(flaky), set(stale), [], {}

    async def send_and_receive(self, dest, req, response_type, timeout):
        from agents.team import run_step
        from merge_gate.pr import PullRequest

        self.calls.append(req.step)
        self.timeouts[req.step] = timeout
        if req.step in self.dead:
            return None, type("S", (), {"detail": "Timeout waiting for response"})()
        if req.step in self.flaky and self.calls.count(req.step) == 1:
            return response_type(step=req.step, ok=False, req_id=req.req_id, error="OSError: disk hiccup"), None
        out = run_step(req.step, PullRequest(**req.pr.model_dump()), req.source, req.timeout_s)
        rid = "an-earlier-request" if req.step in self.stale else req.req_id
        return response_type(step=req.step, ok=True, req_id=rid, **out), None


def _demo_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from merge_gate.serve import State

    state = State(use_llm=False)
    state.notifier = None
    state.demo()
    return state


ADDRS = {s: f"agent1{s}" for s in ("rules", "owners", "tests", "sandbox")}


def test_fan_out_retries_errors_but_not_timeouts(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    ctx = FakeCtx(dead={"owners"}, flaky={"rules"})
    steps, trace = asyncio.run(fan_out(ctx, ADDRS, state.prs["demo-1"], use_llm=False))
    assert ctx.calls.count("rules") == 2  # explicit error result: one retry
    assert ctx.calls.count("owners") == 1  # timeout: no retry (it would queue behind the busy specialist)
    assert "Rules agent: done" in trace[0] and "after a retry" in trace[0]
    assert trace[1] == ("OwnerRouter agent failed (Timeout waiting for response); ran that step in-process instead")
    assert "skipped" in trace[2]
    report = state.verify({"pr_id": "demo-1", "llm": False}, None, steps)
    plain = state.verify({"pr_id": "demo-1", "llm": False})
    assert report.verdict == "BLOCK" and report.evidence[0].id.startswith("R1")
    assert report.run_hash == plain.run_hash  # same gate, same answer, whichever agent did the work


def test_fan_out_ignores_a_stale_late_reply(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    ctx = FakeCtx(stale={"owners"})
    steps, trace = asyncio.run(fan_out(ctx, ADDRS, state.prs["demo-1"], use_llm=False))
    assert ctx.calls.count("owners") == 1 and "stale reply" in trace[1] and "in-process" in trace[1]
    assert [o.email for o in steps["owners"](None)]  # the in-process result, not the stale one


def test_fan_out_step_exception_does_not_abandon_siblings(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    import agents.team as team

    state = _demo_state(tmp_path, monkeypatch)
    real, done = team.run_step, []

    def run_step(step, *a):
        if step == "owners":
            raise RuntimeError("git blame exploded")
        out = real(step, *a)
        done.append(step)
        return out

    monkeypatch.setattr(team, "run_step", run_step)
    with pytest.raises(RuntimeError, match="OwnerRouter step failed: RuntimeError: git blame exploded"):
        asyncio.run(team.fan_out(FakeCtx(dead={"owners"}), ADDRS, state.prs["demo-1"], use_llm=False))
    assert done == ["rules"]  # the sibling finished; the run then failed loudly instead of a silent PASS


def test_fan_out_testwriter_exception_becomes_a_note(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    import agents.team as team

    state = _demo_state(tmp_path, monkeypatch)
    real = team.run_step
    monkeypatch.setattr(team, "run_step", lambda step, *a: (_ for _ in ()).throw(ValueError("bad"))
                        if step == "tests" else real(step, *a))
    steps, trace = asyncio.run(team.fan_out(FakeCtx(dead={"tests"}), ADDRS, state.prs["demo-1"], use_llm=True))
    assert "TestWriter/Sandbox step failed (ValueError: bad)" in trace[2]
    assert steps["testgen"](None, 60).error == "generated tests unavailable: ValueError: bad"


def test_step_timeouts_cover_the_llm_and_both_sandbox_runs():
    pytest.importorskip("uagents")
    import inspect

    from agents.team import step_timeout
    from merge_gate import llm

    assert step_timeout("tests", 60) >= inspect.signature(llm.complete).parameters["timeout_s"].default
    assert step_timeout("sandbox", 60) > 2 * 60 and step_timeout("sandbox", 90) > 2 * 90


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


def test_fan_out_with_llm_chains_testwriter_into_sandbox(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    import merge_gate.testgen as tg
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    monkeypatch.setattr(tg, "generate_tests", lambda pr: "def test_invariant_never_negative():\n"
                        "    from shop.pricing import apply_discount\n    assert apply_discount(10, 150) == 0.0\n")
    ctx = FakeCtx()
    steps, trace = asyncio.run(fan_out(ctx, {s: s for s in ("rules", "owners", "tests", "sandbox")}, state.prs["demo-1"], use_llm=True))
    assert sorted(ctx.calls) == ["owners", "rules", "sandbox", "tests"] and len(trace) == 4
    res = steps["testgen"](None, 60)
    assert res.kept_invariants == ["test_invariant_never_negative"]
    assert [e.id for e in res.evidence] == ["gate::test_invariant_never_negative"]  # PR breaks the invariant
