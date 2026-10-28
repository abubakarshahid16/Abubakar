"""Rule cards: every checklist rule is tested with the REAL checking code before it may give a verdict (order 296).

A card is a checklist item of `reference/datasheet_checks.json` (its words, box, limit, clause and page are the
item's own: one home) plus test cases. A case is a small invented sheet (the facts of one box) and the status
the real code must give:

  * meets   - a value the rule accepts                       -> COMPLIANT
  * breaks  - a value the rule refuses, or the value missing -> NON_COMPLIANT / MISSING_INFORMATION
  * unclear - a placeholder or two different values          -> MISSING_INFORMATION / NEEDS_ENGINEER_REVIEW

`run_card` calls `datasheet_checks.evaluate` itself on a one-item checklist: no copy of the comparison. Pure; no
model, no database, no network. Cases here are GENERATED from the rule's kind and so test the code, not the rule's
meaning; a person's cases (`item["tests"]`) test the meaning and are kept apart (`kind: "written"`).
"""

from __future__ import annotations

from . import datasheet_checks as dc

COMPLIANT, NON_COMPLIANT = dc.COMPLIANT, dc.NON_COMPLIANT
MISSING, REVIEW = dc.MISSING_INFORMATION, dc.NEEDS_ENGINEER_REVIEW

#: Rule kinds a case can be generated for. Any other kind needs a written case (`item["tests"]`).
GENERATED_KINDS = ("required", "allowed")


def field_name_of(role: str, rules: dict) -> str | None:
    """A field name the real role reader maps to `role`, or None when none of the obvious spellings does."""
    for name in (role.replace("_", " "), f"{role.replace('_', ' ')}."):
        if dc.role_of(name, rules) == role:
            return name
    return None


def _fact(
    name: str, value: str | None, *, tag: str = "a", blank: str | None = None
) -> dict:
    return {
        "id": f"card-{name}-{value}-{tag}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": value,
        "raw_value": None if blank else value,
        "raw_unit": None,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 1 if blank else 0,
        "blank_marker": blank,
        "value_note": None,
        "page": 1,
        "equipment_tag": None,
    }


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


def run_card(item: dict, equipment_type: str, rules: dict | None = None) -> dict:
    """The card's result: every case run, and its status: `tested` only when there are at least three cases
    (meets, breaks, unclear) and all passed; `draft` otherwise, with the reason."""
    rules = rules or dc.load_rules()
    cases = [*generated_cases(item, rules), *(item.get("tests") or [])]
    runs = [run_case(item, equipment_type, c, rules) for c in cases]
    names = {r["case"] for r in runs}
    if not runs:
        status, why = "draft", "no test cases for this kind of rule"
    elif not {"meets", "breaks", "unclear"} <= names:
        status, why = "draft", "needs a meets, a breaks and an unclear case"
    elif not all(r["passed"] for r in runs):
        status, why = "draft", "a case failed"
    else:
        status, why = "tested", ""
    return {"id": item["id"], "status": status, "why": why, "runs": runs}
