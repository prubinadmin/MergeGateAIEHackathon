"""Spec-only test writer (owner: Michael). Uses Muse Spark.

Input: the issue text plus the public interface of the changed modules (signatures + docstrings,
bodies stripped; docstrings come from the base version when the function already existed, so the
implementer cannot rewrite the spec). The writer never sees the PR's diff, its tests or its reasoning.

The model writes two kinds of tests:
  test_invariant_*  must hold before and after the PR. Kept only if they pass on base.
                    Passing on base and failing on head = a regression -> block evidence.
  test_issue_*      the new behaviour the issue asks for. Failing on head -> review evidence only,
                    because the model may have misread the spec.
The verdict is still decided by plain code in verify.decide().
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from . import llm
from .pr import PullRequest
from .rules import is_test_path, module_name
from .sandbox import SandboxResult, run_tests
from .schema import Evidence

DEVELOPER_PROMPT = """You are an independent test writer for a merge gate. You write pytest tests from a SPEC ONLY.
You are given an issue and the public interface (signatures and docstrings) of the modules a pull request touches.
You never see the implementation or the pull request.

Write one pytest file. Rules:
- Import the code under test INSIDE each test function, exactly as `from <module> import <name>` using the
  module paths given (never at the top of the file: some names may not exist yet before the change).
- Two kinds of test functions, and only these two prefixes:
  - test_invariant_<what>: behaviour that the docstrings promise and that must hold both before and after the
    change (edge cases, bounds, types, errors raised, round trips). Write at least 4, covering boundaries
    the docstrings state (zero, negative, empty, very large, over 100%, None) when they apply.
  - test_issue_<what>: the new or changed behaviour the issue asks for. 0 to 3 of these.
- Each test checks one thing and has a short assert message.
- Deterministic: no network, no files, no sleeping, no randomness, no mocking of the code under test.
- Use pytest.approx for floats. Use pytest.raises only when a docstring says an error is raised.
- Do not test private names (leading underscore).
Return only the Python file in one ```python code block."""


@dataclass
class TestGenResult:
    source: str = ""
    kept_invariants: list[str] = field(default_factory=list)
    dropped_invariants: list[str] = field(default_factory=list)  # failed on base: bad tests
    base: SandboxResult | None = None
    head: SandboxResult | None = None
    evidence: list[Evidence] = field(default_factory=list)
    error: str = ""


def _strip_bodies(src: str, base_docs: dict[str, str]) -> str:
    """Signatures + docstrings of public top-level functions and classes."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    out: list[str] = []

    def sig(fn: ast.FunctionDef | ast.AsyncFunctionDef, indent: str, qual: str) -> None:
        if fn.name.startswith("_") and fn.name != "__init__":
            return
        head = ast.unparse(fn).split("\n", 1)[0]  # 'def f(a, b) -> int:'
        for dec in fn.decorator_list:
            out.append(f"{indent}@{ast.unparse(dec)}")
        out.append(indent + head)
        doc = base_docs.get(qual) or ast.get_docstring(fn)
        if doc:
            out.append(f'{indent}    """{doc}"""')
        out.append(f"{indent}    ...")
        out.append("")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig(node, "", node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            out.append(f"class {node.name}({bases}):" if bases else f"class {node.name}:")
            doc = base_docs.get(node.name) or ast.get_docstring(node)
            if doc:
                out.append(f'    """{doc}"""')
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig(item, "    ", f"{node.name}.{item.name}")
            out.append("    ...")
            out.append("")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            text = ast.unparse(node)
            if len(text) < 120 and not text.startswith("_"):
                out.append(text)
    return "\n".join(out).strip()


def _docstrings(src: str | None) -> dict[str, str]:
    docs: dict[str, str] = {}
    if not src:
        return docs
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return docs
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if d := ast.get_docstring(node):
                docs[node.name] = d
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (d := ast.get_docstring(item)):
                        docs[f"{node.name}.{item.name}"] = d
    return docs


def public_interface(pr: PullRequest) -> str:
    """Interface of the changed non-test modules: head signatures, base docstrings where they exist."""
    parts = []
    for path in pr.changed_files():
        if not path.endswith(".py") or is_test_path(path):
            continue
        head = pr.file_at(pr.head_ref, path)
        if head is None:
            continue
        stub = _strip_bodies(head, _docstrings(pr.file_at(pr.base_ref, path)))
        if stub:
            parts.append(f"# module: {module_name(path)}  (file {path})\n{stub}")
    return "\n\n".join(parts)


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    code = (m.group(1) if m else text).strip() + "\n"
    ast.parse(code)  # raises SyntaxError on garbage
    return code


def _test_names(code: str) -> list[str]:
    return [n.name for n in ast.parse(code).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]


def _drop_tests(code: str, names: set[str]) -> str:
    tree = ast.parse(code)
    tree.body = [n for n in tree.body if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names)]
    return ast.unparse(tree) + "\n"


def generate_tests(pr: PullRequest) -> str:
    """Return pytest source written from the issue + interface only."""
    interface = public_interface(pr)
    if not interface:
        raise ValueError("no public interface in the changed modules")
    user = f"ISSUE\n{pr.title}\n{pr.issue_text or '(no issue text)'}\n\nPUBLIC INTERFACE\n```python\n{interface}\n```"
    return _extract_code(llm.complete(DEVELOPER_PROMPT, user))


def independent_check(pr: PullRequest, timeout_s: int = 60) -> TestGenResult:
    res = TestGenResult()
    try:
        res.source = generate_tests(pr)
    except (llm.LLMError, SyntaxError, ValueError) as e:
        res.error = f"test writer unavailable: {e}"
        return res

    name = "test_gate_spec.py"
    res.base = run_tests(pr.repo_path, pr.base_ref, {name: res.source}, timeout_s)
    if res.base.errored and not res.base.failed:
        res.error = "generated tests do not run on base"
        return res

    names = _test_names(res.source)
    failed_on_base = {f.test_id.split("::")[-1] for f in res.base.failed}
    res.dropped_invariants = [n for n in names if n.startswith("test_invariant") and n in failed_on_base]
    res.kept_invariants = [n for n in names if n.startswith("test_invariant") and n not in failed_on_base]
    source = _drop_tests(res.source, set(res.dropped_invariants)) if res.dropped_invariants else res.source

    res.head = run_tests(pr.repo_path, pr.head_ref, {name: source}, timeout_s)
    if res.head.errored and not res.head.failed:
        res.evidence.append(Evidence(
            type="failing_test", id="gate::import", severity="block",
            detail="the PR breaks the public interface: the gate's tests cannot even import or run",
        ))
        return res
    for f in res.head.failed:
        test = f.test_id.split("::")[-1]
        if test.startswith("test_invariant"):
            res.evidence.append(Evidence(type="failing_test", id=f"gate::{test}", detail=f"{test}: {f.message}", file=f.file, line=f.line, severity="block"))
        elif test.startswith("test_issue"):
            res.evidence.append(Evidence(type="failing_test", id=f"gate::{test}", detail=f"{test}: {f.message}", file=f.file, line=f.line, severity="review"))
    return res
