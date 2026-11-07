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
    import merge_gate.llm as llm

    def no_network(*a, **k):
        raise RuntimeError("no LLM in tests")

    monkeypatch.setattr(llm, "complete", no_network)  # converse() must fall back to the plain-code text
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
    state.auto_page = False  # this test drives paging by hand; auto-paging has its own test
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
        import time
        for _ in range(100):  # owner replies are sent from a background thread
            if len(state.notifier.sent) >= 3:
                break
            time.sleep(0.05)
        assert len(state.notifier.sent) == 3  # the page, the WHY answer, the "Blocked" confirmation
    finally:
        httpd.shutdown()


# --- conversational replies ---------------------------------------------------------------------------

def _block_report():
    from merge_gate.schema import Evidence
    return VerdictReport(pr_id="p1", verdict="BLOCK", owners=[Owner("Peter", "peter@example.com", 3, "2026-03-01")],
                         evidence=[Evidence(type="rule", id="R1_DELETED_TEST", detail="PR deletes test_x")], run_hash="sha256:abc")


def test_converse_uses_muse_wording(monkeypatch):
    import merge_gate.llm as llm
    seen = {}

    def fake(developer, user, **k):
        seen["user"] = user
        return "Done, I blocked p1: it deletes test_x, which is the test that guards your discount rule."

    monkeypatch.setattr(llm, "complete", fake)
    action = imessage.handle_inbound(imessage.Inbound(OWNER, "BLOCK"), _block_report())[0]
    text = imessage.converse(_block_report(), "BLOCK", action)
    assert text.startswith("Done, I blocked p1") and "R1_DELETED_TEST" in seen["user"] and "block_pr" in seen["user"]


def test_converse_never_claims_approval(monkeypatch):
    import merge_gate.llm as llm
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "All good, I approved and merged it for you.")
    action = imessage.handle_inbound(imessage.Inbound(OWNER, "OK"), _block_report(), "https://github.com/o/r/pull/7")[0]
    text = imessage.converse(_block_report(), "OK", action, "https://github.com/o/r/pull/7")
    assert text == action.text and "github.com/o/r/pull/7" in text


def test_converse_block_must_say_block(monkeypatch):
    import merge_gate.llm as llm
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Got it, thanks!")
    action = imessage.handle_inbound(imessage.Inbound(OWNER, "BLOCK"), _block_report())[0]
    assert imessage.converse(_block_report(), "BLOCK", action) == action.text


def test_converse_falls_back_when_muse_fails():
    action = imessage.handle_inbound(imessage.Inbound(OWNER, "WHY"), _block_report())[0]
    assert imessage.converse(_block_report(), "WHY", action) == action.text


def test_converse_forbids_claims_not_the_word_approve(monkeypatch):
    import merge_gate.llm as llm
    url = "https://github.com/o/r/pull/7"
    action = imessage.handle_inbound(imessage.Inbound(OWNER, "OK"), _block_report(), url)[0]
    ok_text = f"Nothing I can do here, approve it yourself on GitHub: {url}"
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ok_text)
    assert imessage.converse(_block_report(), "OK", action, url) == ok_text  # telling the owner to approve is fine
    for claim in ("Clean. Go ahead and merge.", "This is safe to ship.", "I approved it, you're done.",
                  "Good to go, nothing else needed.", "Ship it."):
        monkeypatch.setattr(llm, "complete", lambda *a, _c=claim, **k: _c)
        assert imessage.converse(_block_report(), "OK", action, url) == action.text, claim


