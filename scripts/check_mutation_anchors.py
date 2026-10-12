"""Check every mutation anchor WITHOUT running any test.

`scripts/mutation_check.py` refuses a mutation whose anchor does not match its
target file exactly once (it reports ERROR / HARNESS ERROR), but it only finds
out when that mutation is run, which takes a test run each. After a refactor
the registry can hold stale anchors for weeks unnoticed. This script loads the
same registry and does only the cheap part: read each target file, count the
anchor, and report any mutation whose count is not exactly 1 (or whose file is
missing).

    python scripts/check_mutation_anchors.py

Exit code 0: every anchor matches exactly once. 1: at least one is stale.
Run it from the repository root.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from mutations._base import Mutation  # noqa: E402


def find_stale(mutations: Iterable[Mutation]) -> list[tuple[Mutation, str]]:
    """Return `(mutation, reason)` for each mutation whose anchor is not
    found exactly once. Files are read once each and cached."""
    cache: dict[Path, str | None] = {}
    stale: list[tuple[Mutation, str]] = []
    for m in mutations:
        if m.path not in cache:
            try:
                cache[m.path] = m.path.read_text(encoding="utf-8")
            except (FileNotFoundError, IsADirectoryError):
                cache[m.path] = None
        source = cache[m.path]
        if source is None:
            stale.append((m, f"file not found: {m.path}"))
            continue
        count = source.count(m.anchor)
        if count != 1:
            stale.append((m, f"anchor matches {count} times, expected exactly 1"))
    return stale


def main() -> int:
    import mutation_check  # loads the registry; no side effects beyond import

    stale = find_stale(mutation_check.ALL)
    total = len(mutation_check.ALL)
    if not stale:
        print(f"OK: all {total} mutation anchors match exactly once")
        return 0
    print(f"STALE: {len(stale)} of {total} mutation anchors do not match exactly once\n")
    for m, reason in stale:
        try:
            rel = m.path.relative_to(mutation_check.REPO)
        except ValueError:
            rel = m.path
        print(f"  {m.id}  {rel}")
        print(f"       {reason}")
        print(f"       {m.description}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
