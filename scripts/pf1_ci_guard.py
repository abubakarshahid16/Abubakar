"""Print the job matrix of the PF1 CPU workflow, or refuse (#881, order 171).

    python scripts/pf1_ci_guard.py plan [--only ID ...]

Reads only `tests/data/pf1/`. Exit 2 and a plain message when any sheet is held
out, is of the library group, or names a file outside that folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import pf1_ci_guard  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("plan")
    cmd.add_argument("--only", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        matrix = pf1_ci_guard.plan(REPO, REPO / pf1_ci_guard.SET_DIR, args.only or None)
    except pf1_ci_guard.Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(matrix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
