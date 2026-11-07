"""github_pr: query parsing, API resolution (mocked, no network) and a blame-capable clone from a local bare repo."""

import subprocess

import pytest

from merge_gate import github_pr
from merge_gate.demo import build_demo_repo
from merge_gate.github import GitHubError
from merge_gate.github_pr import ResolvedPR, materialize, parse_query, resolve
from merge_gate.owners import resolve_owners
from merge_gate.verify import verify


def _pr_json(full="psf/requests", number=42, size=1234):
    owner, _, repo = full.partition("/")
    return {
        "number": number, "title": "Fix retries", "body": "Closes #41: retries must back off.",
        "user": {"login": "someone"}, "base": {"ref": "main", "repo": {"full_name": full, "size": size}},
        "head": {"sha": "abc123"}, "html_url": f"https://github.com/{full}/pull/{number}",
    }


@pytest.mark.parametrize("q, want", [
    ("psf/requests#42", ("psf", "requests", 42)),
    ("psf/requests/pull/42", ("psf", "requests", 42)),
    ("https://github.com/psf/requests/pull/42", ("psf", "requests", 42)),
    ("https://github.com/psf/requests/pull/42/files", ("psf", "requests", 42)),
    ("psf/requests", ("psf", "requests", None)),
    ("vllm-project/vllm.git", ("vllm-project", "vllm", None)),
    ("vllm", None),
    ("not a query", None),
])
def test_parse_query(q, want):
    assert parse_query(q) == want


def test_resolve_bare_word_searches_then_takes_newest_open_pr(monkeypatch):
    calls = []

    def fake_api(path):
        calls.append(path)
        if path.startswith("/search/repositories"):
            assert "q=vllm" in path and "sort=stars" in path
            return {"total_count": 1, "items": [{"full_name": "vllm-project/vllm"}]}
        assert path == "/repos/vllm-project/vllm/pulls?state=open&sort=created&direction=desc&per_page=1"
        return [_pr_json("vllm-project/vllm", 9001)]

    monkeypatch.setattr(github_pr, "_api", fake_api)
    r = resolve("vllm")
    assert (r.owner, r.repo, r.number, r.base_ref, r.head_sha, r.author) == ("vllm-project", "vllm", 9001, "main", "abc123", "someone")
    assert r.pr_id == "gh:vllm-project/vllm#9001" and r.html_url.endswith("/pull/9001")
    assert len(calls) == 2


def test_resolve_direct_pr_and_errors(monkeypatch):
    monkeypatch.setattr(github_pr, "_api", lambda path: _pr_json() if path == "/repos/psf/requests/pulls/42" else pytest.fail(path))
    assert resolve("https://github.com/psf/requests/pull/42").number == 42

    monkeypatch.setattr(github_pr, "_api", lambda path: {"total_count": 0, "items": []})
    with pytest.raises(GitHubError, match="no GitHub repository matches"):
        resolve("zzqqxx-nothing")

    monkeypatch.setattr(github_pr, "_api", lambda path: [])
    with pytest.raises(GitHubError, match="no open pull requests"):
        resolve("psf/requests")


def test_materialize_refuses_huge_repos(tmp_path):
    r = ResolvedPR("o", "r", 1, "", "", "", "main", "x", "", size_kb=3 * 1024 * 1024)
    with pytest.raises(GitHubError, match="over 2 GB"):
        materialize(r, str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def _bare_with_pull_ref(tmp_path) -> tuple[str, str]:
    """A bare 'GitHub' holding the demo repo, with refs/pull/1/head -> pr/demo-1."""
    src = build_demo_repo(str(tmp_path / "src"))
    bare = str(tmp_path / "shop.git")
    subprocess.run(["git", "clone", "--quiet", "--bare", src, bare], check=True, capture_output=True)
    subprocess.run(["git", "-C", bare, "update-ref", "refs/pull/1/head", "refs/heads/pr/demo-1"], check=True, capture_output=True)
    sha = subprocess.run(["git", "-C", bare, "rev-parse", "refs/pull/1/head"], check=True, capture_output=True, text=True).stdout.strip()
    return bare, sha


def test_materialize_clone_is_diffable_blamable_and_verifiable(tmp_path):
    bare, sha = _bare_with_pull_ref(tmp_path)
    r = ResolvedPR("acme", "shop", 1, "Speed up apply_discount", "Make it faster without changing results.",
                   "coding-agent", "main", sha, "https://github.com/acme/shop/pull/1")
    pr = materialize(r, str(tmp_path), clone_url=lambda o, n: bare)

    assert pr.pr_id == "gh:acme/shop#1" and pr.repo_path.startswith(str(tmp_path))
    assert (pr.base_ref, pr.head_ref, pr.opened_by, pr.title) == ("origin/main", "pr-1", "coding-agent", "Speed up apply_discount")
    assert pr.git("rev-parse", pr.head_ref).strip() == sha
    assert pr.git("rev-parse", pr.base_ref).strip()
    assert "shop/pricing.py" in pr.changed_files() and "-    return max(0.0" in pr.diff()

    owners = resolve_owners(pr)
    assert owners and owners[0].name == "Peter" and owners[0].email == "peter@example.com"

    report = verify(pr, use_llm=False)
    assert report.pr_id == "gh:acme/shop#1" and report.verdict == "BLOCK"
    assert "R1_DELETED_TEST" in {e.id for e in report.evidence}


def test_materialize_cleans_up_on_failure(tmp_path):
    r = ResolvedPR("acme", "shop", 1, "", "", "", "main", "x", "")
    with pytest.raises(GitHubError, match="git clone failed"):
        materialize(r, str(tmp_path), clone_url=lambda o, n: str(tmp_path / "does-not-exist.git"))
    assert list(tmp_path.iterdir()) == []
