"""Owner replies become tests: the codebase learns what only its authors know.

The owner texts a rule in plain English ("a discount over 100% must make the price free, never negative").
Muse Spark turns that ONE sentence into ONE pytest test, written against the public interface of the changed
module only (same extraction as testgen: signatures + base docstrings, never the PR's diff or tests).

The test is kept only if it PASSES on the base ref: a rule that doesn't hold on main is a misunderstanding,
not knowledge. Whether it FAILS on the PR head is recorded. Accepted tests live in the gate's data dir
(owner_tests/<owner email, sanitised>/test_<slug>_<sentence hash>.py + owner_tests/registry.json), never in
the target repo, and from then on verify() runs them on every PR that touches the same files. Running a
stored test needs no model call; only creating one does. Generated code only ever runs through
sandbox.run_tests (a temp `git archive` copy, scrubbed env, subprocess with a timeout), never in-process,
and a stored file runs only if its sha256 still matches the one recorded when it was validated.
A wrong rule is not permanent: `python -m merge_gate owner-tests remove <id>`, or the owner texts FORGET <name>.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import threading
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
    id: str = ""  # <owner key>/<test name>_<sentence hash>: what `owner-tests remove` and FORGET take
    sha256: str = ""  # of the validated code; a stored file that no longer matches is never run

    def entry(self) -> dict:
        """The registry record."""
        keys = ("id", "owner", "sentence", "pr_id", "created_at", "file", "files", "test_name",
                "passes_base", "fails_head", "run_hash", "sha256")
        d = asdict(self)
        return {k: d[k] for k in keys}


def owner_key(owner: str) -> str:
    """'Peter@Example.com' -> 'peter_example_com'. The full address, so two owners never share a directory."""
    return re.sub(r"[^a-z0-9_]", "_", (owner or "owner").strip().lower()) or "owner"


def _dir(dir_: str | None) -> str:
    return dir_ or OWNER_TESTS_DIR


_registry_lock = threading.Lock()  # ponytail: one process; a file lock if several gate processes share the dir


def load_registry(dir_: str | None = None) -> list[dict]:
    path = os.path.join(_dir(dir_), "registry.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_registry(root: str, entries: list[dict]) -> None:
    """Atomic: a crash mid-write never leaves a half-written registry."""
    os.makedirs(root, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".registry-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(root, "registry.json"))


def _source_files(pr: PullRequest) -> list[str]:
    return [p for p in pr.changed_files() if p.endswith(".py") and not is_test_path(p)]


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


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
    t.id = f"{owner_key(owner)}/{t.test_name}_{_sha(t.sentence)[:8]}"

    sandbox_name = os.path.basename(t.id) + ".py"
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
    t.file = t.id + ".py"
    t.run_hash = run_hash({"sentence": t.sentence, "source": code, "base": base.output_hash, "head": head.output_hash})
    t.sha256 = _sha(code)
    root = _dir(dir_)
    with _registry_lock:
        os.makedirs(os.path.join(root, owner_key(owner)), exist_ok=True)
        # exactly the validated bytes: free text (owner, sentence) never goes into source, only into registry.json
        with open(os.path.join(root, t.file), "w", encoding="utf-8", newline="") as f:
            f.write(code)
        _save_registry(root, [e for e in load_registry(root) if e["file"] != t.file] + [t.entry()])
    _log(t)
    return t


def remove(match: str, owner: str | None = None, dir_: str | None = None) -> list[dict]:
    """Delete stored rules whose id, file or test name is `match` (only `owner`'s, when given)."""
    root, match = _dir(dir_), match.strip()
    with _registry_lock:
        entries = load_registry(root)
        gone = [e for e in entries if match in (e.get("id"), e["file"], e["test_name"])
                and (owner is None or e["owner"].lower() == owner.lower())]
        if not gone:
            return []
        for e in gone:
            path = os.path.join(root, e["file"])
            if os.path.exists(path):
                os.remove(path)
        _save_registry(root, [e for e in entries if e not in gone])
    for e in gone:
        store.append("owner_test_removed", {"id": e.get("id"), "owner": e["owner"], "by": owner or "cli", "sentence": e["sentence"]})
    return gone


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
    """Run every stored owner test about a file this PR touches, each in its own sandbox session so one broken
    file can't hide the others. Passes on base + fails on head -> block. No longer runs on base -> review."""
    changed = set(pr.changed_files())
    root = _dir(dir_)

    def ev(e: dict, test: str, msg: str, severity="block", file=None, line=None) -> Evidence:
        return Evidence(
            type="failing_test", id=f"owner::{e['owner'].lower()}::{test}", severity=severity, file=file, line=line,
            detail=f'{e["owner"]} taught the gate "{e["sentence"]}"; {test} {msg}',
        )

    base_sha = pr.git("rev-parse", pr.base_ref).strip()
    out: list[Evidence] = []
    for e in load_registry(root):
        if not changed & set(e.get("files") or []):
            continue
        path = os.path.join(root, e["file"])
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            src = f.read()
        if not e.get("sha256") or _sha(src) != e["sha256"]:
            store.append("owner_test_skipped", {"file": e["file"], "reason": "file does not match the validated sha256"})
            continue
        out += _check_rule(pr, e, src, base_sha, timeout_s, ev)
    return out


# (repo, base commit, test sha256) -> whether it fails on base. The base outcome depends only on those, so every
# PR against the same base reuses it instead of re-exporting and re-running base for each rule on each verify.
# ponytail: in-process only (helps serve.py, not one-shot CI); grows by one entry per (base commit, rule).
_base_fails: dict[tuple[str, str, str], bool] = {}


def _check_rule(pr: PullRequest, e: dict, src: str, base_sha: str, timeout_s: int, ev) -> list[Evidence]:
    """One stored rule in its own sandbox sessions: base (cached per base commit), then head only if base holds."""
    files = {os.path.basename(e["file"]): src}
    key = (os.path.abspath(pr.repo_path), base_sha, e["sha256"])
    if key not in _base_fails:
        base = run_tests(pr.repo_path, base_sha, files, timeout_s)
        if base.errored:  # never cache: a timeout may be transient
            return [ev(e, e["test_name"], "is broken: it no longer runs on the base branch", severity="review")]
        _base_fails[key] = bool(base.failed)
    if _base_fails[key]:
        return []  # the rule stopped holding on base before this PR; not this PR's doing
    head = run_tests(pr.repo_path, pr.head_ref, files, timeout_s)
    if head.errored:
        return [ev(e, e["test_name"], "cannot even run on the PR")]
    return [ev(e, f.test_id.split("::")[-1], f"fails: {f.message}", file=f.file, line=f.line) for f in head.failed]
