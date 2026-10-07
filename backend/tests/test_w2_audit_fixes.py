# ruff: noqa: RUF001  (Unicode minus, dashes and spaces are the point of these tests)
"""W2, the 7 Oct audit entries (#449). One section per entry; every test uses
invented text and is written to fail on the code as it stood before the fix.
"""
from __future__ import annotations

import json

import pytest

from app import (
    ai_engineering_check as aic,
)
from app import (
    assertions,
    claims,
    claude_datasheet,
    condition_choice,
    numparse,
    synthesis,
)
from app.claude_crs_comments import accept as crs_accept
from tests.test_claude_crs_comments import NC, row_for

MINUS, EN = "−", "–"


def _vals(sentence):
    return [(m.raw_value, m.raw_unit, m.normalized_value) for m in claims.extract_measurements(sentence)]


# ------------------------------------------------------------------ B02

@pytest.mark.parametrize("text", ["-29 C", f"{MINUS}29 C", f"{EN}29 C"])
def test_b02_every_spelling_of_a_negative_temperature_keeps_its_minus(text):
    assert _vals(f"The minimum temperature is {text}.") == [("-29", "C", -29.0)]


@pytest.mark.parametrize("text", ["10-40 C", f"10{EN}40 C", f"10 {EN} 40 C", "10 - 40 C"])
def test_b02_a_range_gives_both_ends_with_the_shared_unit(text):
    assert [(v, u) for v, u, _ in _vals(f"Operating range {text}.")] == [("10", "C"), ("40", "C")]


@pytest.mark.parametrize("text", ["ISO 8501-1 mm", "grade T-29 mm"])
def test_b02_a_dash_inside_an_identifier_is_still_no_measurement(text):
    assert _vals(f"Use {text}.") == []


# ------------------------------------------------------------------ B03

def _row(sentence, n):
    return claims.Claim(f"e{n}", f"DOC-{n}.pdf", 1, None, sentence, (), (),
                        claims.extract_measurements(sentence), frozenset({"pressure"}))


def _label(*sentences):
    return claims.label_cluster([_row(s, i) for i, s in enumerate(sentences)])[0]


def test_b03_identical_sentences_with_two_quantities_are_not_a_conflict():
    sentence = "Design pressure is 10 bar and test pressure is 15 bar."
    assert _label(sentence, sentence) == "agreement"


def test_b03_dual_unit_value_printed_in_one_row_and_once_in_the_other_is_not_a_conflict():
    assert _label("Test pressure is 1,000 psi (6.89 MPa).",
                  "Test pressure is 6.89 MPa.") == "agreement"


def test_b03_a_quantity_with_no_agreeing_partner_is_still_a_conflict():
    assert _label("Design pressure is 10 bar and test pressure is 15 bar.",
                  "Design pressure is 10 bar and test pressure is 16 bar.") == "possible_conflict"


# ------------------------------------------------------------------ B11

def test_b11_the_english_word_in_is_not_inches():
    assert _vals("Hold 5 in the vessel at 2 bar.") == [("2", "bar", pytest.approx(0.2))]
    assert _vals("Pipe wall of 5 in the line list.") == []


@pytest.mark.parametrize("text", ["5 in. thick", "a 5 in) gap", "6 in x 4 in", "length 5 in"])
def test_b11_inches_written_as_inches_still_count(text):
    assert any(u == "in" for _, u, _ in _vals(f"Use {text}."))


def test_b11_pascal_is_a_unit():
    assert _vals("Differential of 200 Pa.") == [("200", "Pa", pytest.approx(0.0002))]


# ------------------------------------------------------------------ C-H3

def test_chh3_an_invented_number_is_not_made_valid_by_erasing_a_digit_of_the_clause():
    finding = {**NC, "standard_clause": "5", "required_value": "6", "required_unit": "bar",
               "requirement_source_text": "The pressure shall not exceed 6 bar.",
               "contractor_evidence_text": "8 bar", "comparator": "<="}
    row = row_for(finding)
    comment = "SAES-D-001 Para. 5 limits it to 6 bar; typically 56 bar is seen."
    out = crs_accept({"comment": comment, "action": None}, finding, row)
    assert out["accepted"] is False and out["reason"] == "number_not_in_inputs", out
    honest = "SAES-D-001 Para. 5 limits it to 6 bar; the submittal states 8 bar."
    assert crs_accept({"comment": honest, "action": None}, finding, row)["accepted"] is True


# ------------------------------------------------------------------ H07

def test_h07_a_figure_in_another_unit_is_not_supported():
    spans = "The wall thickness is 6 mm."
    assert synthesis.first_unit_conflict("The pressure is 6 bar.", spans) == "6 bar"
    assert synthesis.first_unit_conflict("The wall is 6 mm.", spans) is None
    assert synthesis.first_unit_conflict("The wall is 6 mm.", "Wall | 6") is None   # a table cell


def test_h07_the_unit_check_is_applied_to_a_cited_sentence():
    sources = [{"text": "The wall thickness is 6 mm.", "filename": "a.pdf", "page_start": 1, "evidence_id": "e1"}]
    kept, dropped = synthesis._cite("The pressure is 6 bar [S1]. The wall is 6 mm [S1].", sources)
    assert [d[0] for d in dropped] == ["The pressure is 6 bar [S1]."]
    assert [k.text for k in kept] == ["The wall is 6 mm [S1]."]


@pytest.mark.parametrize("sentence", ["The rating is R10 [S1].", "The vessel V2 is used [S1]."])
def test_h07_r10_and_v2_are_not_treated_as_references(sentence):
    assert synthesis.claimed_numbers(sentence)


