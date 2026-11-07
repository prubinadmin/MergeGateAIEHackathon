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
    "R10_RUNTIME_INTEGRITY": "the PR removes a public name that other code still imports (ImportError at runtime)",
    "R11_PERFORMANCE_REGRESSION": "an edited function gains a nested loop or a blocking sleep (review)",
    "R12_COMPLEXITY_INFLATION": "an edited function gets much more complex, or a new one is very complex (review)",
    "R13_STYLE_INCONSISTENCY": "new camelCase names in a snake_case module, or dropped type hints (review)",
    "R14_REGULATORY_STYLE_VIOLATION": "new wildcard import, bare except, swallowed exception, print (review) or debugger call (block)",
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


# --- Integrity, performance, simplicity, style (R10-R14) ---------------------------
# Like R7, each check compares the PR head with base and reports only what the PR introduces:
# code that was already there is the owner's earlier decision, not this PR's. Only changes that
# break or hang production block; quality signals (loops, complexity, style) go to REVIEW.


def _changed_functions(c: FileChange) -> dict[str, tuple[ast.AST | None, ast.AST]]:
    """name -> (base version or None if new, head version), for functions the PR adds or edits."""
    base_fns = _functions(c.base_tree)
    out: dict[str, tuple[ast.AST | None, ast.AST]] = {}
    for name, fn in _functions(c.head_tree).items():
        old = base_fns.get(name)
        if old is None or ast.dump(old) != ast.dump(fn):
            out[name] = (old, fn)
    return out


