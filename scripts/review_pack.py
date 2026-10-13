"""PF6 (#886): build the engineer review pack, and score a filled one back.

    python scripts\\review_pack.py build --main FINDINGS.json --secondary PSV.json --main-sample 40 --out OUTSIDE_REPO\\pack.xlsx
    python scripts\\review_pack.py score --pack FILLED.xlsx

`build` reads two `review-findings/1` files (`scripts/review_score.py export`
writes them) and writes the .xlsx pack; it refuses to write inside this
repository, because the pack carries requirement text and document names.
`score` prints counts only - ids and numbers, never a finding's text - fit to
post on #829 / #692.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import review_pack as rp  # noqa: E402


def _load_findings(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise rp.PackError(f"{path}: not a review-findings/1 file")
    return data["findings"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--main", required=True, help="review-findings/1 file: the MAIN (non-PSV) sample pool")
    b.add_argument("--secondary", required=True, help="review-findings/1 file: the SECONDARY (PSV) set")
    b.add_argument("--main-sample", type=int, required=True)
    b.add_argument("--secondary-sample", type=int, default=None,
                   help="omit to take every secondary row (#886: a fixed set)")
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--out", required=True)

    s = sub.add_parser("score")
    s.add_argument("--pack", required=True)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            out = Path(args.out).resolve()
            if REPO in out.parents:
                print("REFUSED: a review pack carries requirement text and document names; it stays outside this repository.")
                return 2
            pack = rp.build_pack(_load_findings(args.main), _load_findings(args.secondary),
                                 main_sample_size=args.main_sample,
                                 secondary_sample_size=args.secondary_sample, seed=args.seed)
            out.write_bytes(rp.render_pack(pack))
            print(f"{pack['counts']['main_sampled']} MAIN row(s) and "
                 f"{pack['counts']['secondary_sampled']} SECONDARY row(s) written to {out}. "
                 "No mark is filled in.")
            return 0
        if args.cmd == "score":
            filled = rp.read_pack(args.pack)
            result = rp.score_pack(filled)
            print(json.dumps(result, indent=1))
            return 0
    except rp.PackError as exc:
        print(f"REFUSED: {exc}")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
