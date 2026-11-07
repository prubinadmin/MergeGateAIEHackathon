import json

import pytest

from merge_gate.cli import main, stub_report
from merge_gate.schema import VerdictReport, run_hash, validate


def test_stub_report_is_valid_and_round_trips():
    r = stub_report("demo-1")
    d = json.loads(r.to_json())
    validate(d)
    assert VerdictReport.from_dict(d) == r


def test_block_without_evidence_is_rejected():
    with pytest.raises(ValueError):
        validate({"pr_id": "x", "verdict": "BLOCK", "evidence": []})


def test_unknown_verdict_is_rejected():
    with pytest.raises(ValueError):
        validate({"pr_id": "x", "verdict": "MAYBE"})


def test_run_hash_is_order_independent():
    assert run_hash({"a": 1, "b": 2}) == run_hash({"b": 2, "a": 1})
    assert run_hash({"a": 1}) != run_hash({"a": 2})


def test_cli_stub(capsys):
    assert main(["verify", "--pr", "demo-1", "--stub"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "BLOCK"
    assert out["owners"][0]["name"] == "Peter"
