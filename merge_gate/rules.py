"""Anti-gaming and safety rules (owner: Michael). Deterministic: no LLM, no network.

Each rule compares the base and head versions of the files a PR changes and returns Evidence.
Rule ids are stable strings; the iMessage text and the benchmark refer to them.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from typing import Callable

from .pr import PullRequest
from .schema import Evidence

RULE_IDS = {
    "R1_DELETED_TEST": "a test function or test file was removed",
    "R2_SKIPPED_TEST": "a test was newly skipped or marked xfail",
    "R3_WEAKENED_ASSERT": "a test lost asserts or an assert was made trivially true",
    "R4_MOCKED_SUBJECT": "the code this PR changes is mocked out in tests",
    "R5_HARDCODED_OUTPUT": "the implementation special-cases inputs that appear in the tests",
    "R6_OUT_OF_SCOPE_TEST_EDIT": "tests changed that do not match any changed source module",
    "R7_DANGEROUS_CALL": "new SQL string building, eval/exec, shell=True or unsafe deserialization",
    "R8_BACKDOOR_LITERAL": "new hardcoded credential or magic value that grants access",
    "R9_UNPARSEABLE": "a changed Python file does not parse, so the rules could not check it",
    "R10_RUNTIME_INTEGRITY": "code is broken when trying to run (syntax error, broken import, or runtime smoke failure)",
    "R11_PERFORMANCE_REGRESSION": "performance slowed down (new nested O(N^2) loops, blocking sleep/sync I/O, or unindexed scans)",
    "R12_COMPLEXITY_INFLATION": "code simplicity violation (function refactored to be significantly more complex, high cyclomatic depth)",
    "R13_STYLE_INCONSISTENCY": "code style conventions inconsistent with existing codebase (naming style drift, dropped typing)",
    "R14_REGULATORY_STYLE_VIOLATION": "code style regulations violation (wildcard imports, bare excepts, leftover debug calls)",
}

SENSITIVE_NAME = re.compile(r"auth|login|token|passw|secret|permission|admin|role|access|session|verify", re.I)


# --- file model ----------------------------------------------------------------


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    name = os.path.basename(p)
    parts = p.split("/")[:-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "tests" in parts
        or "test" in parts
    )


def module_name(path: str) -> str:
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    for prefix in ("src/",):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p.replace("/", ".")


@dataclass
class FileChange:
    path: str
    base: str | None  # None = file added
    head: str | None  # None = file deleted
    base_tree: ast.Module | None
    head_tree: ast.Module | None

    @property
    def is_test(self) -> bool:
        return is_test_path(self.path)


def _parse(src: str | None) -> ast.Module | None:
    if src is None:
        return None
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def changes(pr: PullRequest) -> list[FileChange]:
    out = []
    for path in pr.changed_files():
        if not path.endswith(".py"):
            continue
        base = pr.file_at(pr.base_ref, path)
        head = pr.file_at(pr.head_ref, path)
        out.append(FileChange(path, base, head, _parse(base), _parse(head)))
    return out


def _functions(tree: ast.Module | None) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Qualified name -> function node (methods as Class.method)."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    if tree is None:
        return found

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = child
                walk(child, prefix + child.name + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")

    walk(tree, "")
    return found


def _tests(tree: ast.Module | None) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {k: v for k, v in _functions(tree).items() if k.split(".")[-1].startswith("test")}


def _call_name(node: ast.AST) -> str:
    """Dotted name of a call target: mock.patch.object -> 'mock.patch.object'."""
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_skip(node: ast.AST) -> bool:
    name = _call_name(node)
    return any(name.endswith(s) for s in ("mark.skip", "mark.skipif", "mark.xfail", "pytest.skip", "unittest.skip", "skip", "skipIf", "skipUnless", "expectedFailure"))


def _skip_count(fn: ast.AST) -> int:
    n = 0
    for dec in getattr(fn, "decorator_list", []):
        if _is_skip(dec):
            n += 1
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and _call_name(node) in ("pytest.skip", "pytest.xfail", "self.skipTest"):
            n += 1
    return n


def _asserts(fn: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            out.append(node)
        elif isinstance(node, ast.Call):
            name = _call_name(node).split(".")[-1]
            if name.startswith("assert") or name == "raises":
                out.append(node)
    return out


def _trivial_assert(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        t = node.test
        if isinstance(t, ast.Constant) and bool(t.value):
            return True
        if isinstance(t, ast.Compare) and len(t.comparators) == 1:
            if ast.dump(t.left) == ast.dump(t.comparators[0]):
                return True
    return False


def _literals(tree: ast.Module | None) -> set:
    vals: set = set()
    if tree is None:
        return vals
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)) and not isinstance(node.value, bool):
            vals.add(node.value)
    return vals


def _ev(rule_id: str, detail: str, path: str, line: int | None, severity: str = "block") -> Evidence:
    return Evidence(type="rule", id=rule_id, detail=detail, file=path, line=line, severity=severity)  # type: ignore[arg-type]


# --- rules ---------------------------------------------------------------------


def r1_deleted_test(chs: list[FileChange]) -> list[Evidence]:
    out = []
    for c in chs:
        if not c.is_test:
            continue
        before = _tests(c.base_tree)
        if c.head is None and before:
            out.append(_ev("R1_DELETED_TEST", f"PR deletes test file {c.path} ({len(before)} tests)", c.path, None))
            continue
        after = _tests(c.head_tree)
        for name, fn in before.items():
            if name not in after:
                out.append(_ev("R1_DELETED_TEST", f"PR deletes {name} from {c.path}", c.path, fn.lineno))
    return out


def r2_skipped_test(chs: list[FileChange]) -> list[Evidence]:
    out = []
    for c in chs:
        if not c.is_test or c.head_tree is None:
            continue
        before = _tests(c.base_tree)
        for name, fn in _tests(c.head_tree).items():
            was = _skip_count(before[name]) if name in before else 0
            if _skip_count(fn) > was:
                out.append(_ev("R2_SKIPPED_TEST", f"PR newly skips {name} in {c.path}", c.path, fn.lineno))
    return out


def r3_weakened_assert(chs: list[FileChange]) -> list[Evidence]:
    out = []
    for c in chs:
        if not c.is_test or c.head_tree is None:
            continue
        before = _tests(c.base_tree)
        for name, fn in _tests(c.head_tree).items():
            if name not in before:
                continue
            old, new = _asserts(before[name]), _asserts(fn)
            old_trivial = sum(_trivial_assert(a) for a in old)
            new_trivial = sum(_trivial_assert(a) for a in new)
            if len(new) < len(old):
                out.append(_ev("R3_WEAKENED_ASSERT", f"{name} in {c.path} went from {len(old)} asserts to {len(new)}", c.path, fn.lineno))
            elif new_trivial > old_trivial:
                bad = next(a for a in new if _trivial_assert(a))
                out.append(_ev("R3_WEAKENED_ASSERT", f"{name} in {c.path} now has an assert that is always true", c.path, bad.lineno))
            elif len(new) == 0 and len(old) > 0:
                out.append(_ev("R3_WEAKENED_ASSERT", f"{name} in {c.path} no longer asserts anything", c.path, fn.lineno))
    return out


def _patch_targets(tree: ast.Module | None) -> list[tuple[str, int]]:
    """(dotted target, line) for mock.patch('a.b.c'), patch.object(mod, 'f'), monkeypatch.setattr('a.b', ...)."""
    found: list[tuple[str, int]] = []
    if tree is None:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        last = name.split(".")[-1]
        args = node.args
        if last == "patch" and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            found.append((args[0].value, node.lineno))
        elif last in ("object", "setattr") and len(args) >= 2:
            first, second = args[0], args[1]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((first.value, node.lineno))
            elif isinstance(second, ast.Constant) and isinstance(second.value, str):
                found.append((_call_name(first) + "." + second.value, node.lineno))
    return found


def r4_mocked_subject(chs: list[FileChange]) -> list[Evidence]:
    changed_src: dict[str, set[str]] = {}
    for c in chs:
        if not c.is_test and c.head_tree is not None:
            base_fns = _functions(c.base_tree)
            head_fns = _functions(c.head_tree)
            touched = {
                n.split(".")[-1]
                for n, f in head_fns.items()
                if n not in base_fns or ast.dump(f) != ast.dump(base_fns[n])
            }
            mod = module_name(c.path)
            changed_src[mod] = touched
            changed_src[mod.split(".")[-1]] = touched  # patch.object(pricing, 'f') style
    out = []
    for c in chs:
        if not c.is_test or c.head_tree is None:
            continue
        before = {t for t, _ in _patch_targets(c.base_tree)}
        for target, line in _patch_targets(c.head_tree):
            if target in before:
                continue
            mod, _, attr = target.rpartition(".")
            if mod in changed_src and (attr in changed_src[mod] or not changed_src[mod]):
                out.append(_ev("R4_MOCKED_SUBJECT", f"{c.path} mocks {target}, which this PR changes", c.path, line))
    return out


def _const_return(body: list[ast.stmt]) -> bool:
    return len(body) >= 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Constant)


def _literal_ifs(fn: ast.AST) -> list[tuple[ast.If, object]]:
    """`if <expr> == <literal>: return <literal>` inside fn -> (node, compared literal)."""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not _const_return(node.body):
            continue
        t = node.test
        compares = [t] if isinstance(t, ast.Compare) else [v for v in getattr(t, "values", []) if isinstance(v, ast.Compare)]
        for cmp in compares:
            if len(cmp.ops) == 1 and isinstance(cmp.ops[0], (ast.Eq, ast.In)):
                for side in (cmp.left, cmp.comparators[0]):
                    if isinstance(side, ast.Constant):
                        out.append((node, side.value))
                    elif isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                        out.extend((node, e.value) for e in side.elts if isinstance(e, ast.Constant))
    return out


def r5_r8_literal_special_cases(chs: list[FileChange], test_literals: set) -> list[Evidence]:
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None:
            continue
        base_fns = _functions(c.base_tree)
        for name, fn in _functions(c.head_tree).items():
            old_cases = {ast.dump(n) for n, _ in _literal_ifs(base_fns[name])} if name in base_fns else set()
            for node, lit in _literal_ifs(fn):
                if ast.dump(node) in old_cases:
                    continue
                ret = node.body[0].value.value  # type: ignore[union-attr]
                if lit in test_literals or ret in test_literals:
                    out.append(_ev("R5_HARDCODED_OUTPUT", f"{name}() in {c.path} special-cases {lit!r}, a value from the tests", c.path, node.lineno))
                elif isinstance(lit, str) and (ret is True or SENSITIVE_NAME.search(name) or SENSITIVE_NAME.search(c.path)):
                    out.append(_ev("R8_BACKDOOR_LITERAL", f"{name}() in {c.path} grants a special path for the hardcoded value {lit!r}", c.path, node.lineno))
    return out


def _dangerous(tree: ast.Module | None) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    if tree is None:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        last = name.split(".")[-1]
        if last in ("execute", "executemany", "executescript", "raw") and node.args:
            q = node.args[0]
            if isinstance(q, ast.JoinedStr) or (isinstance(q, ast.BinOp) and isinstance(q.op, (ast.Add, ast.Mod))) or (
                isinstance(q, ast.Call) and _call_name(q).endswith("format")
            ):
                found.append(("SQL built from a string instead of query parameters", node.lineno))
        elif name in ("eval", "exec", "builtins.eval", "builtins.exec"):
            found.append((f"{name}() on dynamic input", node.lineno))
        elif name in ("os.system", "os.popen"):
            found.append((f"{name}() runs a shell command", node.lineno))
        elif name.startswith("subprocess.") and any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
            found.append(("subprocess with shell=True", node.lineno))
        elif name in ("pickle.loads", "pickle.load", "marshal.loads"):
            found.append((f"{name}() deserializes untrusted data", node.lineno))
        elif name in ("yaml.load",) and not any(k.arg == "Loader" for k in node.keywords):
            found.append(("yaml.load without a safe Loader", node.lineno))
    return found


def r7_dangerous_call(chs: list[FileChange]) -> list[Evidence]:
    out = []
    for c in chs:
        if c.is_test:
            continue
        before = {d for d, _ in _dangerous(c.base_tree)}
        before_count: dict[str, int] = {}
        for d, _ in _dangerous(c.base_tree):
            before_count[d] = before_count.get(d, 0) + 1
        seen: dict[str, int] = {}
        for desc, line in _dangerous(c.head_tree):
            seen[desc] = seen.get(desc, 0) + 1
            if desc not in before or seen[desc] > before_count.get(desc, 0):
                out.append(_ev("R7_DANGEROUS_CALL", f"{c.path}:{line} adds {desc}", c.path, line))
    return out


def r6_out_of_scope_tests(chs: list[FileChange]) -> list[Evidence]:
    src_stems = {os.path.basename(c.path)[:-3] for c in chs if not c.is_test}
    out = []
    for c in chs:
        if not c.is_test or os.path.basename(c.path) == "conftest.py":
            continue
        stem = os.path.basename(c.path)[:-3]
        stem = stem[len("test_"):] if stem.startswith("test_") else stem.removesuffix("_test")
        if src_stems and stem not in src_stems:
            out.append(_ev("R6_OUT_OF_SCOPE_TEST_EDIT", f"PR edits {c.path}, but changes no {stem}.py", c.path, None, severity="review"))
    return out


def _all_test_literals(pr: PullRequest) -> set:
    """Literals in the repo's tests at base (what an implementer could hardcode against)."""
    lits: set = set()
    try:
        files = pr.git("ls-tree", "-r", "--name-only", pr.base_ref).splitlines()
    except Exception:
        return lits
    for path in files:
        if path.endswith(".py") and is_test_path(path):
            lits |= _literals(_parse(pr.file_at(pr.base_ref, path)))
    # trivial values would match everything
    return {v for v in lits if v not in (0, 1, -1, "", None) and not (isinstance(v, str) and len(v) < 2)}


