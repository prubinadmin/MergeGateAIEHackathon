"""`python -m merge_gate serve`: HTTP API over the real gate, for the web UI and the iMessage webhook.

  GET  /api/health
  GET  /api/demo                      demo PRs (builds the demo repo once, under runs/demo)
  POST /api/verify   {"pr_id": "demo-1"}                 -> verdict report (real rules, blame, sandbox, Muse)
       or          {"repo_path", "base_ref", "head_ref", "issue_text", "title", "opened_by", "pr_id"}
  POST /api/message  {"pr_id": "demo-1", "pr_url": ""}  -> {"to": owner, "text": iMessage text}
  POST /api/reply    {"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}}
                                                         -> {"command", "action", "text", "github_blocked"}
  GET  /api/log                       run log records + whether the hash chain verifies

Stdlib only. CORS is open so the Vite dev server can call it. Bind to localhost.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store
from .demo import build_demo_repo, demo_prs
from .notify import format_message, handle_reply, parse_reply
from .pr import PullRequest
from .schema import VerdictReport

DEMO_ROOT = os.path.join("runs", "demo")


class State:
    def __init__(self, use_llm: bool) -> None:
        self.use_llm = use_llm
        self.reports: dict[str, VerdictReport] = {}
        self.prs: dict[str, PullRequest] = {}
        self.lock = threading.Lock()
        self._demo_ready = False

    def demo(self) -> list[PullRequest]:
        with self.lock:
            if not self._demo_ready:
                repo = build_demo_repo(DEMO_ROOT)
                for pr in demo_prs(repo):
                    self.prs[pr.pr_id] = pr
                self._demo_ready = True
        return [p for k, p in self.prs.items() if k.startswith("demo-")]

    def verify(self, body: dict) -> VerdictReport:
        from .verify import verify

        if "repo_path" in body:
            pr = PullRequest(
                pr_id=body.get("pr_id") or "custom",
                repo_path=body["repo_path"],
                base_ref=body.get("base_ref", "main"),
                head_ref=body["head_ref"],
                issue_text=body.get("issue_text", ""),
                title=body.get("title", ""),
                opened_by=body.get("opened_by", ""),
            )
        else:
            self.demo()
            pr = self.prs.get(body.get("pr_id", ""))
            if pr is None:
                raise KeyError(f"unknown pr_id {body.get('pr_id')!r}")
        use_llm = body.get("llm", self.use_llm)
        report = verify(pr, use_llm=bool(use_llm))
        store.log_report(report, source="api")
        with self.lock:
            self.prs[pr.pr_id] = pr
            self.reports[pr.pr_id] = report
        return report

    def report(self, pr_id: str) -> VerdictReport:
        r = self.reports.get(pr_id)
        if r is None:
            r = self.verify({"pr_id": pr_id})
        return r


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=lambda o: o.__dict__).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
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
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            try:
                if self.path == "/api/health":
                    return self._send(200, {"ok": True, "llm": state.use_llm})
                if self.path == "/api/demo":
                    return self._send(200, [
                        {"pr_id": p.pr_id, "title": p.title, "issue_text": p.issue_text, "opened_by": p.opened_by,
                         "files": p.changed_files(), "diff": p.diff()}
                        for p in state.demo()
                    ])
                if self.path == "/api/log":
                    ok, bad = store.verify_chain()
                    return self._send(200, {"chain_ok": ok, "first_bad": bad, "records": store.read()[-200:]})
                return self._send(404, {"error": "not found"})
            except Exception as e:  # noqa: BLE001 - report to the client
                return self._send(500, {"error": str(e)})

        def do_POST(self) -> None:
            try:
                body = self._body()
                if self.path == "/api/verify":
                    return self._send(200, state.verify(body).to_dict())
                if self.path == "/api/message":
                    r = state.report(body["pr_id"])
                    return self._send(200, {"to": r.owners[0].__dict__ if r.owners else None, "text": format_message(r, body.get("pr_url", ""))})
                if self.path == "/api/reply":
                    r = state.report(body["pr_id"])
                    reply = parse_reply(body.get("text", ""))
                    action = handle_reply(r, reply, body.get("pr_url", ""))
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


def serve(host: str = "127.0.0.1", port: int = 8787, use_llm: bool = False) -> None:
    state = State(use_llm)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"[merge-gate] API on http://{host}:{port}  (Muse Spark {'ON' if use_llm else 'OFF'})")
    httpd.serve_forever()
