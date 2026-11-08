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
    writers: list[str] = field(default_factory=list)  # model names whose tests ran, e.g. muse-wonder-1.0, gemini-4-argon


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


def generate_tests(pr: PullRequest, provider: str = "muse") -> str:
    """Return pytest source written from the issue + interface only."""
    interface = public_interface(pr)
    if not interface:
        raise ValueError("no public interface in the changed modules")
    user = f"ISSUE\n{pr.title}\n{pr.issue_text or '(no issue text)'}\n\nPUBLIC INTERFACE\n```python\n{interface}\n```"
    return _extract_code(llm.complete(DEVELOPER_PROMPT, user, provider=provider))


def writers() -> list[str]:
    """Spec-test writers: Muse always; Gemini (gemini-4-argon) too when GEMINI_API_KEY is set.

    Two labs, one PR must get past both. Neither sees the other's tests, the PR's tests or its diff."""
    return ["muse"] + (["gemini"] if llm.has_key("gemini") else [])


def _tag_tests(code: str, tag: str) -> str:
    """test_issue_x -> test_issue_<tag>_x (same for test_invariant) so two writers' tests share one module."""
    tree = ast.parse(code)
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for cls in ("test_issue", "test_invariant"):
                if n.name.startswith(cls):
                    n.name = f"{cls}_{tag}{n.name[len(cls):]}"
                    break
    return ast.unparse(tree) + "\n"


def merge_sources(sources: dict[str, str]) -> str:
    """One pytest module from several writers'; the first writer keeps its names, so single-writer output is unchanged."""
    # ponytail: module bodies are concatenated; a helper two writers both define resolves to the later one
    first, *rest = sources
    parts = [sources[first]] + [_tag_tests(sources[w], w) for w in rest]
    return "\n".join(p.rstrip("\n") for p in parts) + "\n"


def _generate_or_error(pr: PullRequest, w: str) -> tuple[str, str | None, str | None]:
    try:
        return w, generate_tests(pr, w), None
    except (llm.LLMError, SyntaxError, ValueError) as e:
        return w, None, f"{llm.model_name(w)}: {e}"


def independent_check(pr: PullRequest, timeout_s: int = 60) -> TestGenResult:
    from concurrent.futures import ThreadPoolExecutor

    ws = writers()
    with ThreadPoolExecutor(max_workers=len(ws)) as pool:  # both writers at once: Gemini adds no wall-clock time
        outcomes = list(pool.map(lambda w: _generate_or_error(pr, w), ws))
    sources = {w: s for w, s, _ in outcomes if s is not None}  # map keeps writer order: Muse stays first
    errors = [err for _, _, err in outcomes if err]
    if not sources:
        return TestGenResult(error="test writer unavailable: " + "; ".join(errors))
    res = check_generated(pr, merge_sources(sources), timeout_s)
    res.writers = [llm.model_name(w) for w in sources]
    if errors:  # the other writer's tests still ran; say who was missing
        res.error = "; ".join(filter(None, [res.error, "test writer unavailable: " + "; ".join(errors)]))
    return res


def _split_invariants(names: list[str], failed_on_base: set[str]) -> tuple[list[str], list[str]]:
    """(kept, dropped): the invariant tests that passed on base, and the bad ones that already failed there."""
    invariants = [n for n in names if n.startswith("test_invariant")]
    return [n for n in invariants if n not in failed_on_base], [n for n in invariants if n in failed_on_base]


def _head_evidence(head: SandboxResult) -> list[Evidence]:
    """Failures on head: an invariant is a regression (block), an issue test may have misread the spec (review)."""
    if head.errored and not head.failed:
        return [Evidence(
            type="failing_test", id="gate::import", severity="block",
            detail="the PR breaks the public interface: the gate's tests cannot even import or run",
        )]
    out: list[Evidence] = []
    for f in head.failed:
        test = f.test_id.split("::")[-1]
        if test.startswith("test_invariant"):
            out.append(Evidence(type="failing_test", id=f"gate::{test}", detail=f"{test}: {f.message}", file=f.file, line=f.line, severity="block"))
        elif test.startswith("test_issue"):
            out.append(Evidence(type="failing_test", id=f"gate::{test}", detail=f"{test}: {f.message}", file=f.file, line=f.line, severity="review"))
    return out


def check_generated(pr: PullRequest, source: str, timeout_s: int = 60) -> TestGenResult:
    """Run spec-only tests on base, drop the ones base already fails, then run the rest on head."""
    res = TestGenResult(source=source)
    name = "test_gate_spec.py"
    res.base = run_tests(pr.repo_path, pr.base_ref, {name: res.source}, timeout_s)
    if res.base.errored and not res.base.failed:
        res.error = "generated tests do not run on base"
        return res

    failed_on_base = {f.test_id.split("::")[-1] for f in res.base.failed}
    res.kept_invariants, res.dropped_invariants = _split_invariants(_test_names(res.source), failed_on_base)
    source = _drop_tests(res.source, set(res.dropped_invariants)) if res.dropped_invariants else res.source

    res.head = run_tests(pr.repo_path, pr.head_ref, {name: source}, timeout_s)
    res.evidence = _head_evidence(res.head)
    return res
