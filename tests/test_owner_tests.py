"""Owner replies become tests. The model is replaced by fixed text: no network, no real iMessage."""

import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from merge_gate import imessage, llm, owner_tests, store
from merge_gate.demo import build_demo_repo, demo_prs
from merge_gate.learn import GateConfig, apply_config
from merge_gate.notify import handle_reply, parse_reply
from merge_gate.schema import Evidence, Owner, VerdictReport

SENTENCE = "a discount over 100% must make the price free, never negative"
GOOD = '''```python
def test_discount_over_100_is_free():
    from shop.pricing import apply_discount
    assert apply_discount(10, 150) == 0.0, "over 100% off is free, never negative"
    assert apply_discount(10, 100) == 0.0, "100% off is free"
```'''
WRONG_ON_MAIN = GOOD.replace("== 0.0, \"over", "== -5.0, \"over")
PETER = "peter@example.com"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # demo repo, run log and owner_tests/ all land in the temp dir
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setattr(store, "_mongo_insert", lambda rec: None)
    return {p.pr_id: p for p in demo_prs(build_demo_repo("demo"))}


def model(monkeypatch, text):
    calls = []

    def fake(dev, user, **kw):
        calls.append(user)
        if isinstance(text, Exception):
            raise text
        return text

    monkeypatch.setattr(llm, "complete", fake)
    return calls


def test_accepted_when_it_holds_on_base_and_breaks_on_head(demo, monkeypatch):
    calls = model(monkeypatch, GOOD)
    t = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    assert t.accepted and t.passes_base and t.fails_head, t.reason
    assert t.test_name == "test_discount_over_100_is_free"
    assert SENTENCE in calls[0] and "def apply_discount" in calls[0]
    assert "test_discount_never_negative" not in calls[0]  # never shown the PR's tests

    assert t.file == "peter/test_discount_over_100_is_free.py"
    assert "apply_discount(10, 150)" in open(f"owner_tests/{t.file}").read()
    [entry] = owner_tests.load_registry()
    assert {k: entry[k] for k in ("owner", "sentence", "pr_id", "passes_base", "fails_head")} == {
        "owner": PETER, "sentence": SENTENCE, "pr_id": "demo-1", "passes_base": True, "fails_head": True}
    assert entry["created_at"] and entry["run_hash"].startswith("sha256:") and entry["files"] == ["shop/pricing.py"]
    [rec] = store.read(kind="owner_test")
    assert rec["data"]["accepted"] and rec["data"]["file"] == t.file
    assert owner_tests.outcome_text(t) == ("Learned: test_discount_over_100_is_free. "
                                           "It fails on demo-1, so demo-1 stays blocked.")


def test_rejected_when_the_rule_does_not_hold_on_main(demo, monkeypatch):
    model(monkeypatch, WRONG_ON_MAIN)
    t = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    assert not t.accepted and not t.passes_base
    assert "doesn't hold on main" in t.reason and owner_tests.outcome_text(t).startswith("Couldn't learn that")
    assert owner_tests.load_registry() == []
    assert store.read(kind="owner_test")[0]["data"]["accepted"] is False


@pytest.mark.parametrize("out, why", [
    ("```python\ndef test_x(:\n```", "doesn't parse"),
    ("```python\nX = 1\n```", "no test function"),
    (llm.LLMError("down"), "unavailable"),
])
def test_rejected_without_a_usable_test(demo, monkeypatch, out, why):
    model(monkeypatch, out)
    t = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    assert not t.accepted and why in t.reason and owner_tests.load_registry() == []


def test_free_text_is_teach_and_commands_still_work():
    r = parse_reply("pricing must never round before tax")
    assert (r.command, r.note) == ("TEACH", "pricing must never round before tax")
    assert parse_reply("BLOCK rounding").command == "BLOCK"
    assert parse_reply("why?").command == "WHY"
    assert parse_reply("false alarm, fine").command == "FALSE_ALARM"
    assert parse_reply("ok").command == "OK"
    assert parse_reply("   ").command == "UNKNOWN"
    assert parse_reply("thanks!").command == "UNKNOWN"  # too short to be a rule: no model call
    report = VerdictReport(pr_id="p1", verdict="BLOCK", evidence=[Evidence("rule", "R1", "x")])
    action = handle_reply(report, r)
    assert action.kind == "teach" and "turning that into a test" in action.text


def test_only_the_owner_can_teach(monkeypatch):
    monkeypatch.setenv("OWNER_PHONES", json.dumps({PETER: "+15550100001"}))
    r = VerdictReport(pr_id="p1", verdict="BLOCK", owners=[Owner("Peter", PETER, 3, "2026-03-01")])
    action, reply, ok = imessage.handle_inbound(imessage.Inbound("+15559999999", SENTENCE), r)
    assert reply.command == "TEACH" and not ok and action.kind == "none"
    action, _, ok = imessage.handle_inbound(imessage.Inbound("+15550100001", SENTENCE), r)
    assert ok and action.kind == "teach"


def test_verify_turns_a_stored_owner_test_into_block_evidence(demo, monkeypatch):
    from merge_gate.verify import verify

    model(monkeypatch, GOOD)
    assert owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE).accepted
    model(monkeypatch, llm.LLMError("no model needed to run stored tests"))

    report = verify(demo["demo-1"], use_llm=True, config=None)
    [ev] = [e for e in report.evidence if e.id.startswith("owner::")]
    assert ev.id == "owner::peter::test_discount_over_100_is_free" and ev.severity == "block"
    assert SENTENCE in ev.detail and report.verdict == "BLOCK"
    # untouched file -> the rule isn't run; same rule on a PR that keeps it -> no evidence
    assert not [e for e in verify(demo["demo-3"], use_llm=True, config=None).evidence if e.id.startswith("owner::")]
    # learned gate config can never mute an owner's rule
    cfg = GateConfig(rule_severity={"owner": "off", ev.id: "review"})
    assert apply_config([ev], cfg)[0].severity == "block"


def _post(port, path, body):
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def test_reply_and_webhook_teach_end_to_end(demo, monkeypatch):
    from merge_gate import serve

    secret = "s" * 24
    monkeypatch.setenv("SENDBLUE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("OWNER_PHONES", json.dumps({PETER: "+15550100001"}))
    model(monkeypatch, GOOD)
    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()  # never a real iMessage
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        out = _post(port, "/api/reply", {"pr_id": "demo-1", "text": SENTENCE})
        assert out["command"] == "TEACH" and out["action"] == "teach"
        assert out["text"] == "Learned: test_discount_over_100_is_free. It fails on demo-1, so demo-1 stays blocked."

        hook = f"/api/sendblue?token={secret}"
        state.threads[imessage.phone_key("+15559999999")] = {"pr_id": "demo-1", "pr_url": "", "github": {}}
        assert "ignored" in _post(port, hook, {"from_number": "+15559999999", "content": SENTENCE})
        assert state.notifier.sent == []  # a stranger's rule is never learned or answered

        state.threads[imessage.phone_key("+15550100001")] = {"pr_id": "demo-1", "pr_url": "", "github": {}}
        out = _post(port, hook, {"from_number": "+15550100001", "content": SENTENCE})
        assert out["action"] == "teach"
        deadline = time.monotonic() + 60
        while len(state.notifier.sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
        assert [t for _, t in state.notifier.sent] == [
            "Got it — turning that into a test…",
            "Learned: test_discount_over_100_is_free. It fails on demo-1, so demo-1 stays blocked."]
    finally:
        httpd.shutdown()