def _new_items(base: list[tuple[str, int]], head: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Items (key, line) whose key occurs more often at head than at base."""
    seen: dict[str, int] = {}
    for key, _ in base:
        seen[key] = seen.get(key, 0) + 1
    out = []
    for key, line in head:
        if seen.get(key, 0) > 0:
            seen[key] -= 1
        else:
            out.append((key, line))
    return out


def _public_names(tree: ast.Module | None) -> set[str]:
    names: set[str] = set()
    if tree is None:
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {n for n in names if not n.startswith("_")}


def r10_runtime_integrity(chs: list[FileChange], pr: PullRequest) -> list[Evidence]:
    """The PR removes or renames a public name that other code still imports: an ImportError at runtime."""
    removed: dict[str, set[str]] = {}
    for c in chs:
        if c.is_test or c.base_tree is None or (c.head is not None and c.head_tree is None):
            continue  # unparseable heads are R9's job
        gone = _public_names(c.base_tree) - _public_names(c.head_tree)
        if gone:
            removed[module_name(c.path)] = gone
    if not removed:
        return []
    out = []
    try:
        files = pr.git("ls-tree", "-r", "--name-only", pr.head_ref).splitlines()
    except Exception:
        return out
    for path in files:
        if not path.endswith(".py"):
            continue
        tree = _parse(pr.file_at(pr.head_ref, path))
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in removed:
                for alias in node.names:
                    if alias.name in removed[node.module]:
                        out.append(_ev("R10_RUNTIME_INTEGRITY",
                                       f"{path}:{node.lineno} imports {alias.name} from {node.module}, which this PR removes",
                                       path, node.lineno))
    return out


def _nested_loop_line(fn: ast.AST) -> int | None:
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            for sub in ast.walk(node):
                if sub is not node and isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
                    return node.lineno
    return None


def _sleeps(fn: ast.AST | None) -> list[tuple[str, int]]:
    if fn is None:
        return []
    return [("sleep", n.lineno) for n in ast.walk(fn)
            if isinstance(n, ast.Call) and _call_name(n) in ("time.sleep", "sleep")]


def r11_performance_regression(chs: list[FileChange]) -> list[Evidence]:
    """A changed function gains a nested loop or a blocking sleep it did not have before. Review only."""
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None:
            continue
        for name, (old, new) in _changed_functions(c).items():
            line = _nested_loop_line(new)
            if line and (old is None or _nested_loop_line(old) is None):
                out.append(_ev("R11_PERFORMANCE_REGRESSION", f"{name}() in {c.path} gains a nested loop (possible O(n^2))", c.path, line, severity="review"))
            for _, ln in _new_items(_sleeps(old), _sleeps(new)):
                out.append(_ev("R11_PERFORMANCE_REGRESSION", f"{name}() in {c.path} adds a blocking sleep()", c.path, ln, severity="review"))
    return out


def _cyclomatic_complexity(fn: ast.AST) -> int:
    complexity = 1
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += max(0, len(node.values) - 1)
        elif isinstance(node, getattr(ast, "match_case", ())):
            complexity += 1
    return complexity


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    max_d = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try, ast.With)):
            d = _max_nesting_depth(child, current + 1)
        else:
            d = _max_nesting_depth(child, current)
        max_d = max(max_d, d)
    return max_d


def r12_complexity_inflation(chs: list[FileChange]) -> list[Evidence]:
    """A function the PR edits gets much more complex, or a new function is very complex. Review only."""
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None:
            continue
        for name, (old, new) in _changed_functions(c).items():
            cc, depth = _cyclomatic_complexity(new), _max_nesting_depth(new)
            if old is not None:
                old_cc, old_depth = _cyclomatic_complexity(old), _max_nesting_depth(old)
                if cc >= old_cc + 4:
                    out.append(_ev("R12_COMPLEXITY_INFLATION", f"{name}() in {c.path} goes from complexity {old_cc} to {cc}", c.path, new.lineno, severity="review"))
                elif depth >= 4 and depth > old_depth:
                    out.append(_ev("R12_COMPLEXITY_INFLATION", f"{name}() in {c.path} now nests {depth} levels deep (was {old_depth})", c.path, new.lineno, severity="review"))
            elif cc > 10:
                out.append(_ev("R12_COMPLEXITY_INFLATION", f"new function {name}() in {c.path} has complexity {cc}", c.path, new.lineno, severity="review"))
    return out


SNAKE = re.compile(r"^_*[a-z][a-z0-9_]*$")
CAMEL = re.compile(r"^_*[a-z]+[A-Z][a-zA-Z0-9]*$")


def r13_style_inconsistency(chs: list[FileChange]) -> list[Evidence]:
    """New camelCase functions in a snake_case module, or type hints dropped from an edited function. Review only."""
    out = []
    for c in chs:
        if c.is_test or c.head_tree is None or c.base_tree is None:
            continue
        base_names = [n.split(".")[-1] for n in _functions(c.base_tree)]
        snake_module = bool(base_names) and sum(bool(SNAKE.match(n)) for n in base_names) / len(base_names) >= 0.8
        for name, (old, new) in _changed_functions(c).items():
            short = name.split(".")[-1]
            if old is None and snake_module and CAMEL.match(short):
                out.append(_ev("R13_STYLE_INCONSISTENCY", f"new function {short}() in {c.path} is camelCase in a snake_case module", c.path, new.lineno, severity="review"))
            if old is not None:
                had = old.returns is not None or any(a.annotation for a in old.args.args)
                has = new.returns is not None or any(a.annotation for a in new.args.args)
                if had and not has:
                    out.append(_ev("R13_STYLE_INCONSISTENCY", f"{name}() in {c.path} loses its type hints", c.path, new.lineno, severity="review"))
    return out


def _style_items(tree: ast.Module | None, path: str) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    if tree is None:
        return items
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            items.append((f"wildcard:{node.module}", node.lineno))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                items.append(("bare_except", node.lineno))
            elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                items.append(("except_pass", node.lineno))
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in ("breakpoint", "pdb.set_trace", "ipdb.set_trace"):
                items.append(("debugger", node.lineno))
            elif name == "print" and not is_test_path(path) and not path.endswith(("cli.py", "__main__.py")):
                items.append(("print", node.lineno))
    return items


STYLE_TEXT = {
    "bare_except": ("a bare except:", "review"),
    "except_pass": ("an exception silently swallowed (except ...: pass)", "review"),
    "debugger": ("a debugger breakpoint that halts the process", "block"),
    "print": ("a leftover print() in library code", "review"),
}


def r14_regulatory_style_violation(chs: list[FileChange]) -> list[Evidence]:
    """New wildcard imports, bare excepts, swallowed exceptions, prints (review); a new debugger call blocks."""
    out = []
    for c in chs:
        if c.head_tree is None:
            continue
        for key, line in _new_items(_style_items(c.base_tree, c.path), _style_items(c.head_tree, c.path)):
            if key.startswith("wildcard:"):
                text, sev = f"a wildcard import from {key.split(':', 1)[1]}", "review"
            else:
                text, sev = STYLE_TEXT[key]
            out.append(_ev("R14_REGULATORY_STYLE_VIOLATION", f"{c.path}:{line} adds {text}", c.path, line, severity=sev))
    return out


Rule = Callable[[list[FileChange]], list[Evidence]]
RULES: list[Rule] = [
    r1_deleted_test,
    r2_skipped_test,
    r3_weakened_assert,
    r4_mocked_subject,
    r6_out_of_scope_tests,
    r7_dangerous_call,
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
    evidence.extend(r10_runtime_integrity(chs, pr))
    return evidence

