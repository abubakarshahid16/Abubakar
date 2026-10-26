"""Order 216: the checks every push must pass, run BEFORE the push.

Rule R1 (order 215) was written down and still skipped three times in one day,
so a machine now refuses the push. Only what the branch changed against
`origin/main` is checked, so it stays fast (target: under 60 s):

  * formatting of the lines the branch touched: `quality_ratchet.py format-check
    --base origin/main` - NOT whole-file `ruff format --check`, which would
    fail on every drifting line of a big file the branch only touched a little;
  * `check_lint_baseline.py check`, `check_mutation_anchors.py`,
    `check_system_map.py` (Python changes);
  * `gen_contract_types.py --check` when contract files or models changed;
  * the frontend type check when frontend files changed.

It also WARNS (never blocks) when the branch is behind `origin/main` (R2).

ruff is found the same way on the Mac and in cloud sessions: `$PRE_PUSH_PYTHON`,
then `backend/.venv`, then the Python running this script, `python3`, `python`;
the first that reports ruff 0.16.6 wins. If none does the push is REFUSED with
a message saying so - it never passes, or blocks, silently.

    python scripts/pre_push_guard.py            # what .githooks/pre-push runs
    python scripts/pre_push_guard.py --base origin/main
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUFF_VERSION = "0.16.6"
BUDGET_SECONDS = 60
FRONTEND_NODE_TSC = ("node_modules", "typescript", "bin", "tsc")


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    try:
        done = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, f"{type(exc).__name__}: {exc}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def has_ruff(python: str, root: Path = REPO) -> bool:
    code, out = _run([python, "-m", "ruff", "--version"], root, timeout=30)
    return code == 0 and RUFF_VERSION in out


def candidate_pythons(root: Path = REPO) -> list[str]:
    found = [os.environ.get("PRE_PUSH_PYTHON", "")]
    for rel in (
        ("backend", ".venv", "bin", "python"),
        ("backend", ".venv", "Scripts", "python.exe"),
    ):
        found.append(str(root.joinpath(*rel)))
    found += [
        sys.executable,
        shutil.which("python3") or "",
        shutil.which("python") or "",
    ]
    seen: list[str] = []
    for one in found:
        if one and one not in seen and (Path(one).exists() or shutil.which(one)):
            seen.append(one)
    return seen


def find_python(root: Path = REPO) -> str | None:
    return next((p for p in candidate_pythons(root) if has_ruff(p, root)), None)


def changed_files(base: str, root: Path = REPO) -> list[str] | None:
    code, out = _run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"], root, 60
    )
    return None if code else [line for line in out.splitlines() if line.strip()]


def is_behind(base: str, root: Path = REPO) -> bool:
    code, _ = _run(["git", "merge-base", "--is-ancestor", base, "HEAD"], root, 30)
    return code != 0


def _touches_models(files: list[str], root: Path) -> bool:
    for name in files:
        if name.startswith(("contracts/", "scripts/gen_")):
            return True
        if name.startswith("backend/app/") and name.endswith(".py"):
            try:
                text = (root / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "BaseModel" in text or "sent_defaults" in text:
                return True
    return False


def plan(
    files: list[str], python: str | None, root: Path = REPO
) -> list[tuple[str, list[str], Path, str]]:
    """(label, command, cwd, the fix to print on failure) for each check that applies."""
    steps: list[tuple[str, list[str], Path, str]] = []
    scripts = root / "scripts"
    if any(f.endswith(".py") for f in files) and python:
        steps.append(
            (
                "formatting of the lines this branch touched",
                [
                    python,
                    str(scripts / "quality_ratchet.py"),
                    "format-check",
                    "--base",
                    "origin/main",
                ],
                root,
                "format ONLY the lines you changed (or a new file whole): "
                "python -m ruff format <new-file>; for an old file, rewrap just your lines to ruff's shape",
            )
        )
        steps.append(
            (
                "ruff lint baseline",
                [python, str(scripts / "check_lint_baseline.py"), "check"],
                root,
                "fix the new finding it names (do not run `record` to hide it)",
            )
        )
        steps.append(
            (
                "mutation anchors",
                [python, str(scripts / "check_mutation_anchors.py")],
                root,
                "re-anchor the mutation it names in scripts/mutations/",
            )
        )
        steps.append(
            (
                "system map",
                [python, str(scripts / "check_system_map.py")],
                root,
                "list the new module in docs/system-map.md",
            )
        )
    if python and _touches_models(files, root):
        steps.append(
            (
                "contract types",
                [python, str(scripts / "gen_contract_types.py"), "--check"],
                root,
                "python scripts/gen_contract_types.py, then commit contracts/generated",
            )
        )
    if any(f.startswith("frontend/") for f in files):
        tsc = root / "frontend" / Path(*FRONTEND_NODE_TSC)
        node = shutil.which("node")
        if tsc.exists() and node:
            steps.append(
                (
                    "frontend type check",
                    [node, str(tsc), "-p", "tsconfig.app.json", "--noEmit"],
                    root / "frontend",
                    "fix the type error it names",
                )
            )
    return steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--root", default=str(REPO))
    args = ap.parse_args(argv)
    root = Path(args.root)
    started = time.monotonic()

    files = changed_files(args.base, root)
    if files is None:
        print(
            f"pre-push: {args.base} not found, nothing checked. Run: git fetch origin main"
        )
        return 0
    if is_behind(args.base, root):
        print(
            f"WARNING (R2): this branch is behind {args.base}. Merge main first: git merge {args.base}"
        )
    needs_python = any(f.endswith(".py") for f in files)
    python = find_python(root) if needs_python or _touches_models(files, root) else None
    if needs_python and python is None:
        print(
            f"pre-push: REFUSED. No Python with ruff {RUFF_VERSION} found, so the format and lint checks cannot run.\n"
            "  Looked at: $PRE_PUSH_PYTHON, backend/.venv, the Python running this hook, python3, python.\n"
            f"  Fix: python3 -m pip install ruff=={RUFF_VERSION}   (or: PRE_PUSH_PYTHON=/path/to/python git push)"
        )
        return 1
    failed = []
    for label, cmd, cwd, fix in plan(files, python, root):
        t0 = time.monotonic()
        code, out = _run(cmd, cwd)
        took = time.monotonic() - t0
        print(f"  {'ok  ' if code == 0 else 'FAIL'} {label} ({took:.0f}s)")
        if code:
            failed.append((label, fix))
            print(re.sub(r"(?m)^", "      ", out.strip()[-1500:]))
    total = time.monotonic() - started
    if total > BUDGET_SECONDS:
        print(f"  note: the checks took {total:.0f}s (target {BUDGET_SECONDS}s)")
    if failed:
        print("\npre-push: REFUSED. Fix, then push again:")
        for label, fix in failed:
            print(f"  - {label}: {fix}")
        print(
            "  (a hook bypass, `git push --no-verify`, is for an emergency only and is visible in review)"
        )
        return 1
    print(f"pre-push: ok ({len(files)} changed files, {total:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
