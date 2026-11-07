import json
import os
import subprocess

from merge_gate.bench import Case, Label, load_cases, score
from merge_gate.cli import main, stub_report
from merge_gate.notify import format_message, handle_reply, parse_reply
from merge_gate.pr import PullRequest
from merge_gate.schema import Evidence, Owner, VerdictReport
from merge_gate.verify import decide, verify


# --- verdict -----------------------------------------------------------------

def test_decide_is_deterministic():
    blk = Evidence(type="rule", id="R1_DELETED_TEST", detail="x")
    rev = Evidence(type="rule", id="R6_OUT_OF_SCOPE_TEST_EDIT", detail="y", severity="review")
    assert decide([]) == "PASS"
    assert decide([rev]) == "REVIEW"
    assert decide([rev, blk]) == "BLOCK"


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "a@example.com")
    run("config", "user.name", "A")
    (repo / "m.py").write_text("def f():\n    return 1\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    run("checkout", "-q", "-b", "pr/1")
    (repo / "m.py").write_text("def f():\n    return 2\n")
    run("commit", "-q", "-am", "change")
    return str(repo)


def test_verify_runs_end_to_end_on_a_real_repo(tmp_path):
    pr = PullRequest(pr_id="t1", repo_path=_git_repo(tmp_path), base_ref="main", head_ref="pr/1")
    assert pr.changed_files() == ["m.py"]
    assert "return 2" in pr.diff()
    r = verify(pr)
    assert r.verdict == "PASS"  # no rules wired yet
    assert r.run_hash.startswith("sha256:")


# --- iMessage contract -------------------------------------------------------

def test_parse_reply():
    assert parse_reply("block").command == "BLOCK"
    assert parse_reply("  Why? ").command == "WHY"
    assert parse_reply("why").command == "WHY"
    assert parse_reply("false alarm, that path is dead code").command == "FALSE_ALARM"
    assert parse_reply("lol").command == "UNKNOWN"


def test_ok_never_merges():
    r = stub_report("demo-1")
    a = handle_reply(r, parse_reply("OK"), "https://github.com/x/y/pull/1")
    assert a.kind == "send_text"
    assert "github.com" in a.text


def test_block_blocks():
    assert handle_reply(stub_report("d"), parse_reply("BLOCK")).kind == "block_pr"


def test_message_names_owner_and_evidence():
    text = format_message(stub_report("demo-1"))
    assert "Peter" in text and "BLOCKED" in text and "-5.0" in text


def test_cli_notify(tmp_path, capsys):
    path = tmp_path / "r.json"
    path.write_text(stub_report("demo-1").to_json(), encoding="utf-8")
    assert main(["notify", str(path), "--reply", "BLOCK"]) == 0
    assert "action: block_pr" in capsys.readouterr().out


# --- benchmark contract ------------------------------------------------------

def test_score():
    pr = lambda i: PullRequest(pr_id=i, repo_path=".", base_ref="main", head_ref=i)
    cases = [
        Case(pr("bad"), Label("deleted_test", "BLOCK", "peter@example.com", "heldout")),
        Case(pr("ok"), Label("clean", "PASS", "taaz@example.com", "heldout")),
    ]
    reports = {
        "bad": stub_report("bad"),  # BLOCK, owner Peter
        "ok": VerdictReport(pr_id="ok", verdict="PASS",
                            owners=[Owner("TAAZ", "taaz@example.com", 3, "2026-01-01")]),
    }
    m = score(cases, reports)
    assert m["catch_rate"] == 1.0
    assert m["false_block_rate"] == 0.0
    assert m["routing_accuracy"] == 1.0


def test_load_cases(tmp_path):
    case_dir = tmp_path / "cases" / "pr01"
    case_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(json.dumps({
        "pr_id": "pr01", "repo": "target_repo", "base_ref": "main", "head_ref": "pr/01",
        "issue_text": "x",
        "label": {"kind": "clean", "true_verdict": "PASS",
                  "true_owner_email": "a@example.com", "split": "train"},
    }))
    cases = load_cases(str(tmp_path))
    assert len(cases) == 1
    assert cases[0].pr.repo_path == os.path.normpath(str(tmp_path / "target_repo"))
    assert load_cases(str(tmp_path), "heldout") == []
