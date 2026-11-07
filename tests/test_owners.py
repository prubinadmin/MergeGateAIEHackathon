import os
import subprocess

from merge_gate.owners import base_line_ranges, resolve_owners
from merge_gate.pr import PullRequest


def _commit(repo, who, date, files, msg="c"):
    for p, body in files.items():
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text(body)
    env = {**os.environ, "GIT_AUTHOR_NAME": who, "GIT_AUTHOR_EMAIL": f"{who.lower()}@example.com",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "x@example.com"}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg], check=True, env=env)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    # Peter wrote pricing 8 months ago; TAAZ rewrote one line last week
    _commit(repo, "Peter", "2026-03-01T12:00:00", {"pricing.py": "a = 1\nb = 2\nc = 3\nd = 4\n",
                                                    "CODEOWNERS": "docs/ michael@example.com\n"})
    _commit(repo, "TAAZ", "2026-11-01T12:00:00", {"pricing.py": "a = 1\nb = 2\nc = 30\nd = 4\n"})
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "pr"], check=True)
    return repo


def _pr(repo, files):
    _commit(repo, "Agent", "2026-11-07T12:00:00", files, "pr")
    return PullRequest(pr_id="p", repo_path=str(repo), base_ref="main", head_ref="pr")


def test_modified_lines_go_to_their_author(tmp_path):
    repo = _repo(tmp_path)
    owners = resolve_owners(_pr(repo, {"pricing.py": "a = 10\nb = 20\nc = 30\nd = 4\n"}))
    assert owners[0].email == "peter@example.com" and owners[0].lines == 2
    assert owners[0].last_touched == "2026-03-01" and owners[0].score == 1.0


def test_recency_beats_raw_line_count(tmp_path):
    repo = _repo(tmp_path)
    # touches Peter's line b (8 months old) and TAAZ's line c (1 week old): one line each
    owners = resolve_owners(_pr(repo, {"pricing.py": "a = 1\nb = 99\nc = 99\nd = 4\n"}))
    assert [o.email for o in owners] == ["taaz@example.com", "peter@example.com"]
    assert owners[0].score > owners[1].score and round(sum(o.score for o in owners), 2) == 1.0


def test_pure_insertion_blames_the_line_it_follows(tmp_path):
    repo = _repo(tmp_path)
    owners = resolve_owners(_pr(repo, {"pricing.py": "a = 1\nb = 2\nc = 30\nnew = 0\nd = 4\n"}))
    assert owners[0].email == "taaz@example.com"


def test_new_file_falls_back_to_codeowners(tmp_path):
    repo = _repo(tmp_path)
    owners = resolve_owners(_pr(repo, {"docs/guide.md": "hi\n"}))
    assert [o.email for o in owners] == ["michael@example.com"]


def test_hunk_parsing():
    diff = ("--- a/x.py\n+++ b/x.py\n@@ -2,4 +2,4 @@\n ctx\n-a\n-a2\n+b\n ctx\n@@ -10,0 +11 @@\n+c\n"
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+d\n--- a/y.py\n+++ b/y.py\n@@ -5 +5 @@\n-e\n+f\n")
    assert base_line_ranges(diff) == {"x.py": [(3, 2), (10, 1)], "y.py": [(5, 1)]}
