"""Run log (owner: Michael): every verdict, owner reply and gate-version decision, append-only.

Local: runs/log.jsonl (git-ignored). If MONGODB_URI is set and pymongo is installed, each record is
also inserted into the `mergegate.runs` collection. Each record carries the previous record's hash,
so editing or deleting a past line breaks the chain (verify_chain finds where).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading

from .llm import load_dotenv
from .schema import VerdictReport, run_hash

LOG_PATH = os.path.join("runs", "log.jsonl")
_lock = threading.Lock()


def _last_hash(path: str) -> str:
    if not os.path.exists(path):
        return ""
    last = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last)["hash"] if last else ""


def append(kind: str, data: dict, path: str | None = None) -> dict:
    path = path or LOG_PATH
    with _lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        rec = {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "data": data,
            "prev": _last_hash(path),
        }
        rec["hash"] = run_hash({k: rec[k] for k in ("at", "kind", "data", "prev")})
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _mongo_insert(rec)
    return rec


def log_report(report: VerdictReport, source: str = "cli", path: str | None = None, **extra) -> dict:
    return append("verdict", {"source": source, **report.to_dict(), **extra}, path)


def log_reply(pr_id: str, owner: str, command: str, raw: str, action: str, path: str | None = None) -> dict:
    return append("reply", {"pr_id": pr_id, "owner": owner, "command": command, "raw": raw, "action": action}, path)


def read(path: str | None = None, kind: str | None = None) -> list[dict]:
    path = path or LOG_PATH
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    return [r for r in recs if kind is None or r["kind"] == kind]


def verify_chain(path: str | None = None) -> tuple[bool, int]:
    """(ok, index of the first bad record or -1)."""
    prev = ""
    for i, rec in enumerate(read(path)):
        expect = run_hash({k: rec[k] for k in ("at", "kind", "data", "prev")})
        if rec["prev"] != prev or rec["hash"] != expect:
            return False, i
        prev = rec["hash"]
    return True, -1


def _mongo_insert(rec: dict) -> None:
    load_dotenv()
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return
    try:
        import pymongo  # optional dependency
    except ImportError:
        return
    try:
        pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)["mergegate"]["runs"].insert_one(dict(rec))
    except Exception:
        pass  # the local log is the source of truth; Mongo is a mirror
