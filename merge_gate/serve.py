"""`python -m merge_gate serve`: HTTP API over the real gate, for the web UI and the iMessage webhook.

  GET  /api/health
  GET  /api/demo                      demo PRs (builds the demo repo once, under runs/demo; or, with
                                      MERGE_GATE_DEMO_GITHUB=owner/name, that repo's open PRs, and each
                                      verdict is published back to the PR)
  POST /api/github   {"query": "vllm" | "owner/repo" | "owner/repo#N" | PR URL} -> clones the live PR, returns it as a gate PR (pr_id gh:owner/repo#N) for /api/run
  POST /api/verify   {"pr_id": "demo-1"}                 -> verdict report (real rules, blame, sandbox, Muse)
       or          {"repo_path", "base_ref", "head_ref", "issue_text", "title", "opened_by", "pr_id"}
  POST /api/message  {"pr_id": "demo-1", "pr_url": ""}  -> {"to": owner, "text": iMessage text}
  POST /api/reply    {"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}}
                                                         -> {"command", "action", "text", "github_blocked"}
       a rule to teach, or FORGET <test> -> 403: only via the verified-phone webhook below
  POST /api/message  {..., "send": true, "github": {...}}  -> also sends the iMessage via Sendblue (or console)
  POST /api/sendblue?token=SECRET     Sendblue inbound webhook; only the PR owner's verified phone can act
  GET  /api/log                       run log records + whether the hash chain verifies
  GET  /api/run?pr_id=demo-1&llm=1     Server-Sent Events: one event per real stage as it starts/finishes, then the report
  GET  /api/stats                     counters for the header bar, from the run log

Agentic paging: every verdict from /api/verify or /api/run texts the code owner on its own (the "page" SSE stage,
start/done, carries what was sent); MERGE_GATE_AUTO_PAGE=0 turns it off. Lazy verifies behind /api/message,
/api/reply and /api/sendblue never text anyone; only an explicit {"send": true} on /api/message does.

Stdlib only. CORS is open so the Vite dev server can call it. Bind to localhost.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import imessage, store
from .llm import load_dotenv
from .demo import build_demo_repo, demo_prs
from .notify import Action, format_message, handle_reply, parse_reply
from .pr import PullRequest
from .schema import VerdictReport

DEMO_ROOT = os.path.join("runs", "demo")
logger = logging.getLogger("merge_gate.serve")


class State:
    def __init__(self, use_llm: bool, use_subq: bool = False) -> None:
        self.use_llm = use_llm
        self.use_subq = use_subq  # SubQ routing; on only when SUBQ_API_KEY is set (decided by the CLI)
        self.reports: dict[str, VerdictReport] = {}
        self.prs: dict[str, PullRequest] = {}
        self.lock = threading.Lock()
        self._demo_ready = False
        load_dotenv()
        self.notifier = imessage.notifier_from_env()
        # phone_key -> the PR that number was last messaged about (so a bare "BLOCK" reply has a target)
        self.threads: dict[str, dict] = {}
        # agentic paging: every verdict texts the code owner on its own (MERGE_GATE_AUTO_PAGE=0 turns it off)
        self.auto_page = os.environ.get("MERGE_GATE_AUTO_PAGE", "1") != "0"
        # (pr_id, run_hash) -> None, insertion-ordered: never re-page an identical result; the oldest fall out past 500
        self._paged: dict[tuple[str, str], None] = {}
        # MERGE_GATE_DEMO_GITHUB=owner/name: demo cases are that repo's open PRs, and verdicts go back to them.
        self.github_repo = os.environ.get("MERGE_GATE_DEMO_GITHUB", "").strip()
        self.github_prs: dict[str, object] = {}  # pr_id -> demo_github.GithubPr
        self.published: dict[str, str] = {}  # pr_id -> what was posted to GitHub (or why not)

    def demo(self, refresh: bool = False) -> list[PullRequest]:
        if self.github_repo:
            return self._github_demo(refresh)
        with self.lock:
            if not self._demo_ready:
                repo = build_demo_repo(DEMO_ROOT)
                for pr in demo_prs(repo):
                    self.prs[pr.pr_id] = pr
                self._demo_ready = True
        return [p for k, p in self.prs.items() if k.startswith("demo-")]

    def _github_demo(self, refresh: bool) -> list[PullRequest]:
        from . import demo_github

        with self.lock:
            if refresh or not self._demo_ready:
                path = demo_github.sync(self.github_repo)
                found = demo_github.open_prs(self.github_repo, path)
                self.github_prs = {g.pr.pr_id: g for g in found}
                for k in [k for k in self.prs if k.startswith("demo-")]:
                    del self.prs[k]
                for g in found:
                    self.prs[g.pr.pr_id] = g.pr
                self._demo_ready = True
            return [self.github_prs[k].pr for k in self.github_prs]

    def publish(self, report: VerdictReport) -> None:
        """Post the verdict to the real GitHub PR (merge-gate status + comment), when this case is one."""
        g = self.github_prs.get(report.pr_id)
        if not g:
            return
        from . import github

        try:
            github.publish(report, self.github_repo, g.number, sha=g.sha)
            note = f"posted {github.STATE_FOR[report.verdict]} to {g.url}"
        except github.GitHubError as e:
            note = f"not posted to GitHub: {e}"
        self.published[report.pr_id] = note
        store.append("github_publish", {"pr_id": report.pr_id, "note": note})

    def _pr_from_body(self, body: dict) -> PullRequest:
        """A custom PR from the request (repo_path + head_ref), or one of the demo PRs by pr_id."""
        if "repo_path" in body:
            return PullRequest(
                pr_id=body.get("pr_id") or "custom",
                repo_path=body["repo_path"],
                base_ref=body.get("base_ref", "main"),
                head_ref=body["head_ref"],
                issue_text=body.get("issue_text", ""),
                title=body.get("title", ""),
                opened_by=body.get("opened_by", ""),
            )
        self.demo()
        pr = self.prs.get(body.get("pr_id", ""))
        if pr is None:
            raise KeyError(f"unknown pr_id {body.get('pr_id')!r}")
        return pr

    def _auto_page(self, report: VerdictReport, body: dict, on_stage, auto_page: bool | None) -> None:
        """Agentic paging after a verdict: text the owner on its own; on_stage sees page start/done."""
        if not ((self.auto_page if auto_page is None else auto_page) and report.owners):
            return
        if on_stage:
            on_stage("page", "start", {})
        try:
            out = self.page(report, body.get("pr_url", ""), body.get("github") or {}, dedupe=True)
        except Exception as e:  # noqa: BLE001 - a failed text must never fail the verdict
            out = {"error": f"{type(e).__name__}: {e}"}
        if on_stage:
            on_stage("page", "done", out)

    def verify(self, body: dict, on_stage=None, steps=None, source: str = "api",
               started: float | None = None, auto_page: bool | None = None) -> VerdictReport:
        """started: time.monotonic() when the run began, if earlier work (the agent fan-out) counts toward ms.
        auto_page: override the server default for this run (report() passes False: a lazy verify never texts)."""
        from .verify import verify

        pr = self._pr_from_body(body)
        use_llm = body.get("llm", self.use_llm)
        use_subq = self.use_subq and body.get("subq", True)  # a request can turn SubQ off, never on without the server
        t0 = started if started is not None else time.monotonic()
        report = verify(pr, use_llm=bool(use_llm), on_stage=on_stage, use_subq=bool(use_subq), steps=steps)
        store.log_report(report, source=source, ms=int((time.monotonic() - t0) * 1000), llm=bool(use_llm))
        with self.lock:
            self.prs[pr.pr_id] = pr
            self.reports[pr.pr_id] = report
        self.publish(report)
        g = self.github_prs.get(pr.pr_id)
        if g:  # a real demo-repo PR: the owner's BLOCK reply must reach that PR's check
            body = {**body, "pr_url": body.get("pr_url") or g.url,
                    "github": body.get("github") or {"repo": self.github_repo, "number": g.number}}
        self._auto_page(report, body, on_stage, auto_page)
        return report

    def teach(self, report: VerdictReport, sentence: str) -> str:
        """The owner's sentence -> a stored test (owner_tests.rule_to_test); returns the reply text."""
        from .owner_tests import outcome_text, rule_to_test

        pr = self.prs[report.pr_id]
        t = rule_to_test(pr, report.owners[0].email if report.owners else "owner", sentence)
        if t.accepted:
            with self.lock:
                self.reports.pop(report.pr_id, None)  # next look at this PR includes the new evidence
        return outcome_text(t)

    def forget(self, report: VerdictReport, name: str) -> str:
        """FORGET <test name or id>: the owner removes one of THEIR OWN rules."""
        from .owner_tests import remove

        if not name.strip():
            return "Text FORGET <test name> to remove a rule you taught."
        gone = remove(name, owner=report.owners[0].email if report.owners else "owner")
        if not gone:
            return f"No rule of yours called {name.strip()}."
        with self.lock:
            self.reports.clear()  # any PR may have carried that rule's evidence
        return "Forgot: " + "; ".join(f'{e["test_name"]} ("{e["sentence"]}")' for e in gone)

    def page(self, r: VerdictReport, pr_url: str = "", github: dict | None = None, dedupe: bool = False) -> dict:
        """Text owners[0] the verdict (full page, or one-line FYI on PASS); BLOCK/REVIEW also open the reply thread."""
        text = format_message(r, pr_url)
        out = {"to": r.owners[0].name if r.owners else None, "text": text, "sent": None}
        if not r.owners:
            return {**out, "skipped": "no code owner"}
        phone = imessage.phone_for(r.owners[0].email)
        if not phone:
            return {**out, "error": f"no phone on file for {r.owners[0].email}"}
        key = (r.pr_id, r.run_hash)
        with self.lock:  # check+add as one step: two verifies of one result must never both page
            if dedupe and key in self._paged:
                if (pr_url or github) and r.verdict != "PASS":  # a later caller may know the GitHub PR
                    self._open_thread(phone, r.pr_id, pr_url, github or {})
                return {**out, "skipped": "already paged for this exact result", "sent": "already sent"}
            self._paged[key] = None
            if len(self._paged) > 500:
                del self._paged[next(iter(self._paged))]
            if r.verdict != "PASS":  # an FYI needs no reply; the owner's pending thread stays on the PR that does
                self._open_thread(phone, r.pr_id, pr_url, github or {})
        try:
            out["sent"] = self.notifier.send(phone, text)
        except Exception:
            with self.lock:
                self._paged.pop(key, None)  # not paged after all: the next identical verdict may try again
            raise
        return out

    def _open_thread(self, phone: str, pr_id: str, pr_url: str, github: dict) -> None:
        """Where this number's next reply lands. Re-paging the same PR keeps its pr_url/github unless new ones are given,
        so a BLOCK texted about PR A never lands on PR B or loses the GitHub link it needs."""
        key = imessage.phone_key(phone)
        old = self.threads.get(key) or {}
        if old.get("pr_id") == pr_id:
            pr_url, github = pr_url or old.get("pr_url", ""), github or old.get("github") or {}
        self.threads[key] = {"pr_id": pr_id, "pr_url": pr_url, "github": github}

    def report(self, pr_id: str) -> VerdictReport:
        """The cached verdict, or a lazy verify that never texts anyone: only /api/verify and /api/run page."""
        r = self.reports.get(pr_id)
        if r is None:
            r = self.verify({"pr_id": pr_id}, auto_page=False)
        return r


