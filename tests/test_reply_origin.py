"""/api/reply is for the War Room page only; a curl or a foreign site cannot forge an owner's answer."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from merge_gate import serve, store


def test_reply_needs_the_war_room_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(serve, "DEMO_ROOT", str(tmp_path / "demo"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(serve.State(use_llm=False)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(body, origin=None):
        headers = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
        req = urllib.request.Request(base + "/api/reply", data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        forged = post({"pr_id": "demo-1", "text": "FALSE ALARM"})
        assert forged[0] == 403 and "/api/sendblue" in forged[1]["error"]
        assert post({"pr_id": "demo-1", "text": "BLOCK"}, "https://evil.example")[0] == 403
        assert store.read(kind="reply") == []  # nothing reached the learner
        assert store.read(kind="reply_rejected")

        code, body = post({"pr_id": "demo-1", "text": "BLOCK"}, "http://localhost:3000")
        assert code == 200 and body["action"] == "block_pr"
    finally:
        httpd.shutdown()
