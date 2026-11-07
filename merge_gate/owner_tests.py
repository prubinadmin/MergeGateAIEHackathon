"""Owner replies become tests: the codebase learns what only its authors know.

The owner texts a rule in plain English ("a discount over 100% must make the price free, never negative").
Muse Spark turns that ONE sentence into ONE pytest test, written against the public interface of the changed
module only (same extraction as testgen: signatures + base docstrings, never the PR's diff or tests).

The test is kept only if it PASSES on the base ref: a rule that doesn't hold on main is a misunderstanding,
not knowledge. Whether it FAILS on the PR head is recorded. Accepted tests live in the gate's data dir
(owner_tests/<owner-local-part>/test_<slug>.py + owner_tests/registry.json), never in the target repo,
and from then on verify() runs them on every PR that touches the same files. Running a stored test needs
no model call; only creating one does. Generated code only ever runs through sandbox.run_tests (a temp
`git archive` copy, scrubbed env, subprocess with a timeout), never in-process, and a stored file runs
only if its sha256 still matches the one recorded when it was validated.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass

from . import llm, store
from .pr import PullRequest
from .rules import is_test_path
from .sandbox import run_tests
from .schema import Evidence, run_hash
from .testgen import _drop_tests, _extract_code, _test_names, public_interface

OWNER_TESTS_DIR = "owner_tests"

DEVELOPER_PROMPT = """You turn one rule, stated in plain English by the engineer who owns the code, into ONE pytest test.
You are given the rule and the public interface (signatures and docstrings) of the module it is about.
You never see the implementation or any pull request.

