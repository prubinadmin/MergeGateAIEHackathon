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
        with open(os.path.join(ROOT, "cases", name, "case.json"), encoding="utf-8") as f:
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
