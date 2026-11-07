"""The Merge Gate agent team: four specialist uAgents the ASI:One-facing orchestrator fans out to.

  Rules        merge_gate.rules.check_rules          (deleted tests, weakened asserts, ...)
  OwnerRouter  merge_gate.owners.resolve_owners      (git blame + CODEOWNERS)
  TestWriter   merge_gate.testgen.generate_tests     (Muse Spark writes tests from the spec only)
  Sandbox      merge_gate.testgen.check_generated    (runs those tests on base, then on head)

They talk with typed uAgents Models (StepRequest -> StepResult), not chat. Each call has a timeout. A specialist
handles one message at a time, so a timed-out step is never re-sent (the retry would queue behind the slow
request): it runs in-process at once and the late reply is ignored. Only an explicit error result is retried,
once. A step that falls back to in-process says so in the reply.
The verdict is never delegated: merge_gate.verify (decide(), summary, run_hash) runs in the orchestrator.

Specialists only accept requests from the orchestrator's address: a request carries a repo path and test
code to run, so anyone else asking is refused.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from uuid import uuid4

from uagents import Agent, Context, Model

from merge_gate.pr import PullRequest
from merge_gate.schema import Evidence, Owner

STEPS = ("rules", "owners", "tests", "sandbox")
NAMES = {"rules": "Rules", "owners": "OwnerRouter", "tests": "TestWriter", "sandbox": "Sandbox"}
# Seconds per call. TestWriter waits on llm.complete (180 s default timeout), so it gets more than that.
TIMEOUTS = {"rules": 30, "owners": 30, "tests": 200}


def step_timeout(step: str, timeout_s: int) -> int:
    """Sandbox runs pytest twice (base, then head), each capped at timeout_s, plus checkout time."""
    return TIMEOUTS[step] if step in TIMEOUTS else 2 * timeout_s + 30


class PRSpec(Model):
    pr_id: str
    repo_path: str
    base_ref: str
    head_ref: str
    title: str = ""
    issue_text: str = ""
    opened_by: str = ""


class StepRequest(Model):
    step: str
    pr: PRSpec
    source: str = ""  # Sandbox: the TestWriter's pytest file
    timeout_s: int = 60
    req_id: str = ""  # echoed back, so a late reply to an earlier timed-out request is never taken for this one


class StepResult(Model):
    step: str
    ok: bool
    evidence: list[dict] = []
    owners: list[dict] = []
    source: str = ""
    kept: list[str] = []
    dropped: list[str] = []
    note: str = ""  # a domain outcome, e.g. "test writer unavailable: no MUSE_API_KEY"
    error: str = ""  # the specialist itself failed
    req_id: str = ""


def run_step(step: str, pr: PullRequest, source: str = "", timeout_s: int = 60) -> dict:
    """The real work of one specialist, as StepResult fields. Also the in-process fallback."""
    if step == "rules":
        from merge_gate.rules import check_rules

        return {"evidence": [asdict(e) for e in check_rules(pr)]}
    if step == "owners":
        from merge_gate.owners import resolve_owners

        return {"owners": [asdict(o) for o in resolve_owners(pr)]}
    if step == "tests":
        from merge_gate import llm
        from merge_gate.testgen import generate_tests

        try:
            return {"source": generate_tests(pr)}
        except (llm.LLMError, SyntaxError, ValueError) as e:
            return {"note": f"test writer unavailable: {e}"}
    if step == "sandbox":
        from merge_gate.testgen import check_generated

        r = check_generated(pr, source, timeout_s)
        return {"evidence": [asdict(e) for e in r.evidence], "kept": r.kept_invariants,
                "dropped": r.dropped_invariants, "note": r.error}
    raise ValueError(f"unknown step {step!r}")


def specialist(step: str, seed: str, orchestrator_address: str) -> Agent:
    agent = Agent(name=f"merge-gate-{NAMES[step].lower()}", seed=f"{seed}/{step}")

    @agent.on_message(StepRequest, replies=StepResult)
    async def on_step(ctx: Context, sender: str, req: StepRequest) -> None:
        if sender != orchestrator_address or req.step != step:
            ctx.logger.warning(f"refused {req.step!r} request from {sender}")
            return await ctx.send(sender, StepResult(step=req.step, ok=False, req_id=req.req_id,
                                                     error="refused: not my orchestrator or not my step"))
        try:
            out = await asyncio.to_thread(run_step, step, PullRequest(**req.pr.model_dump()), req.source, req.timeout_s)
            await ctx.send(sender, StepResult(step=step, ok=True, req_id=req.req_id, **out))
        except Exception as e:  # noqa: BLE001 - the orchestrator decides what to do about it
            await ctx.send(sender, StepResult(step=step, ok=False, req_id=req.req_id,
                                              error=f"{type(e).__name__}: {str(e)[:200]}"))

    return agent


class _Team:
    """One fan-out's view of the specialists: sends StepRequests, keeps one trace line per step."""

    def __init__(self, ctx, addresses: dict[str, str], pr: PullRequest, timeout_s: int):
        self.ctx, self.addresses, self.pr, self.timeout_s = ctx, addresses, pr, timeout_s
        self.spec = PRSpec(pr_id=pr.pr_id, repo_path=pr.repo_path, base_ref=pr.base_ref, head_ref=pr.head_ref,
                           title=pr.title, issue_text=pr.issue_text, opened_by=pr.opened_by)
        self.trace: dict[str, str] = {}

    async def _ask(self, step: str, source: str) -> tuple[StepResult | None, str]:
        """One StepRequest -> (the reply, "") or (None, why there is no usable reply)."""
        rid = uuid4().hex
        try:
            resp, status = await self.ctx.send_and_receive(
                self.addresses[step],
                StepRequest(step=step, pr=self.spec, source=source, timeout_s=self.timeout_s, req_id=rid),
                StepResult, timeout=step_timeout(step, self.timeout_s))
        except Exception as e:  # noqa: BLE001 - transport failure: run the step in-process
            return None, f"{type(e).__name__}: {e}"
        if resp is None:  # timed out or undelivered
            return None, getattr(status, "detail", "") or "no reply"
        if resp.req_id != rid:
            return None, "stale reply to an earlier timed-out request"
        return resp, ""

    async def call(self, step: str, source: str = "") -> dict:
        """One step's StepResult fields. An explicit error result is retried once; anything else (timeout,
        stale or undelivered reply, transport failure) is not, because the specialist may still be busy and a
        retry would queue behind it. With no usable reply the step runs in-process."""
        err = ""
        for attempt in (1, 2):
            t0 = time.monotonic()
            resp, err = await self._ask(step, source)
            if resp is None:
                break
            if resp.ok:
                ms = int((time.monotonic() - t0) * 1000)
                self.trace[step] = f"{NAMES[step]} agent: done in {ms} ms" + (" (after a retry)" if attempt == 2 else "")
                return resp.model_dump()
            err = resp.error or "error"  # an explicit error result: retry once
        out = await asyncio.to_thread(run_step, step, self.pr, source, self.timeout_s)
        failed = "failed twice" if attempt == 2 else "failed"
        self.trace[step] = f"{NAMES[step]} agent {failed} ({err[:120]}); ran that step in-process instead"
        return out

    async def tests_then_sandbox(self, use_llm: bool) -> dict | None:
        if not use_llm:
            return None
        written = await self.call("tests")
        if not written.get("source"):
            self.trace["sandbox"] = "Sandbox agent: skipped (no generated tests)"
            return {"note": written.get("note", "")}
        return {**await self.call("sandbox", written["source"]), "source": written["source"]}


