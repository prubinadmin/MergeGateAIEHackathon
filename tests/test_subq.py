import io
import json
import os
import urllib.error

import pytest

from merge_gate import subq
from merge_gate.pr import PullRequest
from merge_gate.schema import Evidence, VerdictReport
from merge_gate.verify import verify

from helpers import git, write

PETER = ("Peter", "peter@example.com")
TAAZ = ("TAAZ", "taaz@example.com")
CODE = "def f(x):\n    a = x\n    b = a + 1\n    c = b * 2\n    return c\n"


@pytest.fixture
def pr(tmp_path, monkeypatch):
    """Peter wrote 3 of the changed lines, TAAZ 1, so blame ranks Peter first."""
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.setenv("SUBQ_API_KEY", "test-key")
    monkeypatch.setattr(subq.time, "sleep", lambda s: None)
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    write(repo, {"m.py": CODE})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "f", author=PETER)
    write(repo, {"m.py": CODE.replace("    c = b * 2\n", "    c = b * 3\n")})
    git(repo, "commit", "-qam", "tweak", author=TAAZ)
    git(repo, "checkout", "-q", "-b", "pr/1")
    write(repo, {"m.py": "def f(x):\n    return (x + 1) * 4\n"})
    git(repo, "commit", "-qam", "pr", author=("Agent", "a@bots.dev"))
    return PullRequest("p", repo, "main", "pr/1", title="t")


def fake_api(monkeypatch, answers):
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        if isinstance(answers, Exception):
            raise answers
        return io.BytesIO(json.dumps({"model": "subq-snap-1.1", "answers": answers(json.loads(req.data))}).encode())

    monkeypatch.setattr(subq.urllib.request, "urlopen", urlopen)
    return calls


def answer(body):
    if "owner" in body["questions"]:
        return {"owner": {"type": "choice", "choice": "c1", "probabilities": {"c0": 0.2, "c1": 0.8}, "confidence": 0.8}}
    return {"urgency": {"type": "score", "score": 0.9, "legend": {"0": "FYI", "1": "Page"},
                        "probabilities": {"0": 0.1, "1": 0.9}, "confidence": 0.8}}


def test_subq_choice_reorders_owners_and_records_routing(pr, monkeypatch):
    calls = fake_api(monkeypatch, answer)
    r = verify(pr, use_subq=True)
    assert [o.email for o in r.owners] == ["taaz@example.com", "peter@example.com"]
    assert (r.routed_by, r.route_confidence) == ("subq", 0.8)
    assert (r.urgency, r.urgency_p) == ("page", 0.9)
    req = calls[0]
    body = json.loads(req.data)
    assert req.full_url == "https://api.subq.ai/v1/systemone"
    assert req.get_header("Authorization") == "Bearer test-key"
    assert body["model"] == "subq-snap-1.1"
    assert set(body["questions"]["owner"]["criteria"]) == {"c0", "c1"}
    assert "b = a + 1" in body["state"]["history_of_changed_lines"]  # git log -L history is in context
    assert VerdictReport.from_dict(json.loads(r.to_json())).routed_by == "subq"


def test_urgency_fyi_when_unlikely(pr, monkeypatch):
    fake_api(monkeypatch, lambda b: {"urgency": {"type": "score", "score": 0.2, "probabilities": {"0": 0.8, "1": 0.2}}})
    assert subq.urgency(pr, []) == ("fyi", 0.2)


def test_http_error_falls_back_to_blame(pr, monkeypatch):
    err = urllib.error.HTTPError("u", 503, "down", {}, io.BytesIO(b"{}"))
    calls = fake_api(monkeypatch, err)
    r = verify(pr, use_subq=True)
    assert r.owners[0].email == "peter@example.com"
    assert (r.routed_by, r.route_confidence, r.urgency_p) == ("blame", None, None)
    assert len(calls) == 2 * 3  # both decisions retried 503 three times


def test_missing_key_falls_back_without_calling(pr, monkeypatch):
    monkeypatch.delenv("SUBQ_API_KEY")
    calls = fake_api(monkeypatch, answer)
    owners = verify(pr).owners  # use_llm off -> SubQ off
    chosen, conf = subq.choose_owner(pr, owners)
    assert (chosen.email, conf) == ("peter@example.com", None)
    block = Evidence(type="rule", id="R1", detail="d")
    assert subq.urgency(pr, [block]) == ("page", None)
    assert subq.urgency(pr, []) == ("fyi", None)
    assert calls == []


def test_old_report_json_still_loads():
    r = VerdictReport.from_dict({"pr_id": "x", "verdict": "PASS"})
    assert (r.routed_by, r.route_confidence, r.urgency, r.urgency_p) == ("blame", None, "", None)
