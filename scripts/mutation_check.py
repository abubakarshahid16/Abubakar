"""Mutation harness: delete a feature, prove its tests fail, restore it.

WHY THIS FILE EXISTS

CLAUDE.md rule 6 says every new test must fail when its feature is deleted, and
`docs/status-honesty-audit.md` records vacuous tests as this project's recurring
defect - now at instance 6, which was a pair of MIGRATION tests that passed with
the migration deleted because the fixture built the table from the current
schema. That pair was caught by running this harness and by nothing else.

A harness that lives in one session's scratchpad proves a claim once and cannot
be re-run by a reviewer. Section 14 of `docs/AI_SUBMITTAL_REVIEW_HANDOFF.md`
tells a reviewer to verify "permission tests are mutation-proven" by deleting
the filter and re-running. This script is that instruction, executable.

HOW IT WORKS

Each mutation names a file, an exact anchor string to replace, a replacement,
and the tests that must then FAIL. The entries live in `scripts/mutations/`,
one file per module they mutate (see its `__init__.py`); this file is the
harness. For every mutation the harness:

  1. copies the file to `<file>.mutbak`,
  2. refuses to continue if the anchor is not found EXACTLY once - an anchor
     that silently stops matching turns a mutation into a no-op, and a no-op
     mutation reports "tests passed" and looks like a vacuous test,
  3. applies the replacement, runs the selected tests,
  4. restores the file in a `finally` block, so an exception, a timeout or a
     Ctrl-C cannot leave the working tree patched.

A mutation whose tests still PASS is a failure of this harness, not a success:
it means the tests do not observe the feature.

USAGE

    python scripts/mutation_check.py                 # every mutation
    python scripts/mutation_check.py --list          # ids and descriptions
    python scripts/mutation_check.py --only M1 M4    # a subset
    python scripts/mutation_check.py --phase 1       # one phase's set

Run it from the repository root, with the Python 3.12 environment the backend
suite uses. Exit code 0 means every mutation was detected; 1 means at least one
was not, and the summary names it.

SAFETY

This script EDITS SOURCE FILES IN PLACE and restores them. Run it on a clean
working tree so that `git status` after a run is the proof it restored
everything. It never touches the database and never runs the full suite.
"""

from __future__ import annotations

import argparse
import importlib
import os
import pkgutil
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# The registry lives beside this file; make it importable however the
# harness is loaded (`python scripts/mutation_check.py`, or a test).
_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import mutations  # noqa: E402
from mutations._base import (  # noqa: E402,F401 - re-exported
    APP, BACKEND, FRONTEND_SRC, REPO, TESTS, Mutation,
)

#: The interpreter that runs the suite. The project venv first, because
#: `run.py` refuses anything but 3.12 and a 3.10 on PATH would fail every
#: mutation for the wrong reason - which reads exactly like a detected
#: mutation and would be a false green.
_VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
_VENV_PY_POSIX = REPO / ".venv" / "bin" / "python"


def _python() -> str:
    for candidate in (_VENV_PY, _VENV_PY_POSIX):
        if candidate.exists():
            return str(candidate)
    return sys.executable


#: THE REGISTRY. Entries live in `scripts/mutations/`, one file per module they
#: mutate, each defining `MUTATIONS`. They used to be ~6,400 lines of this
#: file, and every PR that added a mutation conflicted with every other one.
def registry_modules() -> list[str]:
    """Every registry module, sorted so ALL is built deterministically."""
    return sorted(info.name for info in pkgutil.iter_modules(mutations.__path__)
                  if not info.name.startswith("_"))


def aggregate(sources: Iterable[tuple[str, tuple[Mutation, ...]]]) -> tuple[Mutation, ...]:
    """Concatenate `(module name, MUTATIONS)` pairs, refusing a duplicate id.

    Ids are how `--only` selects a mutation and how tests and docs cite one.
    Two files each defining the same id would make `--only M123` run both and
    a citation ambiguous, and with the entries now spread over many files a
    collision is no longer visible in one screen - so it is refused at import.
    """
    seen: dict[str, str] = {}
    out: list[Mutation] = []
    for name, entries in sources:
        for m in entries:
            if m.id in seen:
                raise ValueError(f"duplicate mutation id {m.id!r}: defined in "
                                 f"mutations.{seen[m.id]} and mutations.{name}")
            seen[m.id] = name
            out.append(m)
    return tuple(out)


def load_registry() -> tuple[Mutation, ...]:
    return aggregate(
        (name, importlib.import_module(f"mutations.{name}").MUTATIONS)
        for name in registry_modules())


ALL: tuple[Mutation, ...] = load_registry()


