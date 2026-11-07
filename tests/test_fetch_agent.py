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

    def verify(self, body):
        self.calls.append(body)
        if self.fail:
            raise self.fail
        self.reports[body["pr_id"]] = _report()
        return self.reports[body["pr_id"]]


def _run(text, state):
    out = []

    async def send(t, card):
        out.append((t, card))

    asyncio.run(handle(text, state, send))
    return out


def test_verify_sends_running_then_verdict_card():
    out = _run("verify demo-1", FakeState())
    assert out[0][0].startswith("Running the gate on demo-1") and out[0][1] is None
    assert "BLOCK" in out[1][0] and out[1][1]["card_kind"] == "custom"


def test_block_only_records(monkeypatch):
    logged = []
    monkeypatch.setattr("agents.merge_gate_agent.store.log_reply", lambda *a: logged.append(a))
    s = FakeState()
    s.reports["demo-1"] = _report()
    out = _run("block demo-1 no", s)
    assert s.calls == [] and "Blocked demo-1" in out[-1][0] and "Nothing was approved" in out[-1][0]
    assert logged == [("demo-1", "asi-one-chat", "BLOCK", "BLOCK no", "block_recorded")]


def test_approve_is_refused_without_running_anything():
    s = FakeState()
    out = _run("approve demo-1", s)
    assert s.calls == [] and "never approve" in out[0][0]


def test_errors_become_a_clear_reply():
    assert "Unknown PR" in _run("verify demo-9", FakeState(fail=KeyError("demo-9")))[-1][0]
    last = _run("why demo-1", FakeState(fail=RuntimeError("git exploded")))[-1][0]
    assert "The gate failed: RuntimeError: git exploded" in last


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

    def __init__(self, dead=(), flaky=()):
        self.dead, self.flaky, self.calls = set(dead), set(flaky), []

    async def send_and_receive(self, dest, req, response_type, timeout):
        from agents.team import run_step
        from merge_gate.pr import PullRequest

        self.calls.append(req.step)
        if req.step in self.dead or (req.step in self.flaky and self.calls.count(req.step) == 1):
            return None, type("S", (), {"detail": "Timeout waiting for response"})()
        out = run_step(req.step, PullRequest(**req.pr.model_dump()), req.source, req.timeout_s)
        return response_type(step=req.step, ok=True, **out), None


def _demo_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from merge_gate.serve import State

    state = State(use_llm=False)
    state.notifier = None
    state.demo()
    return state


def test_fan_out_retries_then_falls_back_in_process_and_says_so(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    addrs = {s: f"agent1{s}" for s in ("rules", "owners", "tests", "sandbox")}
    ctx = FakeCtx(dead={"owners"}, flaky={"rules"})
    steps, trace = asyncio.run(fan_out(ctx, addrs, state.prs["demo-1"], use_llm=False))
    assert ctx.calls.count("rules") == 2 and ctx.calls.count("owners") == 2  # one retry each
    assert "Rules agent: done" in trace[0] and "after a retry" in trace[0]
    assert "OwnerRouter agent failed twice" in trace[1] and "in-process" in trace[1]
    assert "skipped" in trace[2]
    report = state.verify({"pr_id": "demo-1", "llm": False}, None, steps)
    plain = state.verify({"pr_id": "demo-1", "llm": False})
    assert report.verdict == "BLOCK" and report.evidence[0].id.startswith("R1")
    assert report.run_hash == plain.run_hash  # same gate, same answer, whichever agent did the work


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