def test_page_opens_a_reply_thread_only_for_block_and_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    from merge_gate import serve

    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()
    peter = Owner("Peter", "peter@example.com", 3, "2026-03-01")  # the autouse env maps this address to OWNER
    key, gh = imessage.phone_key(OWNER), {"repo": "o/r", "number": 7}

    state.page(VerdictReport(pr_id="a", verdict="BLOCK", owners=[peter], run_hash="h1"), "https://u/a", gh)
    assert state.threads[key] == {"pr_id": "a", "pr_url": "https://u/a", "github": gh}
    state.page(VerdictReport(pr_id="b", verdict="PASS", owners=[peter], run_hash="h2"))  # an FYI: no reply expected
    assert state.threads[key]["pr_id"] == "a"  # a BLOCK texted back still means PR a, not the last FYI
    state.page(VerdictReport(pr_id="a", verdict="BLOCK", owners=[peter], run_hash="h3"))  # re-page, no context given
    assert state.threads[key] == {"pr_id": "a", "pr_url": "https://u/a", "github": gh}  # GitHub link kept
    state.page(VerdictReport(pr_id="c", verdict="REVIEW", owners=[peter], run_hash="h4"), "https://u/c")
    assert state.threads[key] == {"pr_id": "c", "pr_url": "https://u/c", "github": {}}
    assert len(state.notifier.sent) == 4 and set(state._paged) == {("a", "h1"), ("b", "h2"), ("a", "h3"), ("c", "h4")}


def test_failed_background_text_is_logged_and_recorded(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    from merge_gate import serve, store

    class Down:
        def send(self, phone, text):
            raise imessage.SendError("Sendblue HTTP 500")

    state = serve.State(use_llm=False)
    state.notifier = Down()
    with caplog.at_level("ERROR", logger="merge_gate.serve"):
        serve._text_later(state, OWNER, "Blocked p1.", _block_report())  # raises nothing: the thread must live
    assert "p1" in caplog.text and "SendError" in caplog.text
    [rec] = store.read(kind="reply_send_failed")
    assert rec["data"] == {"pr_id": "p1", "owner": "Peter", "text": "Blocked p1.", "error": "SendError: Sendblue HTTP 500"}
    assert OWNER not in json.dumps(rec)  # the phone number stays out of the run log


def test_lazy_report_never_pages_and_message_send_texts_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    from merge_gate import serve

    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()
    state.demo()
    owner = state.verify({"pr_id": "demo-1"}, auto_page=False).owners[0]
    monkeypatch.setenv("OWNER_PHONES", json.dumps({owner.email: OWNER}))
    state.reports.clear()
    assert state.report("demo-1").verdict == "BLOCK" and state.notifier.sent == []  # read-ish paths never text

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        state.reports.clear()
        code, out = _post(port, "/api/message", {"pr_id": "demo-1", "send": True})
        assert code == 200 and out["sent"] == "console-1" and len(state.notifier.sent) == 1  # once, not twice
        assert _post(port, "/api/reply", {"pr_id": "demo-1", "text": "WHY"})[0] == 200
        assert len(state.notifier.sent) == 1
    finally:
        httpd.shutdown()


def test_auto_page_on_verdict_and_no_duplicate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    from merge_gate import serve

    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()
    state.demo()
    owner = state.verify({"pr_id": "demo-1"}).owners[0]
    monkeypatch.setenv("OWNER_PHONES", json.dumps({owner.email: OWNER}))
    state._paged.clear(); state.notifier.sent.clear()

    stages = []
    r = state.verify({"pr_id": "demo-1"}, on_stage=lambda n, st, d: stages.append((n, st, d)))
    assert len(state.notifier.sent) == 1 and r.verdict == "BLOCK"  # paged with no click
    done = [d for n, st, d in stages if n == "page" and st == "done"][0]
    assert done["to"] == owner.name and done["sent"] == "console-1"
    assert imessage.phone_key(OWNER) in state.threads  # the owner's reply has a thread to land in

    state.verify({"pr_id": "demo-1"})  # identical result: no second text
    assert len(state.notifier.sent) == 1


def test_auto_page_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MERGE_GATE_AUTO_PAGE", "0")
    from merge_gate import serve

    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()
    state.demo()
    state.verify({"pr_id": "demo-1"})
    assert state.notifier.sent == []
