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


def sources(checklist: dict) -> dict:
    """`datasheet_checks.checklist_sources`: what `comparison` needs to know of a checklist."""
    return {
        "key": checklist["key"],
        "items": len(checklist["items"]),
        "standards": standards(checklist),
        "draft": checklist["draft"],
    }


def keeps_standards(checklist: dict) -> bool:
    """Lock 2: a checklist not yet signed cannot decide, so while it is a draft the standards it cites stay in
    scope, rule by rule, each under its own trust label. A signed checklist governs as before."""
    from .config import settings

    return settings.draft_checklist_keeps_standards_enabled and bool(
        checklist.get("draft")
    )


def set_aside(
    governing: dict, covered_ids: set, requirements: list[dict], gated: dict
) -> tuple[list[dict], list[dict], dict, dict]:
    """#746: the requirements of the governed standards leave the comparison, each with its reason.
    Returns (covered items, the requirements left, the gate's result without those cells, the run's note)."""

    def covered(requirement: dict) -> bool:
        return requirement.get("standard_document_id") in covered_ids

    detail = (
        f"the {governing['key']} review checklist governs this standard "
        f"({governing['items']} items); not checked one by one"
    )
    cells = gated["not_compared_items"]
    items = [
        {"requirement": requirement, "code": "covered_by_checklist", "detail": detail}
        for requirement in [dict(r) for r in requirements if covered(r)]
        + [i["requirement"] for i in cells if covered(i["requirement"])]
    ]
    note = {
        "type": governing["key"],
        "items": governing["items"],
        "standards": len(covered_ids),
    }
    left = {
        **gated,
        "not_compared_items": [i for i in cells if not covered(i["requirement"])],
    }
    return items, [r for r in requirements if not covered(r)], left, note


def review_type(classification: dict | None) -> str | None:
    """The equipment type a REVIEW CHECKLIST may be chosen from (order 264, found by the 2p gate on a vessel sheet). A
    checklist marked `type_from_title_only` (the vessel and exchanger drafts) is chosen only when the
    type was read from the sheet's title or confirmed by a person; a type that only a passing mention in
    the body gave ("heat exchanger" twice on a drum sheet, `body_phrase_match`) chooses none, and the
    sheet gets no checklist (its other checks, DS-R1 included, still use the stored type).
    Every other type is returned as stored."""
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


def evaluate(facts: list[dict], classification: dict, page_texts: dict) -> list[dict]:
    """The datasheet checks of one review: the stored type for every check, the
    checklist only when `review_type` allows it (cloud, #1390: the revision-block
    check DS-R1 must not stop with the checklist)."""
    from . import datasheet_checks

    rules = datasheet_checks.load_rules()
    if review_type(classification) is None:
        rules = {**rules, "checklists": {}}
    return datasheet_checks.evaluate(
        facts,
        equipment_type=classification.get("equipment_type"),
        page_texts=page_texts,
        rules=rules,
    )