# --- Benchmark Verification Rules (Integrity, Performance, Simplicity, Style) ---

def r10_runtime_integrity(chs: list[FileChange]) -> list[Evidence]:
    """Check: Code is not broken when trying to run."""
    out = []
    for c in chs:
        if c.head is not None and c.head_tree is None:
            out.append(_ev("R10_RUNTIME_INTEGRITY", f"{c.path} has fatal syntax or unparseable errors preventing execution", c.path, None, severity="block"))
            continue
        if c.head_tree is not None:
            # Check for unresolved duplicate definitions or empty critical bodies
            for node in ast.walk(c.head_tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.body:
                        out.append(_ev("R10_RUNTIME_INTEGRITY", f"{c.path}:{node.lineno} function {node.name} has empty executable body", c.path, node.lineno, severity="block"))
    return out


def _has_nested_loop(node: ast.AST) -> bool:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
            for sub in ast.walk(child):
                if sub is not child and isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
                    return True
        elif _has_nested_loop(child):
            return True
    return False


def r11_performance_regression(chs: list[FileChange]) -> list[Evidence]:
    """Check: The performance of the application is not slowed down when pushing new change."""
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None:
            continue
        base_had_nested = _has_nested_loop(c.base_tree) if c.base_tree else False
        head_has_nested = _has_nested_loop(c.head_tree)
        if head_has_nested and not base_had_nested:
            # Find the line of the offending nested loop
            for node in ast.walk(c.head_tree):
                if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
                    for sub in ast.walk(node):
                        if sub is not node and isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
                            out.append(_ev("R11_PERFORMANCE_REGRESSION", f"{c.path}:{node.lineno} introduces nested O(N^2) loop bottleneck", c.path, node.lineno, severity="block"))
                            break
                    if out and out[-1].id == "R11_PERFORMANCE_REGRESSION":
                        break

        # Check for blocking time.sleep() or unbuffered sync calls inside loop
        for node in ast.walk(c.head_tree):
            if isinstance(node, ast.Call):
                call = _call_name(node)
                if call in ("time.sleep", "sleep") and not c.is_test:
                    out.append(_ev("R11_PERFORMANCE_REGRESSION", f"{c.path}:{node.lineno} adds blocking synchronous sleep() causing application slowdown", c.path, node.lineno, severity="block"))
    return out


def _cyclomatic_complexity(fn: ast.AST) -> int:
    complexity = 1
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += max(0, len(node.values) - 1)
        elif isinstance(node, getattr(ast, "Match", ())) :
            complexity += len(getattr(node, "cases", []))
    return complexity


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    max_d = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try, ast.With)):
            d = _max_nesting_depth(child, current + 1)
        else:
            d = _max_nesting_depth(child, current)
        if d > max_d:
            max_d = d
    return max_d


