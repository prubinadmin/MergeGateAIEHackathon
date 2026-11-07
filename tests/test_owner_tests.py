"""Owner replies become tests. The model is replaced by fixed text: no network, no real iMessage."""

import hashlib
import json
import os
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
NAME = "test_discount_over_100_is_free"


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
    assert t.test_name == NAME
    assert SENTENCE in calls[0] and "def apply_discount" in calls[0]
    assert "test_discount_never_negative" not in calls[0]  # never shown the PR's tests

    assert t.id == f"peter_example_com/{NAME}_{hashlib.sha256(SENTENCE.encode()).hexdigest()[:8]}"
    assert t.file == t.id + ".py"
    assert "apply_discount(10, 150)" in open(f"owner_tests/{t.file}").read()
    [entry] = owner_tests.load_registry()
    assert {k: entry[k] for k in ("owner", "sentence", "pr_id", "passes_base", "fails_head")} == {
        "owner": PETER, "sentence": SENTENCE, "pr_id": "demo-1", "passes_base": True, "fails_head": True}
    assert entry["created_at"] and entry["run_hash"].startswith("sha256:") and entry["files"] == ["shop/pricing.py"]
    [rec] = store.read(kind="owner_test")
    assert rec["data"]["accepted"] and rec["data"]["file"] == t.file
    assert owner_tests.outcome_text(t) == f"Learned: {NAME}. It fails on demo-1, so demo-1 stays blocked."


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


@pytest.mark.parametrize("text", [
    "please block this", "don't merge this", "Don’t merge this yet", "do not merge, prices must never be negative",
    "hold this PR", "stop, this is wrong", "reject it", "revert that", "ok but don't merge until Monday",
])
def test_stop_wording_is_block_never_teach(text):
    assert parse_reply(text).command == "BLOCK"


@pytest.mark.parametrize("text, cmd", [
    ("looks good thanks", "UNKNOWN"),  # not a rule: no model call, nothing stored
    ("pricing must never round before tax", "TEACH"),
    ("totals should be rounded to cents", "TEACH"),
    ("a cart can't hold more than 99 units", "BLOCK"),  # 'hold' -> easy to stop wins
    ("quantity >= 1", "TEACH"),
    ("RULE: prices are in cents", "TEACH"),  # explicit prefix always teaches
    ("rule prices are in cents", "TEACH"),
    ("RULE:", "UNKNOWN"),
    (f"FORGET {NAME}", "FORGET"),
])
def test_only_rule_shaped_text_teaches(text, cmd):
    assert parse_reply(text).command == cmd


def test_free_text_is_teach_and_commands_still_work():
    r = parse_reply("pricing must never round before tax")
    assert (r.command, r.note) == ("TEACH", "pricing must never round before tax")
    assert parse_reply("RULE: prices are in cents").note == "prices are in cents"
    assert parse_reply("BLOCK rounding").command == "BLOCK"
    assert parse_reply("why?").command == "WHY"
    assert parse_reply("false alarm, fine").command == "FALSE_ALARM"
    assert parse_reply("ok").command == "OK"
    assert parse_reply("   ").command == "UNKNOWN"
    assert parse_reply("thanks!").command == "UNKNOWN"
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

    report = verify(demo["demo-1"], use_llm=False, config=None)  # stored rules run without Muse
    [ev] = [e for e in report.evidence if e.id.startswith("owner::")]
    assert ev.id == f"owner::peter@example.com::{NAME}" and ev.severity == "block"
    assert SENTENCE in ev.detail and report.verdict == "BLOCK"
    # untouched file -> the rule isn't run
    assert not [e for e in verify(demo["demo-3"], use_llm=False, config=None).evidence if e.id.startswith("owner::")]
    # learned gate config can never mute an owner's rule
    cfg = GateConfig(rule_severity={"owner": "off", ev.id: "review"})
    assert apply_config([ev], cfg)[0].severity == "block"


def test_free_text_is_never_written_into_test_source(demo, monkeypatch):
    model(monkeypatch, GOOD)
    evil = SENTENCE + "\nimport os; os.system('x')\r os.system('y')"
    t = owner_tests.rule_to_test(demo["demo-1"], "peter@example.com\nimport os", evil)
    assert t.accepted
    stored = open(f"owner_tests/{t.file}", newline="").read()
    assert stored == t.source and "os.system" not in stored and "import os" not in stored and "Taught" not in stored
    [entry] = owner_tests.load_registry()
    assert entry["sentence"] == evil.strip()  # the sentence lives only in the registry
    assert entry["sha256"] == hashlib.sha256(stored.encode()).hexdigest()


def test_tampered_stored_test_is_skipped_and_logged(demo, monkeypatch):
    model(monkeypatch, GOOD)
    t = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    assert owner_tests.check_owner_tests(demo["demo-1"])  # untouched: block evidence
    with open(f"owner_tests/{t.file}", "a", encoding="utf-8") as f:
        f.write("\nimport os\nos.system('touch pwned')\n")
    assert owner_tests.check_owner_tests(demo["demo-1"]) == []
    assert store.read(kind="owner_test_skipped")[0]["data"]["file"] == t.file


