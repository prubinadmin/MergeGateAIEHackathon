"""Build Merge Gate benchmark cases from real bugs in BugsInPy (https://github.com/soarsmu/BugsInPy).

For every BugsInPy bug (a buggy commit, a fixed commit, the source patch, and a test that fails on the
buggy code and passes on the fixed code) we make two pull requests in a clone of the upstream project:

  bad   base = the fixed commit, head = the patch reverted.   It re-introduces a real bug.  Label BLOCK.
  clean base = the buggy commit, head = the patch applied.    It is the real fix.          Label PASS.

Every label is checked before it is kept: BugsInPy's own test must pass on base and fail on head for a
bad PR, and fail on base and pass on head for a clean PR, run in this benchmark's venv. Bugs that cannot
be reproduced here (old code that does not run on this Python, missing dependencies, patch that does not
apply) are skipped and listed, never forced. The gate never sees that test.

Issue texts are written by us (BugsInPy has none) and never describe the bug. true_owner_email comes from
git blame on the changed lines, so routing on these cases is NOT an independent measurement; use the
synthetic demo repo for routing. Catch rate and false-block rate are the point here.

Usage:  MERGE_GATE_SANDBOX_PYTHON=benchmark/bugsinpy/.venv38/Scripts/python python benchmark/bugsinpy/build_bugsinpy.py [--projects PySnooper,thefuck] [--max 8]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # repo root: benchmark/bugsinpy/ -> .
sys.path.insert(0, ROOT)

from merge_gate.owners import resolve_owners  # noqa: E402
from merge_gate.pr import PullRequest  # noqa: E402
from merge_gate.sandbox import SANDBOX_PYTHON_ENV, export_ref  # noqa: E402

PY = os.environ.get(SANDBOX_PYTHON_ENV) or sys.executable

META = os.path.join(HERE, "_bugsinpy", "meta", "projects")
REPOS = os.path.join(HERE, "target_repos")
CASES = os.path.join(HERE, "cases")
AGENT = ("coding-agent", "agent@bots.example")
OUTSIDER = ("outside-contributor", "dev@outside.example")


def kv(path: str) -> dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*(\w+)\s*=\s*"(.*)"', line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def git(repo: str, *args: str, who: tuple[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if who:
        env.update(GIT_AUTHOR_NAME=who[0], GIT_AUTHOR_EMAIL=who[1], GIT_COMMITTER_NAME=who[0], GIT_COMMITTER_EMAIL=who[1])
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, check=check)


def make_branch(repo: str, branch: str, start: str, patch: str, reverse: bool, who: tuple[str, str], msg: str) -> str | None:
    git(repo, "checkout", "-q", "-f", "-B", branch, start)
    r = git(repo, "apply", *(["-R"] if reverse else []), "--whitespace=nowarn", patch, check=False)
    if r.returncode != 0:
        git(repo, "checkout", "-q", "-f", start)
        return None
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, who=who)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def test_commands(bug_dir: str) -> list[list[str]]:
    cmds = []
    with open(os.path.join(bug_dir, "run_test.sh"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = shlex.split(line)
            head = parts[0]
            if head in ("pytest", "py.test", "tox"):
                parts = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *[p for p in parts[1:] if p not in ("-s",)]]
            elif head in ("python", "python3"):
                parts = [PY, *parts[1:]]
            else:
                continue
            cmds.append(parts)
    return cmds


def fixed_tests(repo: str, fixed: str, info: dict[str, str]) -> dict[str, str]:
    """BugsInPy's ground-truth test files, as they are in the fixed commit (often added by the fix)."""
    out = {}
    for path in [p.strip() for p in info.get("test_file", "").split(";") if p.strip()]:
        r = git(repo, "show", f"{fixed}:{path}", check=False)
        if r.returncode == 0:
            out[path] = r.stdout
    return out