Rules:
- Exactly one test function, named test_<short_snake_case_summary_of_the_rule>.
- Import the code under test INSIDE the test function, as `from <module> import <name>` using the module paths given.
- Check the rule at its boundaries (for example exactly at, just over and far over a stated limit).
- Each assert has a short message that restates the rule.
- Deterministic: no network, no files, no sleeping, no randomness, no mocking of the code under test.
- Use pytest.approx for floats.
Return only the Python file in one ```python code block."""


@dataclass
class OwnerTest:
    owner: str
    sentence: str
    pr_id: str
    accepted: bool = False
    reason: str = ""  # why it was rejected, empty when accepted
    test_name: str = ""
    source: str = ""
    file: str = ""  # relative to the owner-tests dir
    files: list[str] | None = None  # source files of the target repo this rule is about
    passes_base: bool = False
    fails_head: bool = False
    created_at: str = ""
    run_hash: str = ""
    sha256: str = ""  # of the validated code; a stored file that no longer matches is never run

    def entry(self) -> dict:
        """The registry record."""
        keys = ("owner", "sentence", "pr_id", "created_at", "file", "files", "test_name", "passes_base", "fails_head", "run_hash", "sha256")
        d = asdict(self)
        return {k: d[k] for k in keys}


def owner_key(owner: str) -> str:
    """'Peter@Example.com' -> 'peter'. Safe as a directory and module name."""
    return re.sub(r"[^a-z0-9_]", "_", (owner or "owner").split("@", 1)[0].lower()) or "owner"


def _dir(dir_: str | None) -> str:
    return dir_ or OWNER_TESTS_DIR


def load_registry(dir_: str | None = None) -> list[dict]:
    path = os.path.join(_dir(dir_), "registry.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _source_files(pr: PullRequest) -> list[str]:
    return [p for p in pr.changed_files() if p.endswith(".py") and not is_test_path(p)]


def rule_to_test(pr: PullRequest, owner: str, sentence: str, timeout_s: int = 60, dir_: str | None = None) -> OwnerTest:
    """Owner's sentence -> one validated pytest test, stored under that owner's name if it holds on base."""
    t = OwnerTest(owner=owner, sentence=sentence.strip(), pr_id=pr.pr_id, files=_source_files(pr))
    if not t.sentence:
        t.reason = "the message is empty"
        return t
    interface = public_interface(pr)
    if not interface:
        t.reason = "the PR changes no module with a public interface to test"
        return t
    user = f"RULE (from the code owner)\n{t.sentence}\n\nPUBLIC INTERFACE\n```python\n{interface}\n```"
    try:
        code = _extract_code(llm.complete(DEVELOPER_PROMPT, user))
        names = _test_names(code)
    except llm.LLMError as e:
        t.reason = f"Muse Spark is unavailable ({e})"
        return t
    except SyntaxError:
        t.reason = "the generated test doesn't parse"
        return t
    if not names:
        t.reason = "the generated code has no test function"
        return t
    if len(names) > 1:  # one sentence, one test
        code = _drop_tests(code, set(names[1:]))
    t.test_name, t.source = names[0], code

    sandbox_name = f"test_owner_{owner_key(owner)}_{t.test_name[5:]}.py"
    base = run_tests(pr.repo_path, pr.base_ref, {sandbox_name: code}, timeout_s)
    t.passes_base = base.passed >= 1 and not base.failed and not base.errored
    if not t.passes_base:
        why = base.failed[0].message if base.failed else "it does not run"
        t.reason = f"the rule doesn't hold on {pr.base_ref} ({why})"
        _log(t)
        return t
    head = run_tests(pr.repo_path, pr.head_ref, {sandbox_name: code}, timeout_s)
    t.fails_head = bool(head.failed) or head.errored

    t.accepted = True
    t.created_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t.file = f"{owner_key(owner)}/test_{t.test_name[5:]}.py"
    t.run_hash = run_hash({"sentence": t.sentence, "source": code, "base": base.output_hash, "head": head.output_hash})
    root = _dir(dir_)
    os.makedirs(os.path.join(root, owner_key(owner)), exist_ok=True)
    t.sha256 = _sha(code)
    # exactly the validated bytes: free text (owner, sentence) never goes into source, only into registry.json
    with open(os.path.join(root, t.file), "w", encoding="utf-8", newline="") as f:
        f.write(code)
    registry = [e for e in load_registry(root) if e["file"] != t.file] + [t.entry()]
    with open(os.path.join(root, "registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    _log(t)
    return t


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _log(t: OwnerTest) -> None:
    store.append("owner_test", {**t.entry(), "accepted": t.accepted, "reason": t.reason})


def outcome_text(t: OwnerTest) -> str:
    """The reply the owner gets back."""
    if not t.accepted:
        return f"Couldn't learn that: {t.reason}."
    if t.fails_head:
        return f"Learned: {t.test_name}. It fails on {t.pr_id}, so {t.pr_id} stays blocked."
    return f"Learned: {t.test_name}. {t.pr_id} already follows it; it now guards every PR that touches {', '.join(t.files or [])}."


def check_owner_tests(pr: PullRequest, timeout_s: int = 60, dir_: str | None = None) -> list[Evidence]:
    """Run every stored owner test about a file this PR touches. Passes on base + fails on head -> block."""
    changed = set(pr.changed_files())
    root = _dir(dir_)
    tests: dict[str, dict] = {}  # sandbox file name -> registry entry
    sources: dict[str, str] = {}
    for e in load_registry(root):
        if not changed & set(e.get("files") or []):
            continue
        path = os.path.join(root, e["file"])
        if not os.path.exists(path):
            continue
        name = f"test_owner_{owner_key(e['owner'])}_{os.path.basename(e['file'])[5:]}"
        with open(path, encoding="utf-8", newline="") as f:
            src = f.read()
        if not e.get("sha256") or _sha(src) != e["sha256"]:
            store.append("owner_test_skipped", {"file": e["file"], "reason": "file does not match the validated sha256"})
            continue
        sources[name] = src
        tests[name] = e
    if not tests:
        return []

    base = run_tests(pr.repo_path, pr.base_ref, sources, timeout_s)
    if base.errored and not base.failed:
        return []  # can't establish that the rules hold here; no evidence either way
    failed_base = {f.test_id for f in base.failed}
    head = run_tests(pr.repo_path, pr.head_ref, sources, timeout_s)

    def ev(e: dict, test: str, msg: str, file=None, line=None) -> Evidence:
        return Evidence(
            type="failing_test", id=f"owner::{owner_key(e['owner'])}::{test}", severity="block", file=file, line=line,
            detail=f'{e["owner"]} taught the gate "{e["sentence"]}"; {test} {msg}',
        )

    out: list[Evidence] = []
    if head.errored and not head.failed:
        for name, e in tests.items():  # every rule that held on base is now broken
            if not any(fid.split("::")[0].endswith(name) for fid in failed_base):
                out.append(ev(e, e["test_name"], "cannot even run on the PR"))
        return out
    for f in head.failed:
        if f.test_id in failed_base:
            continue
        e = tests.get(f.test_id.split("::")[0].rsplit("/", 1)[-1])
        if e:
            test = f.test_id.split("::")[-1]
            out.append(ev(e, test, f"fails: {f.message}", f.file, f.line))
    return out