# Browser origins allowed to call this API: the local dev UI and the deployed Vercel UI.
# Add more with MERGE_GATE_ORIGINS="https://a.example,https://b.example".
ALLOWED_ORIGINS = {
    "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173",
    "https://dist-phi-five-99.vercel.app",
} | {o.strip() for o in os.environ.get("MERGE_GATE_ORIGINS", "").split(",") if o.strip()}


def _text_later(state: State, phone: str, text: str, r: VerdictReport) -> None:
    """A text from a background thread (Sendblue already has its 200): a failure is logged AND written to the run log
    as reply_send_failed, so a lost confirmation shows up in /api/log instead of vanishing."""
    try:
        state.notifier.send(phone, text)
    except Exception as e:  # noqa: BLE001 - never lose the reply silently
        logger.exception("text to the owner of %s failed", r.pr_id)
        store.append("reply_send_failed", {"pr_id": r.pr_id, "owner": r.owners[0].name if r.owners else None,
                                           "text": text, "error": f"{type(e).__name__}: {e}"})


def _teach_or_forget(state: State, phone: str, r: VerdictReport, note: str, action: Action) -> None:
    """A verified owner's TEACH or FORGET from the webhook. The plain outcome text IS the reply: never worded by
    converse(), so what the owner reads is exactly what the gate stored or removed."""
    if action.kind == "teach":  # Muse + two sandbox runs: ack now, answer the webhook, text the outcome after
        state.notifier.send(phone, action.text)

        def teach() -> None:
            try:
                text = state.teach(r, note)
            except Exception as e:  # noqa: BLE001 - tell the owner instead of dying silently in a thread
                text = f"Couldn't learn that: {e}"
            _text_later(state, phone, text, r)

        threading.Thread(target=teach, daemon=True).start()
    if action.kind == "forget":
        state.notifier.send(phone, state.forget(r, note))


