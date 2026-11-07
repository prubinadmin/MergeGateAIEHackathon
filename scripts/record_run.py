"""Record a real run of the gate into src/warroom/recorded-run.json, for the static (Vercel) War Room.

Starts the real API in-process on a free port (temporary run log and demo repo), then for every demo PR:
streams /api/run, fetches the owner's message, and sends each reply the phone panel offers. Nothing is
edited by hand: the page replays exactly what the gate returned.

  python scripts/record_run.py            # Muse Spark on if MUSE_API_KEY is set
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from merge_gate import serve, store  # noqa: E402
from merge_gate.llm import has_key  # noqa: E402

UI = {"Origin": "http://localhost:3000", "Content-Type": "application/json"}
REPLIES = ["BLOCK", "WHY", "OK", "FALSE ALARM"]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="mg-record-")
    store.LOG_PATH = os.path.join(tmp, "log.jsonl")
    serve.DEMO_ROOT = os.path.join(tmp, "demo")
    use_llm = has_key()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(serve.State(use_llm)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path):
        req = urllib.request.Request(base + path, headers=UI)
        return json.loads(urllib.request.urlopen(req, timeout=600).read())

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=UI)
        return json.loads(urllib.request.urlopen(req, timeout=600).read())

    out = {"recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "health": get("/api/health"), "demo": get("/api/demo"), "runs": {}, "messages": {}, "replies": {}}
    for pr in out["demo"]:
        pid = pr["pr_id"]
        events = []
        req = urllib.request.Request(f"{base}/api/run?pr_id={pid}&llm={'1' if use_llm else '0'}", headers=UI)
        with urllib.request.urlopen(req, timeout=900) as r:
            for raw in r:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        out["runs"][pid] = events
        verdict = events[-1].get("report", {}).get("verdict")
        print(f"{pid}: {verdict} ({events[-1].get('t')}s)", flush=True)
        out["messages"][pid] = post("/api/message", {"pr_id": pid})
        if verdict and verdict != "PASS":
            out["replies"][pid] = {cmd: post("/api/reply", {"pr_id": pid, "text": cmd}) for cmd in REPLIES}
    out["stats"] = get("/api/stats")
    httpd.shutdown()

    path = os.path.join(ROOT, "src", "warroom", "recorded-run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