def r12_complexity_inflation(chs: list[FileChange]) -> list[Evidence]:
    """Check: Ensures code simplicity so functions are not refactored to be more complex."""
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None:
            continue
        base_fns = _functions(c.base_tree)
        head_fns = _functions(c.head_tree)

        for name, head_fn in head_fns.items():
            head_cc = _cyclomatic_complexity(head_fn)
            head_depth = _max_nesting_depth(head_fn)

            if name in base_fns:
                base_cc = _cyclomatic_complexity(base_fns[name])
                if head_cc >= base_cc + 4:
                    out.append(_ev("R12_COMPLEXITY_INFLATION", f"{c.path}:{head_fn.lineno} function {name} refactored with +{head_cc - base_cc} cyclomatic complexity ({base_cc} -> {head_cc})", c.path, head_fn.lineno, severity="block"))
                elif head_depth >= 4:
                    out.append(_ev("R12_COMPLEXITY_INFLATION", f"{c.path}:{head_fn.lineno} function {name} introduces excessive nesting depth ({head_depth} levels)", c.path, head_fn.lineno, severity="review"))
            else:
                if head_cc > 8:
                    out.append(_ev("R12_COMPLEXITY_INFLATION", f"{c.path}:{head_fn.lineno} new function {name} exceeds simplicity threshold (cyclomatic complexity {head_cc})", c.path, head_fn.lineno, severity="review"))
    return out