def test_base_runs_once_per_base_commit(demo, monkeypatch):
    model(monkeypatch, GOOD)
    owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    refs, real = [], owner_tests.run_tests
    monkeypatch.setattr(owner_tests, "run_tests", lambda repo, ref, *a: refs.append(ref) or real(repo, ref, *a))
    first, second = owner_tests.check_owner_tests(demo["demo-1"]), owner_tests.check_owner_tests(demo["demo-1"])
    assert first and [e.id for e in first] == [e.id for e in second]  # same block evidence both times
    pr = demo["demo-1"]
    assert refs == [pr.git("rev-parse", pr.base_ref).strip(), pr.head_ref, pr.head_ref]  # base ran once, not twice


def test_one_broken_stored_test_does_not_hide_the_others(demo, monkeypatch):
    model(monkeypatch, GOOD)
    good = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    broken = "import no_such_module_xyz\n\n\ndef test_broken():\n    assert True\n"
    entry = {**good.entry(), "id": "taaz_example_com/test_broken_00000000", "owner": "taaz@example.com",
             "sentence": "orders must be positive", "test_name": "test_broken",
             "file": "taaz_example_com/test_broken_00000000.py", "sha256": hashlib.sha256(broken.encode()).hexdigest()}
    os.makedirs("owner_tests/taaz_example_com")
    with open(f"owner_tests/{entry['file']}", "w", encoding="utf-8", newline="") as f:
        f.write(broken)
    owner_tests._save_registry("owner_tests", [entry] + owner_tests.load_registry())  # broken one runs first

    ev = {e.id: e for e in owner_tests.check_owner_tests(demo["demo-1"])}
    assert ev[f"owner::peter@example.com::{NAME}"].severity == "block"
    assert ev["owner::taaz@example.com::test_broken"].severity == "review"  # reported, not silently skipped
    assert "no longer runs" in ev["owner::taaz@example.com::test_broken"].detail


def test_rules_never_collide_and_can_be_removed(demo, monkeypatch, capsys):
    from merge_gate.cli import main

    model(monkeypatch, GOOD)  # same generated test name for different sentences and owners
    a = owner_tests.rule_to_test(demo["demo-1"], PETER, SENTENCE)
    b = owner_tests.rule_to_test(demo["demo-1"], PETER, "prices must never go below zero")
    c = owner_tests.rule_to_test(demo["demo-1"], "peter@other.example", SENTENCE)
    assert len({a.file, b.file, c.file}) == 3 and len(owner_tests.load_registry()) == 3
    assert not [n for n in os.listdir("owner_tests") if n.startswith(".registry-")]  # temp file was replaced

    assert main(["owner-tests", "list"]) == 0
    assert a.id in capsys.readouterr().out
    assert main(["owner-tests", "remove", a.id]) == 0
    assert not os.path.exists(f"owner_tests/{a.file}") and len(owner_tests.load_registry()) == 2
    assert main(["owner-tests", "remove", "nope"]) == 1
    assert store.read(kind="owner_test_removed")[0]["data"]["id"] == a.id
    # by test name, an owner only ever removes their own rule
    gone = owner_tests.remove(NAME, owner="peter@other.example")
    assert [e["id"] for e in gone] == [c.id] and [e["id"] for e in owner_tests.load_registry()] == [b.id]


def _post(port, path, body, origin=None):
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read())}


def test_reply_and_webhook_teach_and_forget_end_to_end(demo, monkeypatch):
    from merge_gate import serve

    secret = "s" * 24
    monkeypatch.setenv("SENDBLUE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("OWNER_PHONES", json.dumps({PETER: "+15550100001"}))
    calls = model(monkeypatch, GOOD)
    state = serve.State(use_llm=False)
    state.notifier = imessage.ConsoleNotifier()  # never a real iMessage
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        # unauthenticated HTTP can never teach: no model call, nothing stored
        calls_before = len(calls)
        ui = "http://localhost:3000"  # /api/reply only serves the War Room page
        assert _post(port, "/api/reply", {"pr_id": "demo-1", "text": SENTENCE})["status"] == 403
        out = _post(port, "/api/reply", {"pr_id": "demo-1", "text": SENTENCE}, origin=ui)
        assert out == {"status": 403, "error": "teach requires a verified owner (reply by iMessage)"}
        assert len(calls) == calls_before and owner_tests.load_registry() == []
        assert _post(port, "/api/reply", {"pr_id": "demo-1", "text": "WHY"}, origin=ui)["action"] == "send_text"

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
            f"Learned: {NAME}. It fails on demo-1, so demo-1 stays blocked."]
        assert len(owner_tests.load_registry()) == 1  # the verified phone did teach

        assert _post(port, "/api/reply", {"pr_id": "demo-1", "text": f"FORGET {NAME}"})["status"] == 403
        assert "ignored" in _post(port, hook, {"from_number": "+15559999999", "content": f"FORGET {NAME}"})
        assert len(owner_tests.load_registry()) == 1  # nobody but the owner's phone can forget
        out = _post(port, hook, {"from_number": "+15550100001", "content": f"FORGET {NAME}"})
        assert out["action"] == "forget" and owner_tests.load_registry() == []
        assert state.notifier.sent[-1][1] == f'Forgot: {NAME} ("{SENTENCE}")'
    finally:
        httpd.shutdown()
