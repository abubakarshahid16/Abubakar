"""Does a review checklist REPLACE its standards' library requirements? (order 235.2)

The relief-valve checklist governs the standards it cites: their library
requirements are not checked one by one, its items are (#746, planner decision).
That is right for a checklist that spells out the standard's checks. A checklist
that only asks "is this field stated" cannot stand in for a 1,000-clause
standard, and calling the standard "covered by the checklist" would be a claim
the checklist cannot back. So an entry says so in the data: `"governs": false`
(the pump checklist does) and its standards stay checked requirement by
requirement beside it. Absent, it governs, as before.
"""

from __future__ import annotations


def governs(entry: dict) -> dict:
    """The `governs` key the checklist carries, from its data entry."""
    return {"governs": entry.get("governs", True) is not False}


def standards(checklist: dict) -> list[str]:
    """The standards a checklist governs: those its items cite, or none when it
    does not replace them."""
    if not checklist.get("governs", True):
        return []
    return sorted({item["source"]["standard"] for item in checklist["items"]})


def review_type(classification: dict | None) -> str | None:
    """The equipment type a REVIEW CHECKLIST may be chosen from (order 264, 2p gate on 216400C). A
    checklist marked `type_from_title_only` (the vessel and exchanger drafts) is chosen only when the
    type was read from the sheet's title or confirmed by a person; a type that only a passing mention in
    the body gave ("heat exchanger" twice on a drum sheet, `body_phrase_match`) chooses none, and the
    sheet is then checked with the generic list. Every other type is returned as stored."""
    from . import datasheet_checks

    classification = classification or {}
    equipment_type = classification.get("equipment_type")
    if not equipment_type:
        return equipment_type
    table = datasheet_checks.load_rules().get("checklists") or {}
    entry = table.get(datasheet_checks.table_key(equipment_type, table))
    evidence = classification.get("equipment_type_evidence") or {}
    weak = evidence.get("method") == "body_phrase_match" and not classification.get(
        "confirmed"
    )
    if isinstance(entry, dict) and entry.get("type_from_title_only") and weak:
        return None
    return equipment_type
