"""Merge Gate as a Fetch.ai uAgent: run the real gate from an ASI:One chat.

  export MERGE_GATE_AGENT_SEED="<long random phrase>"
  python -m agents.merge_gate_agent

Speaks the Agent Chat Protocol (uagents_core.contrib.protocols.chat), mailbox=True so ASI:One can reach
it through Agentverse. It orchestrates four specialist uAgents (agents/team.py: Rules, OwnerRouter,
TestWriter, Sandbox) over typed messages, then decides in plain code (merge_gate.verify). Every message is acknowledged; replies are TextContent, plus an ASI:One
Interactive Card (MetadataContent) for verdicts.

Commands: "list PRs", "verify demo-1", "why demo-1", "block demo-1 <note>", "help".
Design rule: a chat can never approve a merge, and a chat BLOCK is not an owner action either: it is
recorded as a "chat_block_request" with the sender's address. Only the code owner's verified phone or
GitHub approval changes the gate. This agent never sends iMessages and never calls GitHub.
A gate run happens in a background task, so "list PRs" / "why" answer instantly while one is in flight.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from merge_gate import store
from merge_gate.notify import handle_reply, parse_reply
from merge_gate.schema import Evidence, VerdictReport

log = logging.getLogger("merge_gate.agent")
Kind = Literal["list", "verify", "why", "block", "approve", "github", "help"]

HELP = (
    "I run Merge Gate, which checks a PR and routes what it finds to the engineer who wrote the code.\n"
    "Try: \"list PRs\", \"verify demo-1\", \"why demo-1\", \"block demo-1 <reason>\".\n"
    "A chat can never approve a merge; \"block\" records a request for the code owner."
)
# Whole-run budget in seconds (fan-out + decide). Past it the user gets a TimeoutError failure reply, never
# silence; a specialist's late reply is dropped anyway (agents/team.py matches replies by req_id).
GATE_BUDGET_S = 420
_PR = re.compile(r"\bdemo-\d+\b", re.I)
_GITHUB = re.compile(r"\b[\w.-]+/[\w.-]+\b.*#\d+|#\d+.*\b[\w.-]+/[\w.-]+\b")
# Checked in this order: a question (WHY/VERIFY) beats BLOCK, so "why was demo-1 blocked" and
# "check demo-1, block it if bad" never record a block. Not "gate": the product is called Merge Gate.
_KEYWORDS: list[tuple[Kind, tuple[str, ...]]] = [
    ("why", ("why", "explain", "evidence")),
    ("verify", ("verify", "check", "run", "scan", "approved")),  # "is demo-1 approved?" is a question
    ("block", ("block", "stop")),  # not "blocked": "is demo-1 blocked?" is a question, not an order
    ("approve", ("approve", "lgtm")),  # not "merge": the product is called Merge Gate
    ("list", ("list", "prs", "demos", "show")),
]
_NEGATED_BLOCK = re.compile(r"\b(?:don'?t|do\s+not|not|never)\s+(?:block|stop)\b")


@dataclass
class Command:
    kind: Kind
    pr_id: str = ""
    note: str = ""


def _card_selection(text: str) -> Command | None:
    """An Interactive Card selection (ASI:One sends it as JSON text) -> Command; None for anything else."""
    try:
        sel = json.loads(text)
    except ValueError:
        return None
    kind = str(sel.get("action") or "").lower() if isinstance(sel, dict) else ""
    if kind not in ("list", "verify", "why", "block"):
        return None
    return Command(kind, str(sel.get("pr_id", "")).lower(), str(sel.get("note", "")))  # type: ignore[arg-type]


def _text_kind(text: str, pr_id: str) -> Kind:
    """The verb in free text, by _KEYWORDS order; no verb means "verify <pr>" when a PR is named, else help."""
    low = text.lower().replace("’", "'")
    words = set(re.findall(r"[a-z]+", low))
    if _NEGATED_BLOCK.search(low):  # "don't block demo-1" must never record a block
        words -= {"block", "stop"}
    kind = next((k for k, keys in _KEYWORDS if words & set(keys)), None)
    if kind is None or (kind == "list" and pr_id):  # "show me demo-2" acts on demo-2
        return "verify" if pr_id else "help"
    return kind


def _text_command(text: str) -> Command:
    m = _PR.search(text)
    pr_id = m.group(0).lower() if m else ""
    if not pr_id and _GITHUB.search(text):
        return Command("github")
    kind = _text_kind(text, pr_id)
    note = text[m.end():].strip(" :-.") if kind == "block" and m else ""
    return Command(kind, pr_id, note)


def parse_command(text: str) -> Command:
    """Chat text (or an Interactive Card selection, which ASI:One sends as JSON text) -> Command."""
    text = (text or "").strip()
    card = _card_selection(text)
    return card if card is not None else _text_command(text)


def _evidence_line(e: Evidence) -> str:
    where = f" ({e.file}:{e.line})" if e.file and e.line else (f" ({e.file})" if e.file else "")
    kind = "failing test" if e.type == "failing_test" else "rule"
    return f"- [{e.severity}] {kind} {e.id}: {e.detail}{where}"


def format_verdict(r: VerdictReport, trace: list[str] | tuple = ()) -> str:
    lines = [f"{r.verdict}: {r.pr_id}", r.summary]
    if r.evidence:
        lines += ["Evidence:"] + [_evidence_line(e) for e in r.evidence]
    if r.owners:
        o = r.owners[0]
        lines.append(f"Routed to {o.name} <{o.email}>, who wrote {o.lines} of the changed lines.")
    lines.append(f"run_hash {r.run_hash} (gate {r.gate_version})")
    if trace:
        lines += ["Agents:"] + [f"- {t}" for t in trace]
    if r.verdict != "PASS":
        lines.append(f'Say "why {r.pr_id}" or "block {r.pr_id}" (a request to the code owner). A chat can never approve a merge.')
    return "\n".join(lines)


def verdict_card(r: VerdictReport) -> dict[str, str]:
    """ASI:One Interactive Card (card_kind "custom") metadata. Buttons: Why / Block. No approve button, by design."""
    variant = {"BLOCK": "warning", "REVIEW": "info", "PASS": "success"}[r.verdict]
    children: list[dict] = [
        {"type": "group", "direction": "row", "gap": 8, "children": [
            {"type": "badge", "label": r.verdict, "variant": variant},
            {"type": "text", "value": f"gate {r.gate_version}", "style": "muted"},
        ]},
        {"type": "text", "value": r.summary or "(no summary)", "style": "body"},
    ]
    if r.evidence:
        children.append({"type": "heading", "value": "Evidence", "level": 3})
        children.append({"type": "list", "items": [
            {"children": [{"type": "text", "value": f"{e.id}: {e.detail}", "style": "body"}]} for e in r.evidence[:10]
        ]})
    if r.owners:
        o = r.owners[0]
        children.append({"type": "text", "value": f"Routed to {o.name} ({o.lines} changed lines are theirs)", "style": "emphasis"})
    children.append({"type": "text", "value": r.run_hash, "style": "muted"})
    buttons = [{"type": "button", "label": "Why", "action": {"selection": {"action": "why", "pr_id": r.pr_id}}}]
    if r.verdict != "PASS":
        buttons.append({"type": "button", "label": "Block", "primary": True,
                        "action": {"selection": {"action": "block", "pr_id": r.pr_id}}})
    children += [{"type": "divider"}, {"type": "group", "direction": "row", "gap": 8, "children": buttons}]
    payload = {"root": {"type": "section", "title": f"Merge Gate: {r.pr_id}", "children": children}}
    return {
        "card_protocol_version": "1",
        "requires_card_interaction": "true",
        "card_kind": "custom",
        "card_payload": json.dumps(payload),
    }


Send = Callable[[str, "dict[str, str] | None"], Awaitable[None]]
# pr_id -> (report, one line per specialist agent). Default: the whole gate in-process.
Run = Callable[[str], Awaitable["tuple[VerdictReport, list[str]]"]]


def short_addr(address: str) -> str:
    return f"{address[:12]}...{address[-4:]}" if len(address) > 20 else (address or "an unknown sender")


def seen_before(seen: deque, msg_id) -> bool:
    """True when msg_id was already handled (a redelivered message); otherwise records it and returns False."""
    if msg_id in seen:
        return True
    seen.append(msg_id)
    return False


async def _reply_failure(send: Send, e: Exception) -> None:
    log.exception("gate failed")
    await send(f"The gate failed: {type(e).__name__}: {str(e)[:200]}. Try again or 'list PRs'.", None)


_STATIC_REPLIES: dict[str, str] = {
    "help": HELP,
    "github": ("This agent runs the gate on the demo PRs (demo-1, demo-2, demo-3). To gate a real GitHub repo, "
               "install the Action in templates/merge-gate.yml; it posts the same verdict as a required check."),
    "approve": "A chat can never approve a merge. Approve on GitHub with your own login.",
}


async def _record_block_request(cmd: Command, sender: str) -> str:
    """A chat block is a request, not an owner action: never touches the verdict, never runs the gate."""
    raw = f"BLOCK {cmd.note}".strip()
    await asyncio.to_thread(store.log_reply, cmd.pr_id, sender or "asi-one-chat", "chat_block_request", raw,
                            "block_request_recorded")
    return (f"Recorded a block request from {short_addr(sender)}. Only the code owner's verified "
            "phone or GitHub approval changes the gate.")


def _why_reply(state, pr_id: str) -> str:
    report = state.reports.get(pr_id)
    if report is None:
        return f"No verdict yet for {pr_id} — say 'verify {pr_id}' first."
    return handle_reply(report, parse_reply("WHY")).text


async def _quick_reply(cmd: Command, state, sender: str) -> str | None:
    """The reply to a command that never runs the gate; None when cmd is a gate run on a known PR."""
    if cmd.kind in _STATIC_REPLIES:
        return _STATIC_REPLIES[cmd.kind]
    prs = await asyncio.to_thread(state.demo)
    if cmd.kind == "list":
        lines = [f"- {p.pr_id}: {p.title} (opened by {p.opened_by})" for p in prs]
        return "Demo PRs:\n" + "\n".join(lines) + '\nSay "verify demo-1".'
    if not cmd.pr_id:
        return f'Which PR? e.g. "{cmd.kind} demo-1". Say "list PRs" to see them.'
    if cmd.pr_id not in {p.pr_id for p in prs}:
        return f'Unknown PR "{cmd.pr_id}". Say "list PRs" to see the demo PRs.'
    if cmd.kind == "block":
        return await _record_block_request(cmd, sender)
    if cmd.kind == "why":
        return _why_reply(state, cmd.pr_id)
    return None


async def handle(text: str, state, send: Send, use_llm: bool = False, run: Run | None = None,
                 sender: str = "", background: Callable[[Awaitable[None]], None] | None = None) -> None:
    """One chat message -> one or more replies via send(text, card_metadata_or_None).

    state is a merge_gate.serve.State (the same object behind the HTTP API). A gate run sends "Running..."
    at once; the run itself (and its final reply) is handed to background(coro) when given, so the caller's
    message queue is free while it runs. Without background it is awaited here.
    """
    cmd = parse_command(text)

    async def in_process(pr_id: str):
        return await asyncio.to_thread(state.verify, {"pr_id": pr_id, "llm": use_llm}, source="asi-one"), []

    run = run or in_process
    try:
        # every command joins the hash-chained run log (merge_gate.store), so a chat trajectory is auditable
        await asyncio.to_thread(store.append, "chat_command",
                                {"sender": sender, "text": text[:500], "kind": cmd.kind, "pr_id": cmd.pr_id})
        reply = await _quick_reply(cmd, state, sender)
        if reply is not None:
            return await send(reply, None)
        await send(f"Running the gate on {cmd.pr_id}: rules, code owners, sandbox...", None)
    except Exception as e:  # noqa: BLE001 - the user gets the failure, not silence
        return await _reply_failure(send, e)

    async def job() -> None:
        try:
            report, trace = await asyncio.wait_for(run(cmd.pr_id), GATE_BUDGET_S)
            await asyncio.to_thread(store.append, "agent_trace", {"pr_id": cmd.pr_id, "trace": list(trace)})
            await send(format_verdict(report, trace), verdict_card(report))
        except Exception as e:  # noqa: BLE001
            await _reply_failure(send, e)

    if background:
        background(job())
    else:
        await job()


def per_sender_spawner() -> Callable[[str, Awaitable[None]], asyncio.Task]:
    """spawn(sender, coro): run coro as a task on the running loop. One sender's coros run one at a time, in
    order; other senders are unaffected. Tasks are kept referenced until done, so none is garbage-collected."""
    locks: dict[str, asyncio.Lock] = {}
    tasks: set[asyncio.Task] = set()

    def spawn(sender: str, coro: Awaitable[None]) -> asyncio.Task:
        async def serialized() -> None:
            async with locks.setdefault(sender, asyncio.Lock()):
                await coro

        task = asyncio.get_running_loop().create_task(serialized())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    return spawn


def build_agents(seed: str, port: int = 8001, use_llm: bool = False) -> list:
    """[orchestrator, Rules, OwnerRouter, TestWriter, Sandbox]. Only the orchestrator faces ASI:One."""
    import time
    from datetime import datetime, timezone
    from uuid import uuid4

    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement, ChatMessage, MetadataContent, TextContent, chat_protocol_spec,
    )

    from merge_gate.serve import State

    from .team import STEPS, fan_out, specialist

    state = State(use_llm)
    state.notifier = None  # this agent must never send an iMessage: any send() now fails loudly
    agent = Agent(name="merge-gate", seed=seed, port=port, mailbox=True, publish_agent_details=True)
    team = [specialist(step, seed, agent.address) for step in STEPS]
    addresses = {step: a.address for step, a in zip(STEPS, team)}
    proto = Protocol(spec=chat_protocol_spec)
    in_background = per_sender_spawner()
    seen: deque = deque(maxlen=512)  # msg_ids already handled: a redelivery is acknowledged again, acted on once

    @proto.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        if seen_before(seen, msg.msg_id):
            return
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent))

        async def send(reply: str, card: dict[str, str] | None) -> None:
            content: list = [TextContent(type="text", text=reply)]
            if card:
                content.append(MetadataContent(type="metadata", metadata=card))
            await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content))

        async def run(pr_id: str):
            t0 = time.monotonic()  # the logged ms covers the whole fan-out, not just decide()
            steps, trace = await fan_out(ctx, addresses, state.prs[pr_id], use_llm)  # handle() checked pr_id
            report = await asyncio.to_thread(state.verify, {"pr_id": pr_id, "llm": use_llm}, None, steps,
                                             "asi-one", t0)
            return report, trace

        ctx.logger.info(f"chat from {sender}: {text[:120]!r}")
        await handle(text, state, send, use_llm, run, sender, lambda coro: in_background(sender, coro))

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        pass

    agent.include(proto, publish_manifest=True)
    return [agent, *team]


def main() -> None:
    from merge_gate.llm import load_dotenv

    load_dotenv()
    seed = os.environ.get("MERGE_GATE_AGENT_SEED", "")
    if len(seed) < 16:
        sys.exit("Set MERGE_GATE_AGENT_SEED to a long random phrase (it is the agent's identity; keep it secret).")
    from uagents import Bureau

    # Like `merge_gate demo`: Muse Spark (TestWriter + Sandbox) is on when MUSE_API_KEY is set. MERGE_GATE_AGENT_LLM=0 turns it off.
    use_llm = os.environ.get("MERGE_GATE_AGENT_LLM", "1" if os.environ.get("MUSE_API_KEY") else "0") == "1"
    port = int(os.environ.get("MERGE_GATE_AGENT_PORT", "8001"))
    agents = build_agents(seed, port, use_llm)
    logging.basicConfig(level=logging.INFO)  # a no-op when uagents already configured the root logger on import
    for a in agents[1:]:
        log.info("specialist %s: %s", a.name, a.address)
    log.info("orchestrator (ASI:One-facing): %s", agents[0].address)
    log.info("Agent inspector: https://agentverse.ai/inspect/?uri=http%%3A//127.0.0.1%%3A%s&address=%s", port, agents[0].address)
    # The orchestrator gets its own server on `port` so the Agentverse inspector can find it (a multi-agent
    # Bureau answers /agent_info only with an x-uagents-address header, which the inspector doesn't send).
    # The four specialists share a Bureau on port+1; all five run in one process and event loop.
    loop = agents[0]._loop  # uagents binds every agent to this loop at construction; run everything on it
    specialists = Bureau(agents=agents[1:], port=port + 1, endpoint=[f"http://127.0.0.1:{port + 1}/submit"], loop=loop)
    loop.run_until_complete(asyncio.gather(agents[0].run_async(), specialists.run_async()))


if __name__ == "__main__":
    main()
