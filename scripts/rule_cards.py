"""Rule cards: every checklist rule is tested with the REAL checking code before it may give a verdict (order 296).

    python scripts/rule_cards.py            # the report: per checklist, cards tested / draft and why
    python scripts/rule_cards.py --check    # exit 0 only when EVERY card is tested (the release gate, 296.4)

A card is a checklist item of `reference/datasheet_checks.json` (its words, box, limit, clause and page are the
item's own: one home) plus test cases. A case is a small invented sheet (the facts of one box) and the status the
real code must give:

  * meets   - a value the rule accepts                       -> COMPLIANT
  * breaks  - a value the rule refuses, or the value missing -> NON_COMPLIANT / MISSING_INFORMATION
  * unclear - a placeholder or two different values          -> MISSING_INFORMATION / NEEDS_ENGINEER_REVIEW

`run_card` calls `datasheet_checks.evaluate` itself on a one-item checklist: no copy of the comparison. No model, no
database, no network. Cases GENERATED from the rule's kind test the code, not the rule's meaning; a person's cases
(`item["tests"]`, kind "written") test the meaning and are kept apart. A card without cases for its kind of rule
stays `draft`. It lives in scripts/ until the review reads card status (step e of the plan); then it moves into the app.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import datasheet_checks as dc

COMPLIANT, NON_COMPLIANT = dc.COMPLIANT, dc.NON_COMPLIANT
MISSING, REVIEW = dc.MISSING_INFORMATION, dc.NEEDS_ENGINEER_REVIEW

#: Rule kinds a case can be generated for. Any other kind needs a written case (`item["tests"]`).
GENERATED_KINDS = ("required", "allowed")


def field_name_of(role: str, rules: dict) -> str | None:
    """A field name the real role reader maps to `role`: the role's own printed spelling first, else the role's words."""
    printed = list((rules["roles"].get(role) or {}).get("printed_as") or [])
    for name in (*printed, role.replace("_", " "), f"{role.replace('_', ' ')}."):
        if dc.role_of(name, rules) == role:
            return name
    return None


def _fact(
    name: str,
    value: str | None,
    *,
    tag: str = "a",
    blank: str | None = None,
    unit: str | None = None,
) -> dict:
    return {
        "id": f"card-{name}-{value}-{tag}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": None if blank else value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 1 if blank else 0,
        "blank_marker": blank,
        "value_note": None,
        "page": 1,
        "equipment_tag": None,
    }


TESTS_PATH = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "app"
    / "reference"
    / "rule_card_tests.json"
)


def written_cases(
    equipment_type: str, item_id: str, path: Path = TESTS_PATH
) -> list[dict]:
    """The cases a person wrote for one card (`reference/rule_card_tests.json`, kept apart from the item): each fact is
    [field name as the sheet prints it, value, unit or null]; each case names the status the real code must give."""
    if not path.exists():
        return []
    cases = (
        json.loads(path.read_text(encoding="utf-8")).get(equipment_type) or {}
    ).get(item_id) or []
    return [
        {
            "name": c["name"],
            "kind": "written",
            "facts": [
                _fact(
                    f[0],
                    f[1],
                    unit=f[2] if len(f) > 2 else None,
                    blank=f[1] if f[1] in ("*", "TBA") else None,
                )
                for f in c["facts"]
            ],
            "text": c.get("text", ""),
            "expect": c["expect"],
        }
        for c in cases
    ]


def generated_cases(item: dict, rules: dict) -> list[dict]:
    """The cases proposed for an item from its rule kind, [] when the kind has none or the box has no name."""
    rule = item["rule"]
    kind = rule["kind"]
    if kind not in GENERATED_KINDS or item.get("condition"):
        return []
    name = field_name_of(rule["field"], rules)
    if name is None:
        return []
    out = [
        {
            "name": "meets",
            "kind": "generated",
            "facts": [_fact(name, "7")],
            "text": "",
            "expect": COMPLIANT,
        },
        {
            "name": "breaks",
            "kind": "generated",
            "facts": [],
            "text": "nothing here",
            "expect": MISSING,
        },
        {
            "name": "unclear",
            "kind": "generated",
            "facts": [_fact(name, "*", blank="*")],
            "text": "",
            "expect": MISSING,
        },
    ]
    if kind == "allowed":
        allowed = str(rule["values"][0])
        out[0]["facts"] = [_fact(name, allowed)]
        out[1] = {
            "name": "breaks",
            "kind": "generated",
            "facts": [_fact(name, "zz-not-allowed")],
            "text": "",
            "expect": NON_COMPLIANT,
        }
        out[2] = {
            "name": "unclear",
            "kind": "generated",
            "facts": [
                _fact(name, allowed, tag="a"),
                _fact(name, "zz-not-allowed", tag="b"),
            ],
            "text": "",
            "expect": REVIEW,
        }
    return out


def run_case(item: dict, equipment_type: str, case: dict, rules: dict) -> dict:
    """Run one case through `datasheet_checks.evaluate` with a one-item checklist; the status it gave."""
    one = {
        **rules,
        "checklists": {
            equipment_type: {"items": [item], "sign_off": {"status": "draft"}}
        },
    }
    results = dc.evaluate(
        case["facts"],
        equipment_type=equipment_type,
        page_texts={1: case.get("text") or "x"},
        rules=one,
    )
    got = [r for r in results if r.get("rule_id") == item["id"]]
    status = got[0]["status"] if got else None
    return {
        "case": case["name"],
        "kind": case["kind"],
        "expected": case["expect"],
        "got": status,
        "passed": status == case["expect"],
    }


def cites_a_definition(item: dict, path: Path = TESTS_PATH) -> bool:
    """Is the card's source clause one of its standard's Terms and definitions (order 298.1)? A definition says what
    a word means; it requires nothing, so a card resting on it cannot be `tested`, whatever its cases say."""
    if not path.exists():
        return False
    sections = (
        json.loads(path.read_text(encoding="utf-8")).get("_definition_sections") or {}
    )
    source = item.get("source") or {}
    return any(
        str(source.get("clause") or "").startswith(prefix)
        for prefix in sections.get(source.get("standard"), [])
    )


def run_card(item: dict, equipment_type: str, rules: dict | None = None) -> dict:
    """The card's result: every case run, and its status: `tested` only when there are at least three cases
    (meets, breaks, unclear) and all passed; `draft` otherwise, with the reason."""
    rules = rules or dc.load_rules()
    cases = [
        *generated_cases(item, rules),
        *written_cases(equipment_type, item["id"]),
        *(item.get("tests") or []),
    ]
    runs = [run_case(item, equipment_type, c, rules) for c in cases]
    names = {r["case"] for r in runs}
    if cites_a_definition(item):
        status, why = "draft", "its source clause is a definition, not a requirement"
    elif not runs:
        status, why = "draft", "no test cases for this kind of rule"
    elif not {"meets", "breaks", "unclear"} <= names:
        status, why = "draft", "needs a meets, a breaks and an unclear case"
    elif not all(r["passed"] for r in runs):
        status, why = "draft", "a case failed"
    else:
        status, why = "tested", ""
    return {"id": item["id"], "status": status, "why": why, "runs": runs}


def report() -> dict:
    rules = dc.load_rules()
    out: dict = {}
    for equipment_type, checklist in rules["checklists"].items():
        if not isinstance(checklist, dict):
            continue
        cards = [run_card(i, equipment_type, rules) for i in checklist["items"]]
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