def test_h07_a_part_number_followed_by_a_unit_is_a_quantity():
    assert synthesis.claimed_numbers("Part 6 bar is the limit [S1].") == {"6.0"}
    assert synthesis.claimed_numbers("Part 6 of the standard [S1].") == set()


def test_h07_revision_shorthand_is_still_a_reference_in_a_revision_sentence():
    assert synthesis.claimed_numbers("r5 supersedes r4 [S1].") == set()


# ------------------------------------------------------------------ A09

@pytest.mark.parametrize("phrase", ["satisfies the spec", "conforms to the requirement",
                                    "is adequate", "violates the limit", "is not acceptable"])
def test_a09_a_verdict_in_other_words_is_refused(phrase):
    pages = {1: "Design pressure 23.5 barg."}
    item = {"topic": "Pressure", "page": 1, "field": "Design pressure", "value": "23.5 barg",
            "observation": f"The design pressure of 23.5 barg {phrase}.",
            "action": "Contractor to confirm.", "relates_to": None, "clause": None,
            "confidence": "medium"}
    out = aic.accept(item, pages, {}, [])
    assert out["accepted"] is False and out["reason"] == aic.Reason.PASS_FAIL_WORD.value, out


# ------------------------------------------------------------------ A10

def test_a10_a_clause_is_not_attached_to_a_standard_the_item_only_resembles():
    held = {"API 610.pdf": ["6.1"], "API 614.pdf": ["6.1"]}
    assert aic._held_clause({"relates_to": "API", "clause": "6.1"}, held) is None
    assert aic._held_clause({"relates_to": "SAES-D-00", "clause": "6.1"},
                            {"SAES-D-001.pdf": ["6.1"]}) is None
    assert aic._held_clause({"relates_to": "API 610, 11th edition", "clause": "6.1"}, held) == (
        "API 610.pdf", "6.1")


# ------------------------------------------------------------------ A14

def test_a14_required_does_not_support_not_required_and_the_reverse():
    assert assertions.unsupported("The test is not required.", "The test is required.")
    assert assertions.unsupported("The test is required.", "The test is not required.")
    assert not assertions.unsupported("The test is required.", "The test is required.")
    assert not assertions.unsupported("The test is not required.", "The test is not required.")


def test_a14_compliant_is_not_supported_by_non_compliant_and_approved_not_by_not_approved():
    assert assertions.unsupported("The design is compliant.", "The design is non-compliant.")
    assert assertions.unsupported("The design is approved.", "The design is not approved.")
    assert not assertions.unsupported("The design is non-compliant.", "The design is non-compliant.")


# ------------------------------------------------------------------ A16

def test_a16_a_thousands_comma_is_a_thousands_comma():
    assert condition_choice._number("1,500") == 1500.0
    assert condition_choice._number("9,0") == 9.0
    assert condition_choice._number("1 1/2") == 1.5


def test_a16_a_size_condition_with_a_thousands_comma_is_read_whole():
    found = condition_choice.extract("For pipe larger than 1,500 mm the wall shall be 20 mm.")
    assert found, "the size condition must be found"
    assert found[0].low == pytest.approx(1500.0 / 25.4), found    # the size condition is held in inches


# ------------------------------------------------------- parse_value 3.175

@pytest.mark.parametrize("text, value", [("3.175", 3.175), ("1.200", 1.2), ("12.345", 12.345)])
def test_three_decimals_are_decimals(text, value):
    assert numparse.parse_value(text) == value
    assert claims.parse_value(text) == value


@pytest.mark.parametrize("text", ["4.000", "12.000"])
def test_only_d_000_stays_ambiguous(text):
    assert numparse.parse_value(text) is None


def test_a_three_decimal_measurement_is_normalised():
    assert _vals("Wire diameter 3.175 mm.") == [("3.175", "mm", pytest.approx(3175.0))]


# --------------------------------------------------------------- M2 (datasheet)

PAGE = """MIN TEMPERATURE DATASHEET     Page 1 of 1
5 | Design pressure | 23.5 barg
6 | Casing material | Carbon steel
7 | Minimum temperature | -5 C
8 | Set pressure | 340 psig
Notes: the vessel is designed, built, tested and inspected to the project specification
and the contractor shall provide all documents named in the datasheet index.
"""


def _gate(**fact):
    base = {"field": "Design pressure", "value": "23.5", "unit": "barg",
            "quote": "Design pressure | 23.5 barg", "kind": "offered"}
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [{**base, **fact}]}))
    return claude_datasheet.accept(proposals, PAGE, [])


def test_m2_a_row_quote_is_accepted():
    assert len(_gate()["accepted"]) == 1


def test_m2_a_whole_page_quote_is_refused():
    out = _gate(quote=PAGE.strip())
    assert out["accepted"] == []
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.QUOTE_TOO_BROAD.value]


def test_m2_a_unit_that_is_not_in_the_quote_is_refused():
    out = _gate(unit="psig")
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.UNIT_NOT_IN_QUOTE.value]


def test_m2_one_matching_word_of_a_two_word_label_is_not_enough():
    out = _gate(field="Casing material", value="Carbon steel", unit=None,
                quote="material | Carbon steel")
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.FIELD_NOT_IN_QUOTE.value]
    ok = _gate(field="Casing material", value="Carbon steel", unit=None,
               quote="Casing material | Carbon steel")
    assert len(ok["accepted"]) == 1
