"""Print what the Claude lane cost, per step, from the local spend ledger (#805 plan change 6 E).

Sends nothing. Adds up settled lines; an open reservation is listed apart and is not cost. For any run that is not
a review run (a review run writes its own record):

    python scripts/claude_spend_report.py --since 2026-11-02T08:00:00+00:00 --step-prefix standards_convert:
    python scripts/claude_spend_report.py --run <review run id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main(argv: list[str] | None = None) -> int:
    from app import claude_spend, claude_spend_report

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", help="one review run's id")
    parser.add_argument("--since", help="ISO time; only ledger lines from then on")
    parser.add_argument("--step-prefix", help="only steps starting with this")
    args = parser.parse_args(argv)
    lines = claude_spend.entries()
    figures = claude_spend_report.report(
        lines, run_id=args.run, since=args.since, step_prefix=args.step_prefix
    )
    figures["today_utc"] = {
        "charged_usd": claude_spend_report.charged_today(lines),
        "cap_usd": claude_spend_report.day_cap(),
        "boundary": "every route on this ledger; settled today plus open holds at their worst case",
    }
    print(json.dumps(figures, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