def _scan_github(state: State, body: dict) -> tuple[int, dict]:
    """POST /api/github: resolve + clone a live public GitHub PR and register it as a gate PR (then /api/run it)."""
    from . import github_pr

    query = (body.get("query") or "").strip()
    if not query:
        return 400, {"error": "query required: a repo name (requests), owner/repo, owner/repo#N or a PR URL"}
    try:
        resolved = github_pr.resolve(query)
        pr = github_pr.materialize(resolved, timeout_s=600)  # big repos: vllm needs > 3 min on venue Wi-Fi
    except Exception as e:  # noqa: BLE001 - the UI shows the reason verbatim
        return 400, {"error": f"{type(e).__name__}: {e}"}
    with state.lock:
        state.prs[pr.pr_id] = pr
        state.reports.pop(pr.pr_id, None)
    return 200, {
        "pr_id": pr.pr_id, "title": pr.title, "issue_text": pr.issue_text, "opened_by": pr.opened_by,
        "files": pr.changed_files(), "diff": pr.diff()[:200_000], "url": resolved.html_url,
        "repo": resolved.full_name, "number": resolved.number,
    }


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _origin_ok(self) -> bool:
            """Browsers always send Origin on cross-site fetch/POST; only our UI origins may drive this API.
            No Origin header = not a browser page (curl, the Sendblue webhook via ngrok), so it is allowed."""
            origin = self.headers.get("Origin")
            return origin is None or origin in ALLOWED_ORIGINS

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, code: int, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=lambda o: o.__dict__).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        def log_message(self, fmt: str, *args) -> None:  # quieter console
            pass

        def do_OPTIONS(self) -> None:
            self.send_response(204 if self._origin_ok() else 403)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _stream(self, pr_id: str, use_llm: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            t0 = time.monotonic()

            def send(obj: dict) -> None:
                obj["t"] = round(time.monotonic() - t0, 2)
                line = "data: " + json.dumps(obj, ensure_ascii=False, default=lambda o: o.__dict__) + "\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()

            try:
                send({"type": "begin", "pr_id": pr_id, "llm": use_llm})
                report = state.verify({"pr_id": pr_id, "llm": use_llm},
                                      on_stage=lambda name, status, data: send({"type": "stage", "stage": name, "status": status, **data}))
                ok, _ = store.verify_chain()
                send({"type": "report", "report": report.to_dict(), "chain_ok": ok})
            except Exception as e:  # noqa: BLE001
                send({"type": "error", "error": str(e)})

        def do_GET(self) -> None:
            if not self._origin_ok():
                return self._send(403, {"error": "origin not allowed"})
            try:
                url = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                if url.path == "/api/run":
                    use = state.use_llm if "llm" not in q else q["llm"] in ("1", "true")
                    return self._stream(q.get("pr_id", ""), use)
                if url.path == "/api/stats":
                    recs = store.read()
                    verdicts = [r["data"] for r in recs if r["kind"] == "verdict"]
                    ms = [v["ms"] for v in verdicts if isinstance(v.get("ms"), int)]
                    ok, _ = store.verify_chain()
                    return self._send(200, {
                        "checked": len(verdicts),
                        "blocked": sum(v["verdict"] == "BLOCK" for v in verdicts),
                        "review": sum(v["verdict"] == "REVIEW" for v in verdicts),
                        "passed": sum(v["verdict"] == "PASS" for v in verdicts),
                        "owner_replies": sum(r["kind"] == "reply" and r["data"].get("command") != "chat_block_request"
                                             for r in recs),
                        "owner_blocks": sum(r["kind"] == "reply" and r["data"].get("command") == "BLOCK" for r in recs),
                        "median_ms": int(statistics.median(ms)) if ms else None,
                        "events": len(recs),
                        "chain_ok": ok,
                        "llm": state.use_llm,
                    })
                if self.path == "/api/health":
                    return self._send(200, {"ok": True, "llm": state.use_llm, "subq": state.use_subq})
                if self.path == "/api/demo":
                    return self._send(200, [
                        {"pr_id": p.pr_id, "title": p.title, "issue_text": p.issue_text, "opened_by": p.opened_by,
                         "files": p.changed_files(), "diff": p.diff(),
                         "github_url": getattr(state.github_prs.get(p.pr_id), "url", "")}
                        for p in state.demo(refresh=True)
                    ])
                if self.path == "/api/log":
                    ok, bad = store.verify_chain()
                    return self._send(200, {"chain_ok": ok, "first_bad": bad, "records": store.read()[-200:]})
                return self._send(404, {"error": "not found"})
            except Exception as e:  # noqa: BLE001 - report to the client
                return self._send(500, {"error": str(e)})

        def _sendblue(self, body: dict) -> None:
            """Inbound iMessage webhook. Auth first; then only the PR's verified owner can act."""
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if not imessage.webhook_authorized(q.get("token"), list(self.headers.values())):
                return self._send(401, {"error": "unauthorized"})
            inbound = imessage.parse_inbound(body)
            if inbound is None:
                return self._send(200, {"ignored": "outbound echo or no sender"})
            thread = state.threads.get(imessage.phone_key(inbound.phone))
            if not thread:
                return self._send(200, {"ignored": "no open PR for this number"})
            r = state.report(thread["pr_id"])
            action, reply, ok = imessage.handle_inbound(inbound, r, thread["pr_url"])
            if not ok:
                store.log_reply(r.pr_id, "unverified-sender", reply.command, reply.raw, "rejected")
                return self._send(200, {"ignored": "sender is not this PR's owner"})
            owner = r.owners[0].name
            blocked = False
            gh = thread["github"]
            if action.kind == "block_pr" and gh.get("repo") and gh.get("number"):
                from . import github

                github.block_pr(gh["repo"], int(gh["number"]), owner, reply.note)
                blocked = True
            _teach_or_forget(state, inbound.phone, r, reply.note, action)
            store.log_reply(r.pr_id, owner, reply.command, reply.raw, action.kind)

            def answer() -> None:  # Muse can take seconds; Sendblue gets its 200 now, the owner gets the text after
                _text_later(state, inbound.phone, imessage.converse(r, reply.raw, action, thread["pr_url"]), r)

            if action.kind not in ("teach", "forget"):  # those already texted their plain outcome above
                threading.Thread(target=answer, daemon=True).start()
            return self._send(200, {"command": reply.command, "action": action.kind, "github_blocked": blocked})

        def _github(self, body: dict) -> None:
            return self._send(*_scan_github(state, body))

        def do_POST(self) -> None:
            if not self._origin_ok():
                return self._send(403, {"error": "origin not allowed"})
            try:
                body = self._body()
                if self.path == "/api/verify":
                    return self._send(200, state.verify(body).to_dict())
                if self.path == "/api/github":
                    return self._github(body)
                if self.path == "/api/message":
                    r = state.report(body["pr_id"])
                    text = format_message(r, body.get("pr_url", ""))
                    # text follows the report's urgency: "fyi" is a one-line FYI, "page" (or unassessed) the full message
                    out = {"to": r.owners[0].__dict__ if r.owners else None, "text": text, "urgency": r.urgency or "page", "sent": None}
                    if body.get("send") and r.owners:
                        paged = state.page(r, body.get("pr_url", ""), body.get("github") or {}, dedupe=True)
                        if paged.get("error"):
                            return self._send(400, {**out, "error": paged["error"]})
                        out["sent"] = paged["sent"]
                    return self._send(200, out)
                if urllib.parse.urlparse(self.path).path == "/api/sendblue":
                    return self._sendblue(body)
                if self.path == "/api/reply":
                    r = state.report(body["pr_id"])
                    reply = parse_reply(body.get("text", ""))
                    action = handle_reply(r, reply, body.get("pr_url", ""))
                    # Owner replies from a phone come through /api/sendblue (token + owner's verified number).
                    # A reply that changes an outcome (BLOCK fails a PR's check, FALSE ALARM feeds the learner)
                    # is only taken here from the War Room page on the presenter's laptop: without an allowed
                    # browser Origin, anyone on the machine could curl one. WHY and OK only answer with text.
                    if action.kind in ("block_pr", "log_false_alarm") and self.headers.get("Origin") not in ALLOWED_ORIGINS:
                        store.append("reply_rejected", {"pr_id": r.pr_id, "command": reply.command, "reason": "not from the War Room UI"})
                        return self._send(403, {"error": "replies are accepted only from the War Room UI; phones use /api/sendblue"})
                    if action.kind == "teach":  # runs model-written code: only the verified phone (/api/sendblue) may
                        return self._send(403, {"error": "teach requires a verified owner (reply by iMessage)"})
                    if action.kind == "forget":
                        return self._send(403, {"error": "forget requires a verified owner (reply by iMessage)"})
                    owner = r.owners[0].name if r.owners else "owner"
                    blocked = False
                    gh = body.get("github") or {}
                    if action.kind == "block_pr" and gh.get("repo") and gh.get("number"):
                        from . import github

                        github.block_pr(gh["repo"], int(gh["number"]), owner, reply.note)
                        blocked = True
                    store.log_reply(r.pr_id, owner, reply.command, reply.raw, action.kind)
                    return self._send(200, {"command": reply.command, "action": action.kind, "text": action.text, "github_blocked": blocked})
                return self._send(404, {"error": "not found"})
            except KeyError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787, use_llm: bool = False, use_subq: bool = False) -> None:
    state = State(use_llm, use_subq)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"[merge-gate] API on http://{host}:{port}  (Muse Spark {'ON' if use_llm else 'OFF'}, SubQ {'ON' if use_subq else 'OFF'})")
    httpd.serve_forever()
