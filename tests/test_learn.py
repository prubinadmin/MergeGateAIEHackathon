import json
import os

import pytest

from merge_gate import learn, store
from merge_gate.bench import Case, Label
from merge_gate.learn import GateConfig, apply_config, learn_round, load_current
from merge_gate.pr import PullRequest
from merge_gate.schema import Evidence, Owner, VerdictReport


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    return tmp_path


def ev(rule, sev):
    return Evidence(type="rule", id=rule, detail=rule, severity=sev)


def case(pr_id, true_verdict, split, kind="logic_bug"):
    return Case(PullRequest(pr_id, ".", "main", pr_id), Label(kind, true_verdict, "o@example.com", split))


def raw_report(pr_id, *evidence):
    from merge_gate.verify import decide

    return VerdictReport(pr_id=pr_id, verdict=decide(list(evidence)), evidence=list(evidence), owners=[Owner("O", "o@example.com", 1, "2026-01-01")])


def test_apply_config_changes_severity_and_drops_off():
    out = apply_config([ev("R6", "review"), ev("R7", "block")], GateConfig(rule_severity={"R6": "block", "R7": "off"}))
    assert [(e.id, e.severity) for e in out] == [("R6", "block")]


def scenario():
    cases = [
        case("t1", "BLOCK", "train"),                   # R6 only fired, as review -> missed
        case("t2", "PASS", "train", "clean"),          # R7 fired: owner says false alarm
        case("h1", "BLOCK", "heldout"),                 # R6 review: missed today
        case("h2", "PASS", "heldout", "clean"),
        case("h3", "BLOCK", "heldout"),                 # only R7 catches this one
    ]
    raw = {
        "t1": raw_report("t1", ev("R6", "review")),
        "t2": raw_report("t2", ev("R7", "block")),
        "h1": raw_report("h1", ev("R6", "review")),
        "h2": raw_report("h2"),
        "h3": raw_report("h3", ev("R7", "block")),
    }
    return cases, raw


def test_keeps_a_change_that_helps_on_heldout_and_rolls_back_one_that_hurts(isolated):
    cases, raw = scenario()
    d = str(isolated / "versions")
    result = learn_round(cases, raw, false_alarms=["t2"], cfg=GateConfig(), dir_=d)

    by_change = {c["change"].split(";")[1].strip(): c for c in result["candidates"]}
    assert not by_change["R7 block -> review"]["adopted_so_far"]   # would let h3 through: rolled back
    assert by_change["R6 review -> block"]["adopted_so_far"]       # catches h1, no new false blocks: kept

    assert result["from"] == "v1" and result["to"] == "v2"
    assert result["heldout_before"]["catch_rate"] == 0.5
    assert result["heldout_after"]["catch_rate"] == 1.0
    assert result["heldout_after"]["false_block_rate"] == 0.0

    cur = load_current(d)
    assert cur.version == "v2" and cur.rule_severity == {"R6": "block"} and cur.parent == "v1"
    assert sorted(os.listdir(d)) == ["current.json", "v1.json", "v2.json"]
    assert store.read(kind="gate_version")[-1]["data"]["to"] == "v2"


def test_nothing_improves_means_no_new_version(isolated):
    cases = [case("t1", "PASS", "train", "clean"), case("h1", "PASS", "heldout", "clean")]
    raw = {"t1": raw_report("t1"), "h1": raw_report("h1")}
    d = str(isolated / "versions")
    result = learn_round(cases, raw, false_alarms=[], cfg=GateConfig(), dir_=d)
    assert result["to"] == "v1" and result["adopted"] is None
    assert load_current(d).version == "v1"


def test_false_alarm_feedback_is_read_from_owner_replies(isolated):
    store.log_reply("demo-3", "Michael", "FALSE_ALARM", "false alarm", "log_false_alarm")
    store.log_reply("demo-1", "Peter", "BLOCK", "block", "block_pr")
    assert learn.false_alarms_from_log() == ["demo-3"]


def test_false_alarm_can_lower_a_spec_test_class_but_never_an_owner_rule(isolated):
    issue = Evidence(type="failing_test", id="gate::test_issue_x", detail="x", severity="block")
    owner_rule = Evidence(type="rule", id="owner::no_sleep", detail="owner taught", severity="block")
    cases = [case("t1", "PASS", "train", "clean"), case("h1", "PASS", "heldout", "clean"), case("h2", "BLOCK", "heldout")]
    raw = {"t1": raw_report("t1", issue, owner_rule), "h1": raw_report("h1", issue), "h2": raw_report("h2", ev("R7", "block"))}
    result = learn_round(cases, raw, false_alarms=["t1"], cfg=GateConfig(), dir_=str(isolated / "versions"))
    changes = [c["change"].split(";")[1].strip() for c in result["candidates"]]
    assert "gate::test_issue block -> review" in changes      # the learner raised it, so FALSE ALARM can lower it
    assert not any(ch.startswith("owner::") for ch in changes)  # an owner's own rule is never proposed down
    assert result["adopted"].endswith("gate::test_issue block -> review")
    assert result["heldout_after"]["false_block_rate"] == 0.0


def test_candidate_that_blocks_a_clean_train_case_is_vetoed(isolated):
    cases = [
        case("t1", "BLOCK", "train"),              # R6 review: missed
        case("t2", "PASS", "train", "clean"),      # R6 review fired here too: raising R6 would block a known-clean PR
        case("h1", "BLOCK", "heldout"),            # R6 review: missed
        case("h2", "PASS", "heldout", "clean"),
    ]
    raw = {"t1": raw_report("t1", ev("R6", "review")), "t2": raw_report("t2", ev("R6", "review")),
           "h1": raw_report("h1", ev("R6", "review")), "h2": raw_report("h2")}
    d = str(isolated / "versions")
    result = learn_round(cases, raw, false_alarms=[], cfg=GateConfig(), dir_=d)
    (cand,) = result["candidates"]
    assert cand["change"].endswith("R6 review -> block")
    assert cand["heldout"]["catch_rate"] == 1.0 and cand["heldout"]["false_block_rate"] == 0.0  # held-out alone would adopt it
    assert cand["train_false_block_rate"] == 1.0 and not cand["adopted_so_far"]                  # train clean PR vetoes it
    assert result["adopted"] is None and load_current(d).version == "v1"


def test_spec_test_classes_are_tunable_like_rules(isolated):
    issue = Evidence(type="failing_test", id="gate::test_issue_x", detail="x", severity="review")
    cases = [case("t1", "BLOCK", "train"), case("h1", "BLOCK", "heldout"), case("h2", "PASS", "heldout", "clean")]
    raw = {"t1": raw_report("t1", issue), "h1": raw_report("h1", issue), "h2": raw_report("h2")}
    result = learn_round(cases, raw, false_alarms=[], cfg=GateConfig(), dir_=str(isolated / "versions"))
    assert result["adopted"].endswith("gate::test_issue review -> block")
    assert result["heldout_after"]["catch_rate"] == 1.0
