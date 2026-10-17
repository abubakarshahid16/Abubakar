"""#893 (PF2): a clause that NAMES the values a thing shall be, or only asks
for it to be stated, is paired with the sheet's row of that name.

PF1's first run (#881): 18 such clauses on 7 unfamiliar sheets were reported
as "not in the document", and 7 planted defects went with them.

What code may decide: the clause only asks for the thing to be stated and it
is -> met; the sheet's value is one of the named values, letter for letter
-> met. A value that is NOT one of them is never a breach by code (another
name for the same steel is not a breach): it goes to the engineer with both
sides shown. Invented clauses only; no model, no socket.
"""
from __future__ import annotations

import pytest

from app import comparison, db, field_links, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "r.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _req(text, subject, clause="7.2"):
    return {"id": f"req-{clause}", "standard_document_id": "doc_std", "clause": clause,
            "requirement_type": "statement", "requirement_text": text, "source_text": text, "subject": subject}


def _fact(name, value, *, method="geometry", blank=False, number=None, unit=None, page=1):
    return {"id": f"f-{name}-{method}", "document_id": "doc_sheet", "submittal_document_id": "doc_sheet",
            "field_name": name, "field_label": name.title(), "field_value": value, "raw_value": number,
            "raw_unit": unit, "is_blank": 1 if blank else 0, "blank_marker": value if blank else None,
            "extraction_method": method, "page": page, "equipment_tag": None}


CASING = "The casing material shall be carbon steel or stainless steel grade 316."
BODY = "The body material shall be WCB or CF8M."
STATED = "The impeller material shall be stated on the datasheet."


def _judge(text, subject, facts):
    req = _req(text, subject)
    match = comparison.match_statement(req, facts)
    return match, comparison._compare(req, match["fact"], submittal_facts=facts)


# ------------------------------------------------------------------ the pairing
def test_a_row_that_states_a_name_is_paired_with_the_clause_about_it():
    match, verdict = _judge(CASING, "casing material", [_fact("casing material", "Cast iron"),
                                                        _fact("service", "Cooling water")])
    assert match["fact"]["field_name"] == "casing material" and match["method"] == comparison.METHOD_CONTAINMENT
    assert verdict["status"] != comparison.NOT_IN_DOCUMENT_SCOPE


def test_a_one_word_label_does_not_claim_a_clause_that_says_the_word():
    """Free text beside a label is where noise comes from: "Service: Cooling
    water" must not answer every clause with "service" in its subject."""
    match, verdict = _judge("The pump in sour service shall be hardness tested.", "pump in sour service",
                            [_fact("service", "Cooling water"), _fact("type", "Horizontal")])
    assert match["fact"] is None and verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_two_readers_reading_the_same_words_are_one_answer_and_differing_readings_a_question():
    same = [_fact("casing material", "Cast iron"), _fact("casing material", "cast  IRON", method="model")]
    match, _verdict = _judge(CASING, "casing material", same)
    assert match["fact"]["extraction_method"] == "geometry" and match["reason"] is None
    differ = [_fact("casing material", "Cast iron"), _fact("casing material", "Carbon steel", method="model")]
    match, verdict = _judge(CASING, "casing material", differ)
    assert match["fact"] is None and match["reason"] == comparison.AMBIGUOUS_MATCH
    assert verdict["status"] != comparison.COMPLIANT


def test_a_plural_subject_meets_the_singular_row():
    match, verdict = _judge("The shaft seals shall be tandem dry gas seals.", "shaft seals",
                            [_fact("shaft seal", "Tandem dry gas seal")])
    assert match["fact"]["field_name"] == "shaft seal" and verdict["status"] == comparison.COMPLIANT


def test_a_blank_row_is_still_the_contractors_to_provide():
    _match, verdict = _judge(CASING, "casing material", [_fact("casing material", "By Vendor", blank=True)])
    assert verdict["status"] == comparison.MISSING_INFORMATION


# ------------------------------------------------------------------ the verdict
def test_a_value_the_clause_names_is_met_and_says_which_values_were_named():
    _match, verdict = _judge(BODY, "body material", [_fact("body material", "wcb")])
    assert verdict["status"] == comparison.COMPLIANT and verdict["rationale"].startswith(comparison.NAMED_VALUE)
    assert "WCB; CF8M" in verdict["rationale"] and verdict["observed"] == "wcb"


