"""The Merge Gate agent team: four specialist uAgents the ASI:One-facing orchestrator fans out to.

  Rules        merge_gate.rules.check_rules          (deleted tests, weakened asserts, ...)
  OwnerRouter  merge_gate.owners.resolve_owners      (git blame + CODEOWNERS)
  TestWriter   merge_gate.testgen.generate_tests     (Muse Spark writes tests from the spec only)
  Sandbox      merge_gate.testgen.check_generated    (runs those tests on base, then on head)

They talk with typed uAgents Models (StepRequest -> StepResult), not chat. The orchestrator gives each call
a timeout and one retry; if a specialist still fails, it runs that step in-process and says so in the reply.
The verdict is never delegated: merge_gate.verify (decide(), summary, run_hash) runs in the orchestrator.

Specialists only accept requests from the orchestrator's address: a request carries a repo path and test
code to run, so anyone else asking is refused.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

from uagents import Agent, Context, Model

from merge_gate.pr import PullRequest
from merge_gate.schema import Evidence, Owner

STEPS = ("rules", "owners", "tests", "sandbox")
NAMES = {"rules": "Rules", "owners": "OwnerRouter", "tests": "TestWriter", "sandbox": "Sandbox"}
# Seconds per call. TestWriter waits on the LLM; Sandbox runs pytest twice (base and head).
TIMEOUTS = {"rules": 30, "owners": 30, "tests": 120, "sandbox": 180}


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
            return await ctx.send(sender, StepResult(step=req.step, ok=False, error="refused: not my orchestrator or not my step"))
        try:
            out = await asyncio.to_thread(run_step, step, PullRequest(**req.pr.model_dump()), req.source, req.timeout_s)
            await ctx.send(sender, StepResult(step=step, ok=True, **out))
        except Exception as e:  # noqa: BLE001 - the orchestrator decides what to do about it
            await ctx.send(sender, StepResult(step=step, ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"))

    return agent


async def fan_out(ctx, addresses: dict[str, str], pr: PullRequest, use_llm: bool, timeout_s: int = 60):
    """Ask the specialists for every step (Rules and OwnerRouter in parallel with TestWriter -> Sandbox).

    Returns (steps for merge_gate.verify, one trace line per specialist).
    """
    spec = PRSpec(pr_id=pr.pr_id, repo_path=pr.repo_path, base_ref=pr.base_ref, head_ref=pr.head_ref,
                  title=pr.title, issue_text=pr.issue_text, opened_by=pr.opened_by)
    trace: dict[str, str] = {}

    async def call(step: str, source: str = "") -> dict:
        err = ""
        for attempt in (1, 2):
            t0 = time.monotonic()
            try:
                resp, status = await ctx.send_and_receive(
                    addresses[step], StepRequest(step=step, pr=spec, source=source, timeout_s=timeout_s),
                    StepResult, timeout=TIMEOUTS[step])
                err = (resp.error if resp is not None else status.detail) or "no reply"
                if resp is not None and resp.ok:
                    ms = int((time.monotonic() - t0) * 1000)
                    trace[step] = f"{NAMES[step]} agent: done in {ms} ms" + (" (after a retry)" if attempt == 2 else "")
                    return resp.model_dump()
            except Exception as e:  # noqa: BLE001 - transport failure counts as a failed attempt
                err = f"{type(e).__name__}: {e}"
        out = await asyncio.to_thread(run_step, step, pr, source, timeout_s)
        trace[step] = f"{NAMES[step]} agent failed twice ({err[:120]}); ran that step in-process instead"
        return out

    async def tests_then_sandbox() -> dict | None:
        if not use_llm:
            return None
        written = await call("tests")
        if not written.get("source"):
            trace["sandbox"] = "Sandbox agent: skipped (no generated tests)"
            return {"note": written.get("note", "")}
        return {**await call("sandbox", written["source"]), "source": written["source"]}

    rules, owners, tg = await asyncio.gather(call("rules"), call("owners"), tests_then_sandbox())
    if tg is None:
        trace["tests"] = "TestWriter + Sandbox agents: skipped (Muse Spark off: no MUSE_API_KEY, or MERGE_GATE_AGENT_LLM=0)"

    def testgen(_pr, _timeout):
        from merge_gate.testgen import TestGenResult

        return TestGenResult(source=tg.get("source", ""), kept_invariants=tg.get("kept", []),
                             dropped_invariants=tg.get("dropped", []), error=tg.get("note", ""),
                             evidence=[Evidence(**e) for e in tg.get("evidence", [])])

    steps = {
        "rules": lambda _pr: [Evidence(**e) for e in rules["evidence"]],
        "owners": lambda _pr: [Owner(**o) for o in owners["owners"]],
    }
    if tg is not None:
        steps["testgen"] = testgen
    return steps, [trace[s] for s in STEPS if s in trace]
