"""An owner's BLOCK reaches the page fast: logged before the GitHub calls, then pushed over /api/events."""

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from merge_gate import github, serve, store


def test_block_is_pushed_before_github_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(serve, "DEMO_ROOT", str(tmp_path / "demo"))
    monkeypatch.setenv("MERGE_GATE_AUTO_PAGE", "0")

    def slow_github(method, path, body=None):  # a GitHub that takes a while, like the real one
        time.sleep(0.8)
        return {"head": {"sha": "abc"}} if method == "GET" else {}

    monkeypatch.setattr(github, "_call", slow_github)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(serve.State(use_llm=False)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    ui = {"Content-Type": "application/json", "Origin": "http://localhost:3000"}
    try:
        req = urllib.request.Request(base + "/api/verify", data=json.dumps({"pr_id": "demo-1"}).encode(), headers=ui)
        urllib.request.urlopen(req, timeout=120).read()

        events: list[tuple[float, dict]] = []
        stream = urllib.request.urlopen(urllib.request.Request(base + "/api/events", headers={"Origin": "http://localhost:3000"}), timeout=30)

        def read() -> None:
            for raw in stream:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    events.append((time.monotonic(), json.loads(line[6:])))
                    if len(events) >= 2:
                        return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.3)

        t0 = time.monotonic()
        body = {"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}}
        out = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/reply", data=json.dumps(body).encode(), headers=ui), timeout=30).read())
        answered = time.monotonic() - t0
        reader.join(timeout=10)

        assert out["action"] == "block_pr" and out["github_blocked"] == "pending"
        assert answered < 0.6, f"reply waited on GitHub: {answered:.2f}s"
        kinds = [e["kind"] for _, e in events]
        assert kinds == ["reply", "github_blocked"]
        first_push = events[0][0] - t0
        assert first_push < 1.0, f"the BLOCK took {first_push:.2f}s to reach the page"
        assert events[1][1]["data"]["ok"] is True
    finally:
        httpd.shutdown()