def test_a_value_the_clause_does_not_name_goes_to_the_engineer_never_a_breach_by_code():
    """THE PLANTED DEFECT of PF1: cast iron where carbon steel or 316 is
    asked. Found - and not called a breach, because "SS 316" against
    "stainless steel grade 316" would be called one by the same code."""
    for stated in ("Cast iron", "SS 316", "Stainless steel 316"):
        _match, verdict = _judge(CASING, "casing material", [_fact("casing material", stated)])
        assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW, stated
        assert stated in verdict["rationale"] and "carbon steel; stainless steel grade 316" in verdict["rationale"]
        assert verdict["status"] not in (comparison.COMPLIANT, comparison.NON_COMPLIANT)


def test_a_clause_that_only_asks_for_the_thing_to_be_stated_is_met_when_it_is():
    _match, verdict = _judge(STATED, "impeller material", [_fact("impeller material", "Stainless steel 316")])
    assert verdict["status"] == comparison.COMPLIANT and verdict["rationale"].startswith(comparison.STATED_AS_ASKED)
    _match, verdict = _judge("The joint efficiency shall be stated on the datasheet.", "joint efficiency",
                             [_fact("joint efficiency", "0.85", number="0.85")])
    assert verdict["status"] == comparison.COMPLIANT                    # a stated number is stated too


# ------------------------------------------------- what counts as named values
@pytest.mark.parametrize("text, names", [
    (CASING, ("carbon steel", "stainless steel grade 316")),
    (BODY, ("WCB", "CF8M")),
    ("The enclosure rating shall be IP66, IP67 or IP68.", ("IP66", "IP67", "IP68")),
    ("The exchanger shall be a removable-bundle type.", ("removable-bundle type",)),
    ("The seat leakage class shall be either Class IV or Class V.", ("Class IV", "Class V")),
])
def test_the_values_a_clause_names(text, names):
    assert field_links.named_values(text) == names


@pytest.mark.parametrize("text", [
    "The casing material shall not be cast iron.",                               # a prohibition
    "The casing shall be carbon steel unless the purchaser agrees otherwise.",   # a condition
    "In sour service the trim shall be Alloy 625.",                              # a service condition
    "The body shall be WCB and the trim shall be 316.",                          # two requirements
    "The trim shall be stainless steel 316 and hard faced.",                     # both, not either
    "The design pressure shall be at least 16 barg.",                            # a limit
    "The vessel shall be designed for full vacuum.",                             # an action
    "The casing material shall be stated on the datasheet.",                     # asks for a statement
    "The material shall be a grade that the purchaser has approved for this particular duty in writing.",
    "Carbon steel is preferred.", "", None,
])
def test_when_unsure_a_clause_names_no_values(text):
    assert field_links.named_values(text) is None


def test_one_of_the_named_values_means_letter_for_letter():
    names = ("carbon steel", "stainless steel grade 316", "tandem dry gas seals")
    assert field_links.is_named_value("Carbon Steel", names) and field_links.is_named_value("carbon-steel", names)
    assert field_links.is_named_value("Tandem dry gas seal", names)              # a plural names the same thing
    for other in ("Cast iron", "steel", "carbon steel lined", "stainless steel 316", "SS 316", "", None):
        assert not field_links.is_named_value(other, names), other
    assert not field_links.is_named_value("WCB", None)


@pytest.mark.parametrize("text, asks", [
    (STATED, True),
    ("The datasheet shall state the coupling type.", True),
    ("The fail position shall be shown on the data sheet.", True),
    ("The seal plan shall be stated on the datasheet unless a seal-less pump is offered.", False),
    ("The hardness need not be stated on the datasheet.", False),
    ("The casing material shall be carbon steel.", False),
])
def test_a_clause_that_asks_only_for_a_statement(text, asks):
    assert field_links.asks_only_to_be_stated(text) is asks


def test_a_conditional_clause_naming_values_is_not_decided_by_this_rule():
    """`named_values` refuses it, so the stated value cannot be called met
    because it happens to be one of the words in the sentence."""
    text = "In sour service the trim material shall be Alloy 625 or Alloy C-276."
    _match, verdict = _judge(text, "trim material", [_fact("trim material", "Alloy 625")])
    assert verdict["status"] != comparison.COMPLIANT
