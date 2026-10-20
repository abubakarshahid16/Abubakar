"""A value the reader recorded as the PURCHASER'S requirement is never the
contractor's submitted value (#882, A-1246).

The AI reader records a value's kind (required, offered, measured) in the fact's
`section` as `model:<kind>`; a code reader's kind is its column header
(`datasheet_ai.rule_kind`). A `required` one leaves the pool every matcher and
judge draws from; a clause left with only that value is MISSING_INFORMATION,
naming the page, never a verdict. Values with no recorded kind are unchanged.
"""

from __future__ import annotations

#: The section a reader gives a value it recorded as the purchaser's requirement.
REQUIRED_SECTION = "model:required"
#: Why `match_rules.refusal` refuses a pairing with such a value.
REQUIRED_KIND = "required_kind"
#: The finding's reason when the sheet gives only the purchaser's own value.
REQUIRED_VALUE_ONLY = "required_value_only"


def is_purchaser_kind(fact: dict | None) -> bool:
    """True for a value the AI reader recorded as required (`section`) AND for one
    a code reader took from a column the header calls the purchaser's: the
    geometry reader's `value_column` and the table reader's "<label> - Required"
    (`datasheet_ai.rule_kind`, the one vocabulary for whose value a column holds)."""
    fact = fact or {}
    if str(fact.get("section") or "").strip().lower() == REQUIRED_SECTION:
        return True
    from . import datasheet_ai  # at call time: it is a large module

    return datasheet_ai.rule_kind(fact) == "required"


def split(facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the facts a review may use, the purchaser's own)."""
    kept: list[dict] = []
    purchaser: list[dict] = []
    for fact in facts:
        (purchaser if is_purchaser_kind(fact) else kept).append(fact)
    return kept, purchaser


def only_required_value(
    verdict: dict, requirement: dict, purchaser: list[dict], sheet, fact, rule_verdict
) -> dict:
    """When no field answered a clause and the only value the sheet gives it is
    the purchaser's own, the finding says the submittal states no offered value
    and names the page the requirement was read on. Any other verdict (a field
    was paired, a rule judged it) is returned as it came."""
    from . import comparison as cmp  # at call time: comparison imports this module

    if fact is not None or rule_verdict or not purchaser:
        return verdict
    if verdict.get("status") not in (
        cmp.MISSING_INFORMATION,
        cmp.NOT_IN_DOCUMENT_SCOPE,
    ):
        return verdict
    hits = cmp.match_by_containment(requirement, purchaser, sheet_kind=sheet)["refused"]
    seen = {r["name"] for r in hits if r["reason"] == REQUIRED_KIND}
    pages = sorted(
        {
            f["page"]
            for f in purchaser
            if f.get("page") is not None
            and cmp._normalise_for_match(f.get("field_name")) in seen
        }
    )
    if not pages:
        return verdict
    return {
        **verdict,
        "status": cmp.MISSING_INFORMATION,
        "rationale": (
            f"{REQUIRED_VALUE_ONLY}: the submittal does not state an offered value; the "
            "sheet's only value for this field is the purchaser's required one "
            f"(page {', '.join(str(n) for n in pages)}), which is not the contractor's submission"
        ),
    }
