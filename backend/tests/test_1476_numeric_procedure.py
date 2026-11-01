"""#1476: a numeric_limit requirement on a procedure goes through the procedure path.

It used to return MISSING_INFORMATION ("no field read from the submittal"): the CRS asked the
contractor for something the procedure states. Now: found -> engineer row with page + verified
quote (and the two numbers in words when exactly one same-quantity measurement is in the quote);
not found -> the counted "no passage found" row. Never COMPLIANT / NON_COMPLIANT / MISSING.
All text is invented.
"""

from __future__ import annotations

from app import comparison, procedure_text
from app import requirements_3b as r3b

PAGES = [
    (1, "Permits. Each permit is valid for a single shift of 12 hours."),
    (2, "Calibration. Gauges are checked every 6 months and every 400 hours of use."),
    (3, "Storage. Spare seals are kept in a dry store."),
]


def _req(text, evidence=None):
    limit = r3b.parse_limit(text)
    return {
        "id": "r",
        "clause": "1",
        "requirement_type": r3b.classify(text, limit),
        "operator": (limit or {}).get("operator"),
        "raw_value": (limit or {}).get("raw_value"),
        "raw_unit": (limit or {}).get("raw_unit"),
        "requirement_text": text,
        "source_text": text,
        "required_evidence_type": evidence,
    }


def _go(text, fact=None, evidence=None):
    with procedure_text.using(PAGES):
        return comparison.compare(_req(text, evidence), fact)


def test_found_states_both_numbers_and_stays_an_engineer_row():
    text = "Each hot work permit shall be valid for a maximum of 8 hours."
    assert _req(text)["requirement_type"] == "numeric_limit"
    got = _go(text)
    assert got["status"] == comparison.NEEDS_ENGINEER_REVIEW
    why = got["rationale"]
    assert "found on page 1:" in why
    assert "the procedure states 12 hours; the requirement is at most 8 hours" in why
    assert "engineer to confirm" in why


def test_unit_code_is_used_minutes_against_hours_is_the_same_quantity():
    text = "Each permit shall be valid for a single shift of at least 90 minutes."
    why = _go(text)["rationale"]
    assert (
        "the procedure states 12 hours; the requirement is at least 90 minutes" in why
    )


def test_two_same_quantity_numbers_in_the_quote_are_not_compared():
    pages = [(1, "Gauges are checked every 6 months and re-certified every 24 months.")]
    with procedure_text.using(pages):
        why = comparison.compare(
            _req("Gauges shall be checked every 3 months at most."), None
        )["rationale"]
    assert "found on page 1:" in why and "the procedure states" not in why


def test_different_quantity_in_the_quote_is_not_compared():
    why = _go("Gauges shall be checked at most every 3 bar.")["rationale"]
    assert "the procedure states" not in why


def test_not_found_is_the_unfound_row_never_missing():
    got = _go("Spare gaskets shall be stored for a maximum of 5 years.")
    assert got["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert got["rationale"].startswith(procedure_text.NOT_FOUND)
    assert got["status"] != comparison.MISSING_INFORMATION


def test_never_compliant_or_failed():
    for text in (
        "Each hot work permit shall be valid for a maximum of 8 hours.",
        "Each hot work permit shall be valid for a maximum of 12 hours.",
        "Each hot work permit shall be valid for at least 20 hours.",
    ):
        assert _go(text)["status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_datasheet_submittal_is_unchanged():
    """No procedure pages: the old verdict (no fact -> MISSING_INFORMATION)."""
    text = "Each hot work permit shall be valid for a maximum of 8 hours."
    assert (
        comparison.compare(_req(text), None)["status"] == comparison.MISSING_INFORMATION
    )


def test_a_numeric_limit_that_names_another_document_is_not_routed():
    text = "A calibration certificate shall show a maximum error of 2 percent."
    req = _req(text, evidence="certificate")
    with procedure_text.using(PAGES):
        assert procedure_text.route(req, None) is None


def test_a_numeric_limit_with_a_fact_is_not_routed():
    req = _req("Each hot work permit shall be valid for a maximum of 8 hours.")
    with procedure_text.using(PAGES):
        assert procedure_text.route(req, {"raw_value": "5"}) is None


def test_the_unfound_numeric_row_is_counted_in_the_one_note():
    got = _go("Spare gaskets shall be stored for a maximum of 5 years.")
    note = procedure_text.notes(
        [{"clause": "9.1", "reason_code": got["rationale"]}], lambda f: f["clause"]
    )
    assert note and note[0]["count"] == 1 and "9.1" in note[0]["detail"]
