import json
import os

import pytest

from merge_gate import store
from merge_gate.bench import Case, Label
from merge_gate.learn import GateConfig, learn_round, load_current, propose
from merge_gate.pr import PullRequest
from merge_gate.rsi import SOURCES, LearnerPolicy, load_policy, meta_round, neighbours
from merge_gate.schema import Evidence, Owner, VerdictReport


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "log.jsonl"))
    monkeypatch.chdir(tmp_path)  # a learner_versions/ or gate_versions/ in the repo root must not leak in
    return tmp_path


def ev(rule, sev):
    return Evidence(type="rule", id=rule, detail=rule, severity=sev)


def case(pr_id, true_verdict, split, kind="logic_bug"):
    return Case(PullRequest(pr_id, ".", "main", pr_id), Label(kind, true_verdict, "o@example.com", split))


def raw_report(pr_id, *evidence):
    from merge_gate.verify import decide

    return VerdictReport(pr_id=pr_id, verdict=decide(list(evidence)), evidence=list(evidence), owners=[Owner("O", "o@example.com", 1, "2026-01-01")])


def noisy_rule_scenario():
    """R9 blocks a clean train PR nobody replied FALSE ALARM to, and the same R9 false-blocks a held-out clean PR.
    Today's learner (owner feedback + train misses) proposes nothing; a learner with the noisy_rule source fixes it."""
    cases = [
        case("t1", "BLOCK", "train"),                   # R6 block: caught
        case("t2", "PASS", "train", "clean"),          # R9 block: a false block with no owner reply
        case("h1", "BLOCK", "heldout"),                 # R6 block: caught
        case("h2", "PASS", "heldout", "clean"),        # R9 block: held-out false block
    ]
    raw = {
        "t1": raw_report("t1", ev("R6", "block")),
        "t2": raw_report("t2", ev("R9", "block")),
        "h1": raw_report("h1", ev("R6", "block")),
        "h2": raw_report("h2", ev("R9", "block")),
    }
    return cases, raw


def test_meta_round_adopts_the_learner_whose_learned_gate_does_better_on_heldout(isolated):
    cases, raw = noisy_rule_scenario()
    pd, gd = str(isolated / "learner"), str(isolated / "gate")
    result = meta_round(cases, raw, false_alarms=[], policy=LearnerPolicy(), dir_=pd, gate_dir=gd)

    assert result["from"] == "p1" and result["to"] == "p2" and result["adopted"] == "add source noisy_rule"
    assert result["heldout_before"]["false_block_rate"] == 1.0 and result["heldout_after"]["false_block_rate"] == 0.0
    assert result["heldout_after"]["catch_rate"] == 1.0
    by = {c["policy_change"]: c for c in result["candidates"]}
    assert by["add source noisy_rule"]["adopted_so_far"] and by["add source noisy_rule"]["gate_change"].startswith("R9 blocked clean t2")
    assert not by["step 1 -> 2"]["adopted_so_far"] and by["step 1 -> 2"]["gate_change"] is None  # same as today: nothing to propose

    new = load_policy(pd)
    assert new.version == "p2" and new.parent == "p1" and new.sources == ["false_alarm", "missed_train", "noisy_rule"]
    assert sorted(os.listdir(pd)) == ["current.json", "p1.json", "p2.json"]
    assert store.read(kind="learner_version")[-1]["data"]["to"] == "p2"
    # trials ran in scratch dirs: the real gate versions were not touched and no trial entered the run log
    assert not os.path.exists(gd) and load_current(gd).version == "v1"
    assert store.read(kind="gate_version") == []


def test_the_adopted_learner_is_what_learn_round_runs_next(isolated):
    cases, raw = noisy_rule_scenario()
    pd, gd = str(isolated / "learner"), str(isolated / "gate")
    meta_round(cases, raw, false_alarms=[], policy=LearnerPolicy(), dir_=pd, gate_dir=gd)

    before = learn_round(cases, raw, false_alarms=[], cfg=GateConfig(), dir_=gd, policy=LearnerPolicy())
    assert before["adopted"] is None  # the old learner still cannot see the problem
    after = learn_round(cases, raw, false_alarms=[], cfg=GateConfig(), dir_=gd, policy=load_policy(pd))
    assert after["to"] == "v2" and after["adopted"].startswith("R9 blocked clean t2") and after["heldout_after"]["false_block_rate"] == 0.0
    assert load_current(gd).rule_severity == {"R9": "review"}


