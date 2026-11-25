"""Same paper, same comments? (#1911). Compare TWO runs of the same paper and write the result as an xlsx. READ ONLY, no model, no answer key.

    python scripts/consistency_check.py <A> <B> [--label-a NAME] [--label-b NAME] [--different-versions] [--out-root DIR]

<A> and <B> are the team files (.xlsx, their "All points" sheet) or the page JSONs (.json, `points`) of two runs. The result goes to
`<out-root>/consistency-<a>-<b>/consistency.xlsx` (out-root defaults to ./consistency-out). Say `--different-versions` when the two runs are
NOT the same version of the app: the file then says "DIFFERENT VERSIONS, NOT A CONSISTENCY MEASURE" in its first line. Prints the counts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import aim_review_consistency as C  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", default=None)
    ap.add_argument("--label-b", default=None)
    ap.add_argument("--different-versions", action="store_true")
    ap.add_argument("--out-root", default="consistency-out")
    args = ap.parse_args(argv)
    label_a = args.label_a or Path(args.a).stem
    label_b = args.label_b or Path(args.b).stem
    try:
        res = C.compare(C.load(args.a), C.load(args.b))
    except (OSError, ValueError) as exc:
        print(f"cannot read the runs: {exc}")
        return 2
    out = (
        Path(args.out_root)
        / f"consistency-{C.slug(label_a)}-{C.slug(label_b)}"
        / "consistency.xlsx"
    )
    C.write_xlsx(res, out, label_a, label_b, same_version=not args.different_versions)
    for k, v in C.summary_lines(res, label_a, label_b, not args.different_versions):
        print(f"{k}: {v}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
