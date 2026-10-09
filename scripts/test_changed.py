"""Run only the tests mapped to the files changed against origin/main (LOCAL use).

The full backend suite takes many minutes on a laptop. Before pushing, this runs
the part of it that the change can plausibly break, plus `vitest related` for
frontend files. It does NOT replace CI: the required check still runs the whole
suite on every pull request.

    python scripts/test_changed.py              # run the mapped tests
    python scripts/test_changed.py --dry-run    # only print what would run
    python scripts/test_changed.py --base origin/main

Changed files = committed since the merge base with --base, plus staged,
unstaged and untracked files. Mapping:

  backend/tests/test_*.py          -> that file
  backend/app/<module>.py          -> tests that import app.<module>, and tests/test_<module>*.py
  scripts/<name>.py                -> tests that mention <name>.py or scripts/<name>
  frontend/src/**, frontend/tests/** -> `npx vitest related --run <files>`
  conftest.py, pytest.ini, requirements.txt, package files
                                   -> reported: these can affect any test, so run the whole suite

A changed file that maps to no test is listed, so "nothing ran" is never silent.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WHOLE_SUITE = {"backend/tests/conftest.py", "backend/pytest.ini", "backend/requirements.txt",
               "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts",
               "frontend/vitest.config.ts"}


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def changed_files(base: str) -> list[str]:
    files = set(_git("diff", "--name-only", f"{base}...HEAD"))
    files |= set(_git("diff", "--name-only"))
    files |= set(_git("diff", "--name-only", "--cached"))
    files |= set(_git("ls-files", "--others", "--exclude-standard"))
    return sorted(f.replace("\\", "/") for f in files)


def backend_tests_for(paths: list[str], tests_dir: Path) -> tuple[set[str], set[str]]:
    """(test files relative to backend/, changed paths that mapped to nothing)."""
    tests = sorted(tests_dir.glob("test_*.py"))
    texts = {t: t.read_text(encoding="utf-8", errors="replace") for t in tests}
    selected: set[str] = set()
    unmapped: set[str] = set()
    for p in paths:
        hit: set[Path] = set()
        if p.startswith("backend/tests/") and Path(p).name.startswith("test_") and p.endswith(".py"):
            t = tests_dir / Path(p).name
            if t.exists():
                hit.add(t)
        elif p.startswith("backend/app/") and p.endswith(".py"):
            mod = Path(p).stem
            pat = re.compile(rf"\bapp\.{re.escape(mod)}\b|\bfrom app import\b[^\n]*\b{re.escape(mod)}\b")
            hit |= {t for t, s in texts.items() if pat.search(s)}
            hit |= {t for t in tests if t.name.startswith(f"test_{mod}")}
        elif p.startswith("scripts/") and p.endswith(".py"):
            name = Path(p).stem
            hit |= {t for t, s in texts.items() if f"{name}.py" in s or f"scripts/{name}" in s}
        else:
            continue
        if hit:
            selected |= {f"tests/{t.name}" for t in hit}
        else:
            unmapped.add(p)
    return selected, unmapped


FRONTEND = re.compile(r"frontend/(src|tests)/.*\.(ts|tsx)$")


def frontend_files(paths: list[str]) -> list[str]:
    return [p[len("frontend/"):] for p in paths if FRONTEND.match(p)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    paths = changed_files(args.base)
    whole = [p for p in paths if p in WHOLE_SUITE]
    backend, unmapped = backend_tests_for(paths, REPO / "backend" / "tests")
    frontend = frontend_files(paths)
    mapped_kinds = ("backend/tests/", "backend/app/", "scripts/")
    outside = [p for p in paths if p not in WHOLE_SUITE and not p.startswith(mapped_kinds)
               and not FRONTEND.match(p)]

    print(f"{len(paths)} changed file(s) against {args.base}")
    if whole:
        print("  can affect ANY test - run the whole suite before pushing:", ", ".join(whole))
    for p in sorted(unmapped):
        print(f"  no test mapped: {p}")
    for p in outside:
        print(f"  outside the mapping (CI still covers it): {p}")
    print(f"backend: {len(backend)} test file(s)" + ("" if backend else " - nothing to run"))
    for t in sorted(backend):
        print(f"  {t}")
    print(f"frontend: {len(frontend)} file(s) for `vitest related`" + ("" if frontend else " - nothing to run"))
    if args.dry_run:
        return 0

    def run_all() -> int:
        rc = 0
        if backend:
            rc |= subprocess.run([sys.executable, "-m", "pytest", "-q", *sorted(backend)],
                                 cwd=REPO / "backend").returncode
        if frontend:
            npx = "npx.cmd" if sys.platform == "win32" else "npx"
            rc |= subprocess.run([npx, "vitest", "related", "--run", *frontend],
                                 cwd=REPO / "frontend").returncode
        return rc

    # One heavy job at a time on this machine (#680).
    sys.path.insert(0, str(REPO / "backend"))
    from app import heavy_lock

    return heavy_lock.run_locked("tests", run_all)


if __name__ == "__main__":
    sys.exit(main())
