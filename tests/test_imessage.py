import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from merge_gate import imessage
from merge_gate.schema import Owner, VerdictReport

OWNER = "+1 (555) 010-0001"
SECRET = "s" * 24


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET", "SENDBLUE_FROM_NUMBER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OWNER_PHONES", json.dumps({"Peter@Example.com": OWNER}))
    monkeypatch.setenv("SENDBLUE_WEBHOOK_SECRET", SECRET)


def _report():
    return VerdictReport(pr_id="p1", verdict="BLOCK", owners=[Owner("Peter", "peter@example.com", 3, "2026-03-01")])


def test_phone_key_normalises_formats():
    assert imessage.phone_key("+1 (555) 010-0001") == imessage.phone_key("15550100001") == "5550100001"


def test_webhook_fails_closed_without_strong_secret(monkeypatch):
    monkeypatch.delenv("SENDBLUE_WEBHOOK_SECRET")
    assert not imessage.webhook_authorized("", [])
    monkeypatch.setenv("SENDBLUE_WEBHOOK_SECRET", "short")
    assert not imessage.webhook_authorized("short", [])


def test_webhook_accepts_token_in_url_or_header_only():
    assert imessage.webhook_authorized(SECRET, [])
    assert imessage.webhook_authorized(None, ["application/json", SECRET])
    assert not imessage.webhook_authorized("wrong" * 5, ["application/json"])


def test_outbound_echo_ignored():
    assert imessage.parse_inbound({"is_outbound": True, "from_number": OWNER, "content": "x"}) is None


def test_only_the_owner_phone_can_block():
    r = _report()
    action, reply, ok = imessage.handle_inbound(imessage.Inbound("+15550100001", "BLOCK rounding"), r)
    assert ok and action.kind == "block_pr" and reply.command == "BLOCK"
    action, _, ok = imessage.handle_inbound(imessage.Inbound("+15559999999", "BLOCK"), r)
    assert not ok and action.kind == "none"


def test_ok_from_owner_never_approves():
    action, _, ok = imessage.handle_inbound(imessage.Inbound(OWNER, "OK"), _report(), "https://github.com/o/r/pull/7")
    assert ok and action.kind == "send_text" and "github.com/o/r/pull/7" in action.text


def test_sendblue_request_shape_and_error(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["headers"], seen["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
        return io.BytesIO(json.dumps({"status": "QUEUED", "message_handle": "h-1"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    n = imessage.SendblueNotifier("kid", "ksecret", "+15550000000")
    assert n.send("+15550100001", "hi") == "h-1"
    assert seen["url"] == imessage.SEND_URL
    assert seen["headers"]["Sb-api-key-id"] == "kid" and seen["headers"]["Sb-api-secret-key"] == "ksecret"
    assert seen["body"] == {"number": "+15550100001", "content": "hi", "from_number": "+15550000000"}

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout: io.BytesIO(b'{"status": "ERROR", "error_message": "not a contact"}'))
    with pytest.raises(imessage.SendError, match="not a contact"):
        n.send("+15550100001", "hi")


def test_console_notifier_without_keys():
    assert type(imessage.notifier_from_env()).__name__ == "ConsoleNotifier"


# --- end to end through the real HTTP server and the demo repo ---------------------------------

def _post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_webhook_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # demo repo + run log go to a temp dir
    monkeypatch.delenv("MONGODB_URI", raising=False)
    from merge_gate import serve

    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()  # never hit Sendblue from tests, even if keys are in .env
    state.demo()
    owner_email = state.report("demo-1").owners[0].email
    monkeypatch.setenv("OWNER_PHONES", json.dumps({owner_email: OWNER}))

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        code, out = _post(port, "/api/message", {"pr_id": "demo-1", "send": True})
        assert code == 200 and out["sent"] == "console-1"

        hook = f"/api/sendblue?token={SECRET}"
        assert _post(port, "/api/sendblue?token=nope", {"from_number": OWNER, "content": "BLOCK"})[0] == 401
        code, out = _post(port, hook, {"from_number": "+15559999999", "content": "BLOCK"})
        assert code == 200 and "ignored" in out  # stranger, and no thread for that number
        code, out = _post(port, hook, {"from_number": "15550100001", "content": "WHY"})
        assert code == 200 and out["action"] == "send_text"
        code, out = _post(port, hook, {"from_number": OWNER, "content": "BLOCK"})
        assert code == 200 and out == {"command": "BLOCK", "action": "block_pr", "github_blocked": False}
        assert len(state.notifier.sent) == 3  # the page, the WHY answer, the "Blocked" confirmation
    finally:
        httpd.shutdown()