def _testgen_step(tg: dict):
    """merge_gate.verify's testgen step, replaying what TestWriter and Sandbox returned."""

    def testgen(_pr, _timeout):
        from merge_gate.testgen import TestGenResult

        return TestGenResult(source=tg.get("source", ""), kept_invariants=tg.get("kept", []),
                             dropped_invariants=tg.get("dropped", []), error=tg.get("note", ""),
                             evidence=[Evidence(**e) for e in tg.get("evidence", [])])

    return testgen


async def fan_out(ctx, addresses: dict[str, str], pr: PullRequest, use_llm: bool, timeout_s: int = 60):
    """Ask the specialists for every step (Rules and OwnerRouter in parallel with TestWriter -> Sandbox).

    Returns (steps for merge_gate.verify, one trace line per specialist).
    """
    team = _Team(ctx, addresses, pr, timeout_s)
    # return_exceptions: one step failing (even in-process) must not abandon its siblings mid-run.
    rules, owners, tg = await asyncio.gather(team.call("rules"), team.call("owners"),
                                             team.tests_then_sandbox(use_llm), return_exceptions=True)
    if isinstance(tg, BaseException):  # spec-only tests are advisory: a failure becomes a note, as in verify()
        why = f"{type(tg).__name__}: {str(tg)[:200]}"
        team.trace["tests"] = f"TestWriter/Sandbox step failed ({why[:120]}); verdict uses rules and owners only"
        tg = {"note": f"generated tests unavailable: {why}"}
    elif tg is None:
        team.trace["tests"] = "TestWriter + Sandbox agents: skipped (Muse Spark off: no MUSE_API_KEY, or MERGE_GATE_AGENT_LLM=0)"
    failed = [f"{NAMES[s]} step failed: {type(r).__name__}: {str(r)[:200]}"
              for s, r in (("rules", rules), ("owners", owners)) if isinstance(r, BaseException)]
    if failed:  # without rules or owners there is no honest verdict: fail the run loudly, never a silent PASS
        raise RuntimeError("; ".join(failed))
    steps = {
        "rules": lambda _pr: [Evidence(**e) for e in rules["evidence"]],
        "owners": lambda _pr: [Owner(**o) for o in owners["owners"]],
    }
    if tg is not None:
        steps["testgen"] = _testgen_step(tg)
    return steps, [team.trace[s] for s in STEPS if s in team.trace]
