"""agents/team.py: the specialist fan-out (retry, timeout, stale-reply and in-process fallback paths).

FakeCtx is the transport: it "delivers" each StepRequest to the real specialist code (run_step), so the
tests drive the real fan_out/run_step and only fake what a specialist would do over the wire. Failures are
injected at the merge_gate boundaries (resolve_owners, generate_tests), never by mocking agents.team itself.
"""

import asyncio

import pytest


class FakeCtx:
    """Stands in for the orchestrator's Context: 'delivers' each StepRequest to the real specialist code."""

    def __init__(self, dead=(), flaky=(), stale=()):
        self.dead, self.flaky, self.stale = set(dead), set(flaky), set(stale)
        self.calls, self.done, self.timeouts = [], [], {}

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
        self.done.append(req.step)
        rid = "an-earlier-request" if req.step in self.stale else req.req_id
        return response_type(step=req.step, ok=True, req_id=rid, **out), None


def _demo_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # demo repo + run log go to tmp
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from merge_gate.serve import State

    state = State(use_llm=False)
    state.notifier = None
    state.demo()
    return state


def _raiser(exc):
    def raise_it(*a, **kw):
        raise exc

    return raise_it


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
    import subprocess

    import merge_gate.pr as prmod
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    # OwnerRouter times out, so the step runs in-process, where git blame blows up (fail the git boundary, not our code)
    real_run = subprocess.run

    def git_blame_explodes(args, *a, **kw):
        if "blame" in args:
            raise RuntimeError("git blame exploded")
        return real_run(args, *a, **kw)

    monkeypatch.setattr(prmod.subprocess, "run", git_blame_explodes)
    ctx = FakeCtx(dead={"owners"})
    with pytest.raises(RuntimeError, match="OwnerRouter step failed: RuntimeError: git blame exploded"):
        asyncio.run(fan_out(ctx, ADDRS, state.prs["demo-1"], use_llm=False))
    assert ctx.done == ["rules"]  # the sibling finished; the run then failed loudly instead of a silent PASS


def test_fan_out_testwriter_exception_becomes_a_note(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    import merge_gate.llm as llm
    from agents.team import fan_out

    state = _demo_state(tmp_path, monkeypatch)
    # TestWriter times out, so it runs in-process; the model call itself blows up with a non-LLMError
    monkeypatch.setattr(llm, "complete", _raiser(RuntimeError("bad")))
    steps, trace = asyncio.run(fan_out(FakeCtx(dead={"tests"}), ADDRS, state.prs["demo-1"], use_llm=True))
    assert "TestWriter/Sandbox step failed (RuntimeError: bad)" in trace[2]
    assert steps["testgen"](None, 60).error == "generated tests unavailable: RuntimeError: bad"


def test_step_timeouts_cover_the_llm_and_both_sandbox_runs():
    import inspect

    from agents.team import step_timeout
    from merge_gate import llm

    assert step_timeout("tests", 60) >= inspect.signature(llm.complete).parameters["timeout_s"].default
    assert step_timeout("sandbox", 60) > 2 * 60 and step_timeout("sandbox", 90) > 2 * 90


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
