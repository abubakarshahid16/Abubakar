"""Build the PF1 unfamiliar-datasheet test set from a local spec (#881).

    python scripts/pf1_set.py build --spec D:\\project\\pf1-set\\spec.json --out D:\\project\\pf1-set\\set
    python scripts/pf1_set.py check --spec D:\\project\\pf1-set\\spec.json

`build` writes, per document, the invented sheet, the invented standard it
cites and the answers (`review-answer-key/1`), plus `index.json`. `check`
validates the spec and writes nothing. Both print COUNTS ONLY: the set and
its answers stay on this machine and never enter git (the builder refuses an
output folder inside a repository). Format and procedure: eval/review/pf1.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import pf1_set  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "check"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--spec", required=True)
        if name == "build":
            cmd.add_argument("--out", required=True)
            cmd.add_argument("--allow-in-git", action="store_true",
                             help="build invented TUNING sheets into tests/data/pf1 (never held-out or library)")
    args = parser.parse_args(argv)
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        if args.command == "check":
            pf1_set.validate(spec)
            print(f"OK: {len(spec['documents'])} document(s) in the spec; nothing written")
            return 0
        index = pf1_set.build(spec, args.out, allow_in_git=args.allow_in_git)
    except (pf1_set.SpecError, OSError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(json.dumps(pf1_set.summary(index), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
