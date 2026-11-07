"""github_pr: query parsing, API resolution (HTTP faked at urllib, no network) and a blame-capable clone from a local bare repo."""

import io
import json
import subprocess
import urllib.error
import urllib.request

import pytest

from merge_gate import github
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


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_github(monkeypatch, routes, token="test-token"):
    """Fake api.github.com at the urllib boundary: routes(path) -> JSON body (or raises). Returns the calls made."""
    calls: list[tuple[str, str | None]] = []
    if token:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    else:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

    def urlopen(req, timeout=None):
        assert req.full_url.startswith(github.API)
        calls.append((req.full_url[len(github.API):], req.get_header("Authorization")))
        return _Resp(json.dumps(routes(calls[-1][0])).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


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
    def routes(path):
        if path.startswith("/search/repositories"):
            assert "q=vllm" in path and "sort=stars" in path
            return {"total_count": 1, "items": [{"full_name": "vllm-project/vllm"}]}
        assert path == "/repos/vllm-project/vllm/pulls?state=open&sort=created&direction=desc&per_page=1"
        return [_pr_json("vllm-project/vllm", 9001)]

    calls = _fake_github(monkeypatch, routes)
    r = resolve("vllm")
    assert (r.owner, r.repo, r.number, r.base_ref, r.head_sha, r.author) == ("vllm-project", "vllm", 9001, "main", "abc123", "someone")
    assert r.pr_id == "gh:vllm-project/vllm#9001" and r.html_url.endswith("/pull/9001")
    assert len(calls) == 2 and {auth for _, auth in calls} == {"Bearer test-token"}  # the token reaches GitHub, nothing else


def test_resolve_direct_pr_and_errors(monkeypatch):
    _fake_github(monkeypatch, lambda path: _pr_json() if path == "/repos/psf/requests/pulls/42" else pytest.fail(path))
    assert resolve("https://github.com/psf/requests/pull/42").number == 42

    _fake_github(monkeypatch, lambda path: {"total_count": 0, "items": []})
    with pytest.raises(GitHubError, match="no GitHub repository matches"):
        resolve("zzqqxx-nothing")

    _fake_github(monkeypatch, lambda path: [])
    with pytest.raises(GitHubError, match="no open pull requests"):
        resolve("psf/requests")

    def not_found(path):
        raise urllib.error.HTTPError(github.API + path, 404, "Not Found", None, io.BytesIO(b'{"message":"Not Found"}'))

    _fake_github(monkeypatch, not_found)
    with pytest.raises(GitHubError, match="HTTP 404"):
        resolve("psf/requests#1")



def _no_gh_cli(monkeypatch):
    """Simulate a machine without the gh CLI: github._token()'s `gh auth token` fallback must find nothing."""
    import subprocess as _sp

    real_run = _sp.run

    def run(args, *a, **kw):
        if args and args[0] == "gh":
            raise FileNotFoundError("gh: command not found")
        return real_run(args, *a, **kw)

    monkeypatch.setattr(_sp, "run", run)


def test_resolve_without_a_token_calls_github_anonymously(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here, so load_dotenv() finds no token
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    _no_gh_cli(monkeypatch)  # and no `gh auth token` fallback either
    calls = _fake_github(monkeypatch, lambda path: _pr_json(), token="")
    assert resolve("psf/requests#42").number == 42
    assert calls == [("/repos/psf/requests/pulls/42", None)]


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


def test_materialize_times_out_and_cleans_up(tmp_path):
    bare, _ = _bare_with_pull_ref(tmp_path)
    r = ResolvedPR("acme", "shop", 1, "", "", "", "main", "x", "")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(GitHubError, match="longer than 0s"):
        materialize(r, str(work), clone_url=lambda o, n: bare, timeout_s=0)
    assert list(work.iterdir()) == []
