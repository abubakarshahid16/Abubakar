"""Planted-defect sheets and their score (#1607). See `backend/tools/planted_defects.py`.

    python scripts/planted_defects.py generate --out DIR
    python scripts/planted_defects.py score --db COPY [--reader rules|fake|local-model]
                                            [--base relief_valve] [--save FILE.json]

Exit codes: 0 done (the numbers are printed, nothing here gates), 2 refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    from tools import planted_defects as pd

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="write the sheets and their answers")
    gen.add_argument("--out", required=True)
    run = sub.add_parser(
        "score", help="review the sheets on a copy and print the table"
    )
    run.add_argument("--db", required=True, help="a COPY of the database")
    run.add_argument("--reader", default="rules", choices=pd.READERS)
    run.add_argument("--base", help="one base by name (default: all)")
    run.add_argument("--save", help="write the per-sheet result as JSON")
    run.add_argument(
        "--settings-from",
        help="the backend/.env whose switches the review uses (a git worktree has none)",
    )
    args = ap.parse_args(argv)

    bases = pd.all_bases()
    if getattr(args, "base", None):
        bases = [b for b in bases if b["name"] == args.base]
    if args.command == "generate":
        for base in bases:
            manifest = pd.write_set(base, Path(args.out) / base["name"])
            print(f"{base['name']}: {len(manifest['sheets'])} sheets")
        return 0
    if not Path(args.db).exists():
        print(f"refused: {args.db} does not exist")
        return 2
    if args.settings_from:
        from tools import crs_bench

        crs_bench.use_settings_of(Path(args.settings_from))
    try:
        result = pd.score(
            Path(args.db),
            bases,
            reader=args.reader,
            log=lambda line: print(line, file=sys.stderr, flush=True),
        )
    except PermissionError as exc:
        print(f"refused: {exc}")
        return 2
    if args.save:
        Path(args.save).write_text(
            json.dumps(result, indent=1) + "\n", encoding="utf-8"
        )
    print(pd.render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
