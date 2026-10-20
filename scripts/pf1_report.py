"""Report one run of the PF1 unfamiliar-datasheet set, counts only (#881).

    python scripts/pf1_report.py --set D:\\project\\pf1-set\\set --runs D:\\project\\pf1-set\\runs\\main-1
        [--json report.json] [--check]

Reads the builder's `index.json` and the answer keys in `--set`, and for each
sheet `<id>.findings.json` (`review_score.py export`) and `<id>.run.json`
(`pf1_run.py`) in `--runs`. Prints the per-type table and the totals (markdown,
to post on the tracking comment). HELD-OUT sheets are in the totals and never
named. `--check` exits 1 when any planted defect was called Meets (the hard
rule is 0). A sheet with no run is listed as such, never scored as zeros. The
first run of a set is the baseline: no pass or fail. Format and procedure:
eval/review/pf1.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import pf1_report  # noqa: E402
from tools import review_score as rs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--set", required=True, help="the folder pf1_set.py build wrote"
    )
    parser.add_argument(
        "--runs", required=True, help="a folder of <id>.findings.json and <id>.run.json"
    )
    parser.add_argument("--json", help="also write the report as JSON here")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 on any false Meets"
    )
    args = parser.parse_args(argv)
    try:
        index, keys, findings, runs = pf1_report.load_set(args.set, args.runs)
        report = pf1_report.build_report(index, keys, findings, runs)
    except (pf1_report.ReportError, rs.KeyError_, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(pf1_report.render(report), end="")
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    return 1 if args.check and report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