FRONTEND = REPO / "frontend"
#: The vitest binary as npm installed it. Called directly rather than through
#: `npx`, which on this project's Windows checkout can reach for a network
#: install; the local binary is the one the suite already runs.
_VITEST = FRONTEND / "node_modules" / ".bin" / (
    "vitest.cmd" if os.name == "nt" else "vitest")


def _ascii(text: str) -> str:
    """Printable on any console. A report that cannot be printed is no report."""
    return text.encode("ascii", "replace").decode("ascii")


def _run_tests(mutation: Mutation) -> tuple[int, str]:
    if mutation.runner == "vitest":
        cmd = [str(_VITEST), "run", mutation.target]
        if mutation.keyword:
            cmd += ["-t", mutation.keyword]
        # encoding/errors are NOT optional here. vitest prints box-drawing and
        # tick characters; on a Windows console defaulting to cp1252 the
        # decode raises, the harness treats the exception as a non-zero exit,
        # and EVERY mutation reports DETECTED whether or not the test noticed
        # anything. A harness that cannot read its runner's output is a harness
        # that reports a perfect score by accident - the exact failure this
        # file exists to catch.
        proc = subprocess.run(cmd, cwd=FRONTEND, capture_output=True, text=True,
                              timeout=900, shell=False,
                              encoding="utf-8", errors="replace")
        out = f"{proc.stdout}\n{proc.stderr}"
        # The counts line ("Tests  1 failed | 3 passed (4)"), not the "Failed
        # Tests" banner that also contains the word.
        counts = re.compile(r"Tests\s+\d+\s+(?:failed|passed)")
        summary = next(
            (ln.strip() for ln in reversed(out.splitlines()) if counts.search(ln)),
            "(no counts line)")
        # Flattened to ASCII before it is ever printed. vitest's summary
        # carries box-drawing and tick characters, and a Windows console at
        # cp1252 raises on ENCODE as readily as it did on decode - killing the
        # harness mid-run, after the mutation was applied but before the
        # `finally` had printed anything useful.
        return proc.returncode, _ascii(summary)
    # STALE BYTECODE CAN HAND ONE MUTATION ANOTHER'S VERDICT. Python reuses a
    # cached .pyc when the source's size and whole-second mtime match the
    # cache. Two consecutive mutations that change a file by the same number
    # of characters inside one second therefore ran the FIRST one's code for
    # the second: found 2026-09-22, when M296 and M297 each shortened
    # synthesis.py by exactly 23 characters and M297 reported NOT DETECTED -
    # its tests had executed M296's mutant. So: never write bytecode during a
    # mutation run (`-B`), and delete any cached copy of the mutated module
    # first, so the run can only ever compile the source as it now stands.
    for stale in (mutation.path.parent / "__pycache__").glob(f"{mutation.path.stem}.*.pyc"):
        stale.unlink(missing_ok=True)
    cmd = [_python(), "-B", "-m", "pytest", mutation.target, "-q", "--no-header",
           "-p", "no:cacheprovider"]
    if mutation.keyword:
        cmd += ["-k", mutation.keyword]
    # UTF-8 with replacement: decoding pytest's output with the Windows code
    # page (text=True's default) crashed the reader thread on a failure
    # message quoting a curly quote or minus sign, leaving stdout None and the
    # whole run aborted (found 2026-09-25 with M538/M539).
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    return proc.returncode, (lines[-1] if lines else "(no output)")


#: How many tests a run actually executed, out of its summary line. `None` when
#: the line cannot be read at all, which is itself a harness failure.
#: Words that mean a test RAN. `deselected` and `skipped` deliberately absent:
#: a deselected test was never collected and a skipped one never executed, so
#: neither is evidence that the mutation was observed by anything.
_PYTEST_COUNTS = re.compile(r"(\d+)\s+(passed|failed|error|errors|xfailed|xpassed)")
#: The same idea for pytest's "no tests ran" shapes, which carry only words
#: that mean nothing executed. Matched so the verdict can say so precisely
#: rather than "could not read a count".
_PYTEST_NOTHING = re.compile(r"\b\d+\s+(?:deselected|skipped)\b|no tests ran")
_VITEST_COUNTS = re.compile(r"(\d+)\s+(failed|passed)")


