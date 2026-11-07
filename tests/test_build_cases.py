"""The benchmark generator is deterministic, the committed cases match it, and the splits are stratified. No network."""

import importlib.util
import json
import os
import subprocess
from collections import Counter

import pytest

from merge_gate.bench import KINDS, load_cases

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmark")
spec = importlib.util.spec_from_file_location("build_cases", os.path.join(ROOT, "build_cases.py"))
build_cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_cases)


def committed() -> list[dict]:
    out = []
    for name in sorted(os.listdir(os.path.join(ROOT, "cases"))):
        path = os.path.join(ROOT, "cases", name, "case.json")
        if not os.path.isfile(path):  # .DS_Store and friends
            continue
        with open(path, encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def test_case_json_is_deterministic_and_matches_the_committed_files():
    assert build_cases.all_cases() == build_cases.all_cases()
    assert sorted(build_cases.all_cases(), key=lambda c: c["pr_id"]) == committed()


def test_case_schema():
    cases = committed()
    assert len(cases) == 30
    emails = {a[1] for a in build_cases.AUTHORS}
    assert len(emails) >= 5
    assert len({c["pr_id"] for c in cases}) == len({c["head_ref"] for c in cases}) == 30
    for c in cases:
        assert set(c) == {"pr_id", "repo", "base_ref", "head_ref", "title", "issue_text", "opened_by", "label"}
        lab = c["label"]
        assert lab["kind"] in KINDS
        assert lab["true_verdict"] == ("PASS" if lab["kind"] == "clean" else "BLOCK")
        assert lab["true_owner_email"] in emails
        assert c["repo"] == "target_repo" and c["base_ref"] == "main" and c["issue_text"] and c["title"]
    kinds = Counter(c["label"]["kind"] for c in cases)
    assert kinds["clean"] == 8 and sum(kinds.values()) - kinds["clean"] == 22
    assert set(kinds) == set(KINDS)


def test_splits_are_stratified():
    cases = committed()
    by_split = {s: [c["label"]["kind"] for c in cases if c["label"]["split"] == s] for s in ("train", "heldout")}
    assert len(by_split["train"]) == len(by_split["heldout"]) == 15
    for kinds in by_split.values():
        assert set(kinds) == set(KINDS)  # every bad category and clean cases in both splits


def test_every_edit_applies_to_the_base_files():
    base = build_cases.base_files()
    for p in build_cases.PRS:
        head = build_cases.head_files(p, base)
        assert head and any(head[f] != base.get(f) for f in head), p["key"]


def _trees(repo: str) -> dict[str, str]:
    out = subprocess.run(["git", "-C", repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"],
                         capture_output=True, text=True, check=True).stdout
    trees = {}
    for line in out.splitlines():
        ref, _ = line.split()
        trees[ref] = subprocess.run(["git", "-C", repo, "rev-parse", f"{ref}^{{tree}}"],
                                    capture_output=True, text=True, check=True).stdout.strip()
    return trees


def test_target_repo_build_is_deterministic(tmp_path):
    a = build_cases.build_repo(str(tmp_path / "a"))  # also checks every true owner against git blame
    b = build_cases.build_repo(str(tmp_path / "b"))
    assert a == b == build_cases.all_cases()
    trees = _trees(str(tmp_path / "a"))
    assert trees == _trees(str(tmp_path / "b"))  # same file contents on every branch
    assert len(trees) == 31  # main + 30 PR branches
    authors = subprocess.run(["git", "-C", str(tmp_path / "a"), "log", "--format=%ae", "main"],
                             capture_output=True, text=True, check=True).stdout.split()
    assert len(set(authors)) >= 5
    with pytest.raises(FileExistsError):
        build_cases.build_repo(str(tmp_path / "a"))


def test_git_runs_with_a_scrubbed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "outer.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "idx"))
    repo = str(tmp_path / "r")
    os.makedirs(repo)
    build_cases._git(repo, "init", "-q", "-b", "main")
    assert os.path.isdir(os.path.join(repo, ".git")) and not os.path.exists(tmp_path / "outer.git")
    seen = {}
    monkeypatch.setattr(build_cases.subprocess, "run", lambda *a, **kw: seen.update(kw["env"]) or subprocess.CompletedProcess(a, 0, "", ""))
    build_cases._git(repo, "status")
    assert "GIT_DIR" not in seen and "GIT_WORK_TREE" not in seen and "GIT_INDEX_FILE" not in seen
    assert seen["GIT_CONFIG_GLOBAL"] == os.devnull and seen["HOME"] != os.environ.get("HOME")


def test_write_cases_removes_stale_generated_dirs_only(tmp_path):
    cases_dir = str(tmp_path / "cases")
    for stale in ("pr99_clean", "pr01_deleted_test", "notes", "prX_other"):
        os.makedirs(os.path.join(cases_dir, stale))
    with open(os.path.join(cases_dir, "README.md"), "w") as f:
        f.write("keep\n")
    cases = build_cases.all_cases()
    build_cases.write_cases(cases, cases_dir)
    names = set(os.listdir(cases_dir))
    assert "pr99_clean" not in names and "pr01_deleted_test" not in names  # stale prNN_* dirs gone
    assert {"notes", "prX_other", "README.md"} <= names                      # anything else untouched
    assert names - {"notes", "prX_other", "README.md"} == {f"{c['pr_id']}_{c['label']['kind']}" for c in cases}


def test_load_cases_reads_the_benchmark():
    cases = load_cases(ROOT)
    assert len(cases) == 30
    assert len(load_cases(ROOT, "train")) == len(load_cases(ROOT, "heldout")) == 15


def test_baselines(tmp_path, monkeypatch):
    from helpers import make_pr

    from merge_gate import baselines, llm

    pr = make_pr(tmp_path, {"CODEOWNERS": "/shop/ a@example.com\n", "shop/x.py": "X = 1\n"}, {"shop/x.py": "X = 2\n"})
    assert baselines.codeowners_route(pr).owners[0].email == "a@example.com"

    monkeypatch.setattr(llm, "complete", lambda dev, user: "Block. This changes X.")
    assert baselines.llm_review(pr).verdict == "BLOCK"
    monkeypatch.setattr(llm, "complete", lambda dev, user: "not sure")
    assert baselines.llm_review(pr) is None  # unparseable -> counted as a missing report


@pytest.mark.parametrize("reply, want", [
    ("BLOCK", "BLOCK"),
    ("  pass\n", "PASS"),
    ("This should not PASS: BLOCK", "BLOCK"),   # first-match would say PASS
    ("No reason to BLOCK. PASS.", "PASS"),      # first-match would say BLOCK
    ("Block. This changes X.", "BLOCK"),
    ("Reasoning first.\nBLOCK", "BLOCK"),
    ("PASSING is not a verdict", None),
    ("not sure", None),
])
def test_baseline_verdict_parsing(reply, want):
    from merge_gate.baselines import parse_verdict

    assert parse_verdict(reply) == want


def test_bench_llm_baseline_refuses_without_llm_and_fails_on_missing_reports(tmp_path, monkeypatch, capsys):
    from merge_gate import cli, llm

    root = str(tmp_path / "benchmark")
    build_cases.write_cases(build_cases.build_repo(os.path.join(root, "target_repo")), os.path.join(root, "cases"))
    argv = ["bench", "--root", root, "--split", "heldout", "--baseline", "llm"]

    assert cli.main([*argv, "--no-llm"]) == 1
    assert "needs Muse Spark" in capsys.readouterr().err
    assert cli.main([*argv, "--stub"]) == 1

    monkeypatch.setattr(llm, "has_key", lambda: True)

    def down(dev, user):
        raise llm.LLMError("503")

    monkeypatch.setattr(llm, "complete", down)  # every call fails -> no reports -> loud exit 1
    assert cli.main(argv) == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["missing_reports"] == 15
    assert "15 of 15 cases got no llm report" in out.err and "pr" in out.err

    monkeypatch.setattr(llm, "complete", lambda dev, user: "PASS")
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["missing_reports"] == 0