def r13_style_inconsistency(chs: list[FileChange]) -> list[Evidence]:
    """Check: Code style conventions are not inconsistent with existing code styling."""
    out = []
    for c in chs:
        if c.head_tree is None or c.base_tree is None:
            continue
        base_fns = _functions(c.base_tree)
        head_fns = _functions(c.head_tree)

        # Detect naming conventions: snake_case vs camelCase
        base_snake = sum(1 for n in base_fns if re.match(r"^[a-z_][a-z0-9_]*$", n.split(".")[-1]))
        total_base = len(base_fns)

        if total_base > 0 and (base_snake / total_base) >= 0.8:
            # Codebase strictly uses snake_case, check if head introduces camelCase
            for name, fn in head_fns.items():
                short = name.split(".")[-1]
                if re.match(r"^[a-z]+[A-Z][a-zA-Z0-9]*$", short) and not short.startswith("test_"):
                    out.append(_ev("R13_STYLE_INCONSISTENCY", f"{c.path}:{fn.lineno} introduces camelCase '{short}' in a codebase adhering to snake_case naming", c.path, fn.lineno, severity="review"))

        # Detect type annotation dropping (regression in typing consistency)
        for name, base_fn in base_fns.items():
            if name in head_fns:
                head_fn = head_fns[name]
                base_typed = base_fn.returns is not None or any(a.annotation for a in base_fn.args.args)
                head_typed = head_fn.returns is not None or any(a.annotation for a in head_fn.args.args)
                if base_typed and not head_typed:
                    out.append(_ev("R13_STYLE_INCONSISTENCY", f"{c.path}:{head_fn.lineno} removed type annotations from {name}, violating typing consistency", c.path, head_fn.lineno, severity="review"))
    return out


