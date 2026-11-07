"""GitHub enforcement, CI entry point, run log and HTTP API. No network: the GitHub API is faked."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from merge_gate import ci, github, serve, store
from merge_gate.cli import stub_report
from merge_gate.schema import Owner

from helpers import make_pr

SRC = "def apply_discount(price, pct):\n    \"\"\"Never below zero.\"\"\"\n    return max(0.0, price * (1 - pct / 100))\n"
TESTS = "from shop.pricing import apply_discount\n\n\ndef test_a():\n    assert apply_discount(100, 10) == 90\n\n\ndef test_b():\n    assert apply_discount(10, 150) == 0.0\n"


@pytest.fixture
def fake_github(monkeypatch):
    calls = []

    def fake_call(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and "/pulls/" in path:
            return {"head": {"sha": "abc123"}}
        return {}

    monkeypatch.setattr(github, "_call", fake_call)
    return calls


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = str(tmp_path / "log.jsonl")
    monkeypatch.setattr(store, "LOG_PATH", path)
    return path


def test_publish_maps_verdict_to_status(fake_github):
    github.publish(stub_report("PR-7"), "o/r", 7)
    status = [c for c in fake_github if "/statuses/" in c[1]][0]
    assert status[1] == "/repos/o/r/statuses/abc123"
    assert status[2]["state"] == "failure" and status[2]["context"] == "merge-gate"
    body = [c for c in fake_github if "/comments" in c[1]][0][2]["body"]
    assert "BLOCKED" in body and "R1_DELETED_TEST" in body and "Peter" in body


def test_block_pr_fails_the_check(fake_github):
    github.block_pr("o/r", 7, "Peter", "this breaks refunds")
    status = [c for c in fake_github if "/statuses/" in c[1]][0][2]
    assert status["state"] == "failure" and "Peter" in status["description"]


def test_text_can_never_set_success():
    # the only success path in github.py is a status from a clean gate run or a GitHub approval in ci.py
    import inspect

    src = inspect.getsource(github.block_pr)
    assert '"success"' not in src


def _event(tmp_path, pr_body="Make it faster", review=None):
    ev = {"pull_request": {"number": 7, "title": "Speed up", "body": pr_body, "user": {"login": "bot"},
                           "base": {"ref": "main"}, "head": {"sha": "pr/1"}}}
    if review:
        ev["review"] = review
    path = tmp_path / "event.json"
    path.write_text(json.dumps(ev), encoding="utf-8")
    return str(path)


def test_ci_blocks_a_deleted_test(tmp_path, monkeypatch, fake_github, log_path):
    pr = make_pr(tmp_path, {"shop/__init__.py": "", "shop/pricing.py": SRC, "tests/test_pricing.py": TESTS},
                 {"tests/test_pricing.py": TESTS.split("\n\n\ndef test_b")[0] + "\n"})
    # ci reads origin/<base>; make a local ref with that name
    from helpers import git
    git(pr.repo_path, "update-ref", "refs/remotes/origin/main", "main")
    monkeypatch.chdir(pr.repo_path)
    monkeypatch.setenv("GITHUB_EVENT_PATH", _event(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    out = str(tmp_path / "gate_result.json")
    assert ci.main(use_llm=False, out_path=out) == 1
    report = json.loads(open(out, encoding="utf-8").read())
    assert report["verdict"] == "BLOCK"
    assert any(c[2] and c[2].get("state") == "failure" for c in fake_github)
    assert store.read(log_path, "verdict")


def test_owner_github_approval_is_the_only_override(tmp_path, monkeypatch):
    r = stub_report("PR-7")  # owners: peter@example.com first
    monkeypatch.setenv("OWNER_GITHUB", json.dumps({"peter@example.com": "peter-gh"}))
    approve = {"review": {"state": "approved", "user": {"login": "peter-gh"}}}
    stranger = {"review": {"state": "approved", "user": {"login": "random-dev"}}}
    assert ci.owner_approved(approve, r) == "peter-gh"
    assert ci.owner_approved(stranger, r) == ""
    assert ci.owner_approved({"review": {"state": "commented", "user": {"login": "peter-gh"}}}, r) == ""


def test_log_is_a_hash_chain(tmp_path):
    path = str(tmp_path / "log.jsonl")
    store.log_report(stub_report("a"), path=path)
    store.log_reply("a", "Peter", "BLOCK", "block", "block_pr", path=path)
    assert store.verify_chain(path) == (True, -1)
    lines = open(path, encoding="utf-8").read().splitlines()
    tampered = json.loads(lines[0])
    tampered["data"]["verdict"] = "PASS"
    lines[0] = json.dumps(tampered)
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert store.verify_chain(path) == (False, 0)


def test_api_verify_message_reply(tmp_path, monkeypatch, fake_github, log_path):
    monkeypatch.setattr(serve, "DEMO_ROOT", str(tmp_path / "demo"))
    state = serve.State(use_llm=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Origin": "http://localhost:3000"})
        return json.loads(urllib.request.urlopen(req, timeout=120).read())

    try:
        demo = json.loads(urllib.request.urlopen(base + "/api/demo", timeout=60).read())
        assert [d["pr_id"] for d in demo] == ["demo-1", "demo-2", "demo-3", "demo-4"]
        r = post("/api/verify", {"pr_id": "demo-1"})
        assert r["verdict"] == "BLOCK" and r["owners"][0]["name"] == "Peter"
        m = post("/api/message", {"pr_id": "demo-1"})
        assert m["to"]["name"] == "Peter" and "BLOCKED" in m["text"]
        ok = post("/api/reply", {"pr_id": "demo-1", "text": "OK", "pr_url": "https://github.com/o/r/pull/7"})
        assert ok["action"] == "send_text" and "github.com" in ok["text"]
        blk = post("/api/reply", {"pr_id": "demo-1", "text": "BLOCK", "github": {"repo": "o/r", "number": 7}})
        assert blk["action"] == "block_pr" and blk["github_blocked"] is True
        assert any(c[2] and c[2].get("state") == "failure" for c in fake_github)
        log = json.loads(urllib.request.urlopen(base + "/api/log", timeout=30).read())
        assert log["chain_ok"] and any(rec["kind"] == "reply" for rec in log["records"])
    finally:
        httpd.shutdown()
