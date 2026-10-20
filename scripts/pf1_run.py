"""Run a PF1 set through a TEST server and write run records (#881).

    python scripts/pf1_run.py --set D:\\project\\pf1-set\\set --out D:\\project\\pf1-set\\runs \\
        --server http://127.0.0.1:11435 --test-server --email EMAIL --discipline DISCIPLINE

The password is read from the environment variable PF1_PASSWORD, never from an
argument. Held-out sheets are skipped unless --include-held-out. Prints COUNTS
ONLY. Scoring is a separate step on a copy of the server's database
(`scripts/review_score.py export` then `score`). Procedure: eval/review/pf1.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import pf1_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--set", required=True, help="the folder `pf1_set.py build` wrote"
    )
    parser.add_argument(
        "--out", required=True, help="where the run records go (outside git)"
    )
    parser.add_argument("--server", required=True)
    parser.add_argument(
        "--test-server",
        action="store_true",
        help="the server is a test server, not the live app",
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--discipline", action="append", default=[])
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only this sheet id (repeatable)",
    )
    parser.add_argument("--include-held-out", action="store_true")
    parser.add_argument(
        "--no-standards",
        action="store_true",
        help="the library already holds the standards",
    )
    parser.add_argument(
        "--timeout", type=float, default=3600.0, help="seconds per step"
    )
    args = parser.parse_args(argv)
    try:
        base = pf1_run.check_server(args.server, args.test_server)
        password = os.environ.get("PF1_PASSWORD", "")
        if not password:
            raise pf1_run.RunError("set PF1_PASSWORD in the environment")
        index = json.loads((Path(args.set) / "index.json").read_text(encoding="utf-8"))
        transport = pf1_run.HttpTransport(base)
        transport.token = pf1_run.login(transport, args.email, password)
        records = pf1_run.run_set(
            transport,
            index,
            Path(args.set),
            Path(args.out),
            include_held_out=args.include_held_out,
            only=args.only or None,
            timeout=args.timeout,
            with_standard=not args.no_standards,
            disciplines=args.discipline or None,
        )
    except (pf1_run.RunError, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(pf1_run.summary(records), indent=2))
    return 0 if all(r["status"] == "completed" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