def _tests_collected(runner: str, summary: str) -> int | None:
    """The number of tests the run executed, from its own summary.

    THE HARNESS MUST NOT TRUST THE EXIT CODE ALONE. pytest exits 5 when it
    collects NOTHING - a `-k` expression that matches no test - and 5 is
    non-zero, which this file used to read as "the tests failed", which is what
    DETECTED means. Two mutations passed that way having executed no test at
    all, printing "49 deselected" with no pass or fail count, and were
    indistinguishable from the hundred that proved something.

    So the verdict now needs evidence that tests RAN. This reads the count out
    of the runner's own summary line; a summary with no counts in it returns
    None and the run is a harness error, not a result.
    """
    text = summary or ""
    if runner == "vitest":
        if "Tests" not in text:
            return None
        found = _VITEST_COUNTS.findall(text)
        return sum(int(n) for n, _word in found) if found else 0
    found = _PYTEST_COUNTS.findall(text)
    if found:
        # "1 failed, 20 deselected" counts the 1 and not the 20, which is the
        # whole point: deselected tests did not run.
        return sum(int(n) for n, _word in found)
    # Nothing executed, said in pytest's own words.
    return 0 if _PYTEST_NOTHING.search(text) else None


def run(mutation: Mutation) -> tuple[str, str]:
    """Apply, test, restore. Returns `(verdict, summary)`."""
    path = mutation.path
    if not path.exists():
        return "ERROR", f"file not found: {path}"
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(mutation.anchor)
    if occurrences != 1:
        # NOT a pass. An anchor that stopped matching means the mutation never
        # ran, and a mutation that never ran cannot detect anything.
        return "ERROR", (f"anchor matched {occurrences} times, expected exactly 1 "
                         f"- the mutation was NOT applied")
    backup = path.with_suffix(path.suffix + ".mutbak")
    shutil.copyfile(path, backup)
    try:
        path.write_text(source.replace(mutation.anchor, mutation.replacement, 1),
                        encoding="utf-8")
        code, summary = _run_tests(mutation)
    finally:
        shutil.copyfile(backup, path)
        os.remove(backup)
    # A VERDICT NEEDS TESTS TO HAVE RUN. Checked before the exit code is read,
    # because a run that executed nothing has no verdict to give - whatever it
    # exited with.
    ran = _tests_collected(mutation.runner, summary)
    if ran is None:
        return "HARNESS_ERROR", f"could not read a test count from: {summary}"
    if ran == 0:
        return "HARNESS_ERROR", (
            f"the run executed NO tests ({summary}) - the target or keyword "
            f"selects nothing, so this mutation proves nothing")
    return ("DETECTED" if code != 0 else "NOT DETECTED"), summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list mutations and exit")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run these ids only")
    parser.add_argument("--phase", type=int, help="run one phase's mutations")
    args = parser.parse_args()

    selected = list(ALL)
    if args.phase is not None:
        selected = [m for m in selected if m.phase == args.phase]
    if args.only:
        wanted = {i.upper() for i in args.only}
        selected = [m for m in selected if m.id.upper() in wanted]
        missing = wanted - {m.id.upper() for m in selected}
        if missing:
            print(f"unknown mutation id(s): {', '.join(sorted(missing))}")
            return 2

    if args.list:
        for m in selected:
            print(f"{m.id:>4}  phase {m.phase}  [{','.join(m.tags) or '-'}]  {m.description}")
        return 0

    if not selected:
        print("no mutations selected")
        return 2

    print(f"python: {_python()}")
    print(f"running {len(selected)} mutation(s)\n")
    results = []
    for m in selected:
        print(f"  {m.id} ... ", end="", flush=True)
        verdict, summary = run(m)
        print(f"{verdict}  ({summary})")
        results.append((m, verdict, summary))

    print("\n" + "=" * 78)
    detected = [r for r in results if r[1] == "DETECTED"]
    harness = [r for r in results if r[1] in ("HARNESS_ERROR", "ERROR")]
    vacuous = [r for r in results if r[1] == "NOT DETECTED"]
    print(f"{len(detected)}/{len(results)} mutations detected"
          f"  |  {len(vacuous)} not detected  |  {len(harness)} harness error")
    if harness:
        # REPORTED SEPARATELY AND FIRST. A harness error is not a result in
        # either direction: the mutation did not run, or ran nothing, so it
        # says nothing about the tests. Counting it as detected is how two
        # mutations came to pass while executing no tests at all.
        print("\nHARNESS ERROR - these mutations produced no evidence:")
        for m, verdict, summary in harness:
            print(f"  {m.id} [{verdict}] {m.description}")
            print(f"       {summary}")
    if vacuous:
        print("\nNOT DETECTED - the tests do not observe these features:")
        for m, verdict, summary in vacuous:
            print(f"  {m.id} [{verdict}] {m.description}")
            print(f"       {summary}")
        print("\nA mutation that is not detected means the test is VACUOUS.")
        print("Record it per CLAUDE.md rule 7 and fix the test, not the harness.")
    return 1 if (harness or vacuous) else 0


if __name__ == "__main__":
    raise SystemExit(main())
