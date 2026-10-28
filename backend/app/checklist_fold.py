"""One missing value is ONE request on the CRS (order 279.1).

A comparison item ("the cold differential test pressure does not exceed the set pressure") whose OWN field is
missing asks the contractor for the same value as the "is stated" item of that field ("the cold differential
test pressure is stated"). Both came out MISSING_INFORMATION and both reached the CRS. The comparison becomes
NOT_CALCULATED, which stores no row (`datasheet_checks.store`), and says which item asks for the value; the
"is stated" item stays the one row. Only the same field, the same tag and the same status fold; a comparison
whose OTHER side is missing is a different question and stays. Pure."""

from __future__ import annotations

MISSING = "MISSING_INFORMATION"
NOT_CALCULATED = "NOT_CALCULATED"


def fold_into_stated(results: list[dict], checklist: dict) -> list[dict]:
    kind = {i["id"]: i["rule"]["kind"] for i in checklist["items"]}
    asked: dict[tuple, str] = {}
    for r in results:
        if (
            r.get("checklist")
            and kind.get(r["rule_id"]) == "required"
            and r["status"] == MISSING
        ):
            asked.setdefault((r["equipment_tag"], r["role"]), r["rule_id"])
    folded = []
    for r in results:
        by = asked.get((r["equipment_tag"], r["role"]))
        if (
            by
            and r.get("checklist")
            and r["status"] == MISSING
            and kind.get(r["rule_id"]) not in (None, "required")
        ):
            what = str(r["role"]).replace("_", " ")
            r = {
                **r,
                "status": NOT_CALCULATED,
                "detail": f"Not checked: the {what} is not given; {by} asks for it.",
            }
        folded.append(r)
    return folded