def passes(repo: str, ref: str, cmds: list[list[str]], overlay: dict[str, str], timeout: int = 180, debug: bool = False) -> bool | None:
    """True/False = BugsInPy's test passed/failed at ref; None = could not run (collection/import error)."""
    work = tempfile.mkdtemp(prefix="bip-")
    try:
        export_ref(repo, ref, work)
        for path, src in overlay.items():
            full = os.path.join(work, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(src)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("MUSE", "GITHUB", "SENDBLUE", "OWNER_", "MERGE_GATE"))}
        env.update(PYTHONPATH=work, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        for cmd in cmds:
            try:
                p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            except subprocess.TimeoutExpired:
                return None
            out = p.stdout + p.stderr
            if debug:
                print(f"--- rc={p.returncode} {' '.join(cmd[2:])}\n{out[-1500:]}")
            if p.returncode in (2, 3, 4, 5) or "ImportError" in out and "failed" not in out.lower():
                return None
            if p.returncode != 0:
                return False
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def changed_names(patch_path: str) -> list[str]:
    with open(patch_path, encoding="utf-8", errors="replace") as f:
        return sorted({m.group(1) for m in re.finditer(r"^\+\+\+ b/(\S+)", f.read(), re.M)})


def write_case(case_id: str, repo_rel: str, base: str, head: str, title: str, issue: str, opened_by: str,
               kind: str, verdict: str, owner: str, split: str, source: dict) -> None:
    d = os.path.join(CASES, case_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "case.json"), "w", encoding="utf-8") as f:
        json.dump({"pr_id": case_id, "repo": repo_rel, "base_ref": base, "head_ref": head, "title": title,
                   "issue_text": issue, "opened_by": opened_by,
                   "label": {"kind": kind, "true_verdict": verdict, "true_owner_email": owner, "split": split},
                   "source": source}, f, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default="PySnooper,cookiecutter,thefuck")
    ap.add_argument("--max", type=int, default=8, help="max bugs tried per project")
    args = ap.parse_args()

    kept, skipped, n = [], [], 0
    for project in args.projects.split(","):
        repo = os.path.join(REPOS, project)
        bugs_dir = os.path.join(META, project, "bugs")
        if not os.path.isdir(repo) or not os.path.isdir(bugs_dir):
            print(f"skip project {project}: missing clone or metadata")
            continue
        for bug in sorted(os.listdir(bugs_dir), key=int)[: args.max]:
            bdir = os.path.join(bugs_dir, bug)
            info = kv(os.path.join(bdir, "bug.info"))
            patch = os.path.join(bdir, "bug_patch.txt")
            buggy, fixed = info.get("buggy_commit_id", ""), info.get("fixed_commit_id", "")
            cmds = test_commands(bdir)
            tag = f"{project}#{bug}"
            if not (buggy and fixed and cmds):
                skipped.append((tag, "incomplete metadata"))
                continue
            if git(repo, "cat-file", "-e", f"{fixed}^{{commit}}", check=False).returncode != 0:
                skipped.append((tag, "fixed commit not in clone"))
                continue
            files = ", ".join(changed_names(patch)) or "the module"
            source = {"dataset": "BugsInPy", "project": project, "bug": int(bug), "github_url": info.get("github_url", ""),
                      "buggy_commit": buggy, "fixed_commit": fixed, "ground_truth_test": " && ".join(" ".join(c[2:]) for c in cmds)}

            bad_head = make_branch(repo, f"mg/{bug}-reintroduce", fixed, patch, True, AGENT, f"refactor: simplify {files}")
            fix_head = make_branch(repo, f"mg/{bug}-fix", buggy, patch, False, OUTSIDER, f"fix: {files}")
            if not bad_head or not fix_head:
                skipped.append((tag, "patch does not apply"))
                continue

            ov = fixed_tests(repo, fixed, info)
            dbg = os.environ.get("BIP_DEBUG") == tag
            on_fixed, on_bad = passes(repo, fixed, cmds, ov, debug=dbg), passes(repo, bad_head, cmds, ov, debug=dbg)
            on_buggy, on_fix = passes(repo, buggy, cmds, ov, debug=dbg), passes(repo, fix_head, cmds, ov, debug=dbg)
            # Base of the bad PR and head of the fix must pass. The other two must not pass: a failed test
            # or code that no longer even imports both count, since either way the bug is observable.
            if not (on_fixed is True and on_fix is True and on_bad is not True and on_buggy is not True):
                skipped.append((tag, f"ground truth not reproducible here (fixed={on_fixed}, reverted={on_bad}, buggy={on_buggy}, patched={on_fix})"))
                continue

            split = "train" if n % 2 == 0 else "heldout"
            n += 1
            rel = os.path.relpath(repo, HERE).replace("\\", "/")
            bad_pr = PullRequest(f"bip-{project}-{bug}-bad", repo, fixed, bad_head)
            fix_pr = PullRequest(f"bip-{project}-{bug}-clean", repo, buggy, fix_head)
            bad_owner = (resolve_owners(bad_pr) or [None])[0]
            fix_owner = (resolve_owners(fix_pr) or [None])[0]
            write_case(bad_pr.pr_id, rel, fixed, bad_head, f"Simplify {files}",
                       f"Clean up {files}: simplify the implementation and remove special cases that look unnecessary. Behaviour must not change.",
                       "A coding agent", "logic_bug", "BLOCK", bad_owner.email if bad_owner else "", split, source)
            write_case(fix_pr.pr_id, rel, buggy, fix_head, f"Fix incorrect behaviour in {files}",
                       f"There is a bug in {files}: some inputs give the wrong result. Fix it without changing the public interface.",
                       "An outside contributor", "clean", "PASS", fix_owner.email if fix_owner else "", split, source)
            kept.append(tag)
            print(f"kept {tag} ({split})", flush=True)

    print(f"\n{len(kept)} bugs kept -> {2 * len(kept)} cases; {len(skipped)} skipped")
    for tag, why in skipped:
        print(f"  skipped {tag}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
