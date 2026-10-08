"""Prove a sharded CI run executed every collected test exactly once (#589).

Two halves, stdlib only:

1. A pytest PLUGIN (`-p ci_test_ids`, with scripts/ on PYTHONPATH):
   - CI_TEST_IDS_OUT=<file>: append the node id of every test that RAN - one
     line per test, taken from its call phase, or from its setup phase when it
     was skipped or errored there (no call phase follows). Under pytest-xdist
     only the controller writes, so a worker's report is not counted twice.
   - CI_COLLECT_OUT=<file>: write the node id of every collected item (use with
     --collect-only and the same -m selection as the shards).

2. A COMPARE command, run by the aggregate `backend (pytest)` job:

       python scripts/ci_test_ids.py compare --full full.txt shard-1.txt shard-2.txt shard-3.txt

   Fails (exit 1) if any collected test ran in no shard, ran more than once, or
   ran without having been collected. Prints the counts either way.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path


# ------------------------------------------------------------------ plugin

#: True inside a pytest-xdist worker. The controller also receives every
#: worker's reports, so only the controller writes.
_WORKER = False


def pytest_configure(config):
    global _WORKER
    _WORKER = hasattr(config, "workerinput")


def ran_once(when: str, outcome: str) -> bool:
    """The one report per test that says it ran: its call phase, or its setup
    phase when setup skipped or errored (then no call phase follows)."""
    return when == "call" or (when == "setup" and outcome != "passed")


def pytest_runtest_logreport(report):
    out = os.environ.get("CI_TEST_IDS_OUT")
    if out and not _WORKER and ran_once(report.when, report.outcome):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(report.nodeid + "\n")


def pytest_collection_finish(session):
    out = os.environ.get("CI_COLLECT_OUT")
    if out and not _WORKER:
        Path(out).write_text("".join(i.nodeid + "\n" for i in session.items), encoding="utf-8")


# ----------------------------------------------------------------- compare

def compare(full: list[str], shards: dict[str, list[str]]) -> tuple[bool, list[str]]:
    """(ok, report lines). Every id in `full` must have run exactly once."""
    lines: list[str] = []
    ran = Counter()
    for name, ids in shards.items():
        ran.update(ids)
        lines.append(f"{name}: {len(ids)} ran")
    expected = set(full)
    dup_full = [i for i, n in Counter(full).items() if n > 1]
    missing = sorted(expected - set(ran))
    twice = sorted(i for i, n in ran.items() if n > 1)
    extra = sorted(set(ran) - expected)
    lines.append(f"collected: {len(full)} | ran in total: {sum(ran.values())} | distinct: {len(ran)}")
    for label, items in (("collected twice", dup_full), ("MISSING (collected, never ran)", missing),
                         ("RAN MORE THAN ONCE", twice), ("RAN BUT NOT COLLECTED", extra)):
        if items:
            lines.append(f"{label}: {len(items)}")
            lines.extend(f"  {i} (x{ran[i]})" if label.startswith("RAN MORE") else f"  {i}" for i in items[:50])
    ok = not (dup_full or missing or twice or extra) and bool(full)
    if not full:
        lines.append("EMPTY collection list - refusing to call that a pass")
    lines.append("OK: every collected test ran exactly once" if ok else "FAIL")
    return ok, lines


def _read(p: str) -> list[str]:
    return [line.strip() for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--full", required=True)
    c.add_argument("shards", nargs="+")
    args = ap.parse_args(argv)
    ok, lines = compare(_read(args.full), {Path(s).name: _read(s) for s in args.shards})
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
