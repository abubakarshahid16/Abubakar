"""Score CRS workbooks against an answer key by field role and paper page (owner answer 5, 11 Nov 2026).

    python scripts/answer_key_score.py --key KEY.xlsx --crs RUN1.xlsx [--crs RUN2.xlsx ...] [--json] [--rows]

The key and the CRS files stay on this machine (the key is built from a client CRS): pass their paths, never
copy them into the repo. The rule, the key's columns and every number are described in
`backend/tools/answer_key_score.py`. Output is counts with their denominators; --rows adds the key's sheet
row numbers and the matched CRS lines (sheet!row). No document text is printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import answer_key_score as aks  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--key",
        required=True,
        help="the answer key .xlsx (with Field role, Paper page, Scored as)",
    )
    ap.add_argument(
        "--crs",
        required=True,
        action="append",
        help="a CRS .xlsx; repeat for several runs",
    )
    ap.add_argument(
        "--sheet", help="the key's sheet (default: the first with the key columns)"
    )
    ap.add_argument("--json", action="store_true", help="print one JSON object per CRS")
    ap.add_argument(
        "--rows",
        action="store_true",
        help="also print the key row numbers behind each count",
    )
    a = ap.parse_args(argv)
    try:
        rules, patterns = aks._registry()
        key = aks.read_key(a.key, rules, a.sheet)
    except aks.AnswerKeyError as exc:
        print(f"answer key {Path(a.key).name}: {exc}", file=sys.stderr)
        return 2
    for crs in a.crs:
        res = aks.score(key, aks.read_crs(crs), patterns)
        out = {"crs": str(crs), **aks.summary(res)}
        if a.rows:
            out["rows"] = {
                k: res[k]
                for k in (
                    "problems_found",
                    "complies_confirmed",
                    "clear_wrong",
                    "disputed_raised",
                    "wrong_passes",
                    "word_only",
                    "other_clause_not_judged",
                    "key_rows_without_field",
                    "matched_lines",
                )
            }
        if a.json:
            print(json.dumps(out, default=list))
        else:
            print(
                f"{crs}: problems found {out['problems_found']} | complies confirmed "
                f"{out['complies_confirmed']} | clear wrong {out['clear_wrong']} | disputed raised "
                f"{out['disputed_raised']} | wrong passes {out['wrong_passes']} | other clause, not judged "
                f"{out['other_clause_not_judged']} | word only (not counted) {out['word_only_not_counted']}"
            )
            if a.rows:
                print(json.dumps(out["rows"], default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