def r14_regulatory_style_violation(chs: list[FileChange]) -> list[Evidence]:
    """Check: Matches with existing rules and regulations of code styling."""
    out = []
    for c in chs:
        if c.head_tree is None:
            continue

        # 1. Ban wildcard imports
        for node in ast.walk(c.head_tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        out.append(_ev("R14_REGULATORY_STYLE_VIOLATION", f"{c.path}:{node.lineno} wildcard import 'from {node.module} import *' violates styling regulations", c.path, node.lineno, severity="block"))

        # 2. Ban bare except: or silent exception swallowing
        for node in ast.walk(c.head_tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    out.append(_ev("R14_REGULATORY_STYLE_VIOLATION", f"{c.path}:{node.lineno} bare 'except:' clause violates error handling regulations", c.path, node.lineno, severity="block"))
                elif isinstance(node.body, list) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    out.append(_ev("R14_REGULATORY_STYLE_VIOLATION", f"{c.path}:{node.lineno} silent exception swallowing ('except: pass') violates code safety regulations", c.path, node.lineno, severity="block"))

        # 3. Ban debugging print() / debugger statements in non-cli non-test code
        if not c.is_test and not c.path.endswith("cli.py"):
            for node in ast.walk(c.head_tree):
                if isinstance(node, ast.Call):
                    name = _call_name(node)
                    if name in ("print", "breakpoint", "pdb.set_trace"):
                        out.append(_ev("R14_REGULATORY_STYLE_VIOLATION", f"{c.path}:{node.lineno} debug '{name}()' call committed in production module", c.path, node.lineno, severity="review"))
    return out


Rule = Callable[[list[FileChange]], list[Evidence]]
RULES: list[Rule] = [
    r1_deleted_test,
    r2_skipped_test,
    r3_weakened_assert,
    r4_mocked_subject,
    r6_out_of_scope_tests,
    r7_dangerous_call,
    r10_runtime_integrity,
    r11_performance_regression,
    r12_complexity_inflation,
    r13_style_inconsistency,
    r14_regulatory_style_violation,
]


def check_rules(pr: PullRequest) -> list[Evidence]:
    chs = changes(pr)
    evidence: list[Evidence] = [
        _ev("R9_UNPARSEABLE", f"{c.path} does not parse at the PR head", c.path, None, severity="review")
        for c in chs
        if c.head is not None and c.head_tree is None
    ]
    for rule in RULES:
        evidence.extend(rule(chs))
    evidence.extend(r5_r8_literal_special_cases(chs, _all_test_literals(pr)))
    return evidence