def test_no_neighbour_beats_the_incumbent_means_the_learner_stays(isolated):
    cases = [case("t1", "BLOCK", "train"), case("h1", "BLOCK", "heldout"), case("h2", "PASS", "heldout", "clean")]
    raw = {"t1": raw_report("t1", ev("R6", "review")), "h1": raw_report("h1", ev("R6", "review")), "h2": raw_report("h2")}
    pd = str(isolated / "learner")
    result = meta_round(cases, raw, false_alarms=[], policy=LearnerPolicy(), dir_=pd, gate_dir=str(isolated / "gate"))
    assert result["heldout_before"]["catch_rate"] == 1.0  # today's learner already learns the perfect gate here
    assert result["to"] == "p1" and result["adopted"] is None and not any(c["adopted_so_far"] for c in result["candidates"])
    assert sorted(os.listdir(pd)) == ["current.json", "p1.json"]


def test_a_policy_can_change_what_is_proposed_never_what_is_accepted():
    # the constitution: no knob for the held-out split, the adoption floor or the train veto exists to be learned
    assert set(LearnerPolicy.__dataclass_fields__) == {"version", "step", "sources", "combine", "parent", "change"}
    assert all(n.change for n in neighbours(LearnerPolicy()))
    assert "drop source" not in " ".join(n.change for n in neighbours(LearnerPolicy(sources=["missed_train"])))  # never a learner that cannot learn


def test_a_broken_policy_file_never_takes_down_learning(isolated, capsys):
    pd = str(isolated / "learner")
    os.makedirs(pd)
    with open(os.path.join(pd, "current.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "p7"}, f)
    with open(os.path.join(pd, "p7.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "p7", "step": -1, "sources": ["false_alarm"], "combine": False, "parent": "", "change": ""}, f)
    assert load_policy(pd) == LearnerPolicy()  # falls back to today's learner, with a warning, instead of crashing `learn`
    assert "ignoring unreadable learner policy" in capsys.readouterr().err
    for bad in ({"step": 0}, {"step": -1}, {"sources": []}, {"sources": ["heldout"]}):
        with pytest.raises(ValueError):
            LearnerPolicy(**bad)


def test_the_widest_policy_still_cannot_adopt_what_the_floor_rejects(isolated):
    # test_learn's scenario: lowering R7 lets h3 through. With every knob maxed the learner proposes more, the floor still refuses.
    cases = [case("t1", "BLOCK", "train"), case("t2", "PASS", "train", "clean"),
             case("h1", "BLOCK", "heldout"), case("h2", "PASS", "heldout", "clean"), case("h3", "BLOCK", "heldout")]
    raw = {"t1": raw_report("t1", ev("R6", "review")), "t2": raw_report("t2", ev("R7", "block")),
           "h1": raw_report("h1", ev("R6", "review")), "h2": raw_report("h2"), "h3": raw_report("h3", ev("R7", "block"))}
    wide = LearnerPolicy(step=2, sources=list(SOURCES), combine=True)
    gd = str(isolated / "gate")
    result = learn_round(cases, raw, false_alarms=["t2"], cfg=GateConfig(), dir_=gd, policy=wide)
    assert len(result["candidates"]) > 2 and any(" + " in c["change"] for c in result["candidates"])  # singles and a pair
    assert not any(c["adopted_so_far"] for c in result["candidates"] if "R7" in c["change"])        # every R7 change rolled back
    assert load_current(gd).rule_severity == {"R6": "block"}


def test_step_two_and_combine_widen_the_proposals():
    train = [case("t1", "BLOCK", "train"), case("t2", "PASS", "train", "clean")]
    raw = {"t1": raw_report("t1", ev("R6", "review")), "t2": raw_report("t2", ev("R7", "block"), ev("R8", "block"))}
    cfg = GateConfig(rule_severity={"R6": "off"})
    one = propose(cfg, raw, train, false_alarms=["t2"], policy=LearnerPolicy())
    two = propose(cfg, raw, train, false_alarms=["t2"], policy=LearnerPolicy(step=2, combine=True))
    assert {c.rule_severity["R6"] for c in one if c.change.startswith("t1")} == {"review"}
    assert {c.rule_severity["R6"] for c in two if c.change.startswith("t1")} == {"block"}
    pair = [c for c in two if " + " in c.change and "R7" in c.change and "R8" in c.change]
    assert pair and all(c.rule_severity["R7"] == "off" and c.rule_severity["R8"] == "off" for c in pair)
