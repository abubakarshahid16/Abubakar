"""Run the rule cards of every checklist through the real checking code (order 296). Counts only; no model.

    python scripts/rule_cards.py            # the report: per checklist, cards tested / draft and why
    python scripts/rule_cards.py --check    # exit 0 only when EVERY card is tested (the release gate, 296.4)

A card is `tested` when its meets / breaks / unclear cases all gave the expected status from
`datasheet_checks.evaluate`. A card without cases for its kind of rule stays `draft`: the report says how many.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def report() -> dict:
    from app import datasheet_checks as dc
    from app import rule_cards

    rules = dc.load_rules()
    out: dict = {}
    for equipment_type, checklist in rules["checklists"].items():
        if not isinstance(checklist, dict):
            continue
        cards = [
            rule_cards.run_card(i, equipment_type, rules) for i in checklist["items"]
        ]
        why = collections.Counter(c["why"] for c in cards if c["status"] != "tested")
        out[equipment_type] = {
            "cards": len(cards),
            "tested": sum(c["status"] == "tested" for c in cards),
            "draft": sum(c["status"] != "tested" for c in cards),
            "draft_because": dict(why),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    result = report()
    print(json.dumps(result, indent=1))
    if args.check and any(v["draft"] for v in result.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
