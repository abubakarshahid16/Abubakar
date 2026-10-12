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

@pytest.mark.parametrize("text, value", [("3.175", 3.175), ("1.500", 1.5), ("4.000", 4.0),
                                          ("12.345", 12.345)])
def test_three_decimals_are_decimals_in_a_document_with_no_decimal_comma(text, value):
    assert numparse.parse_value(text) == value
    assert claims.parse_value(text) == value


@pytest.mark.parametrize("text", ["3.175", "1.500", "4.000", "-12.345"])
def test_three_decimals_are_ambiguous_in_a_document_that_writes_a_decimal_comma(text):
    with numparse.document_context("The pressure is 9,0 bar."):
        assert numparse.parse_value(text) is None
        assert claims.parse_value(text) is None


def test_unambiguous_shapes_stay_decimals_in_a_decimal_comma_document():
    with numparse.document_context("The pressure is 9,0 bar."):
        assert numparse.parse_value("0.125") == 0.125     # EU thousands never start with 0
        assert numparse.parse_value("6.89") == 6.89
        assert numparse.parse_value("1,500") == 1500.0


@pytest.mark.parametrize("text, uses", [
    ("pressure 9,0 bar", True), ("ratio 1,5 and 2,25", True), ("value 12,3456", True),
    ("stress 8,300 kPa", False), ("items 1,2,3 are listed", False), ("plain 3.175 mm", False)])
def test_a_document_uses_a_decimal_comma_only_when_a_comma_is_a_decimal_mark(text, uses):
    assert numparse.uses_decimal_comma(text) is uses


def test_a_three_decimal_measurement_is_normalised_or_held_back_by_its_document():
    assert _vals("Wire diameter 3.175 mm.") == [("3.175", "mm", pytest.approx(3175.0))]
    with numparse.document_context(True):
        assert _vals("Wire diameter 3.175 mm.") == [("3.175", "mm", None)]


def test_claims_read_each_document_by_its_own_spelling():
    evidence = [
        {"evidence_id": "e1", "filename": "EU-001.pdf", "page_start": 1,
         "text": "Wire diameter is 3.175 mm. Pressure is 9,0 bar."},
        {"evidence_id": "e2", "filename": "US-001.pdf", "page_start": 1,
         "text": "Wire diameter is 3.175 mm."},
    ]
    found = claims.extract_claims(evidence, allowed_document_ids=frozenset())
    by_file = {c.filename: [m.normalized_value for m in c.measurements]
               for c in found if "Wire" in c.exact_span}
    assert by_file["EU-001.pdf"] == [None]
    assert by_file["US-001.pdf"] == [pytest.approx(3175.0)]


def test_a_decimal_comma_document_sends_a_three_decimal_value_to_engineer_review(monkeypatch):
    from app import comparison
    requirement = {"requirement_type": "numeric_limit", "operator": "<=", "raw_value": "3,600",
                   "raw_unit": "rpm", "value": 3600.0, "unit": "rpm", "subject": "speed",
                   "requirement_text": "<= 3,600 rpm",
                   "source_text": "Speed shall not exceed 3,600 rpm.", "field": "speed",
                   "exceptions": []}
    fact = {"id": "f1", "field_name": "speed", "field_value": "4.000 rpm", "raw_value": "4.000",
            "raw_unit": "rpm", "is_blank": 0, "page": 1, "document_id": "doc-eu"}
    monkeypatch.setattr(comparison, "_document_uses_decimal_comma", lambda _id: True)
    out = comparison.compare(requirement, fact)
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "decimal comma" in out["rationale"] and "unit" not in out["rationale"].split("decimal")[0]
    monkeypatch.setattr(comparison, "_document_uses_decimal_comma", lambda _id: False)
    assert comparison.compare(requirement, fact)["status"] == comparison.COMPLIANT


def test_the_document_flag_is_read_from_the_stored_chunks(tmp_path, monkeypatch):
    from app import comparison, db
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.init_db()
    con = db.connect()
    cols = [r["name"] for r in con.execute("PRAGMA table_info(chunks)").fetchall()]
    assert "text" in cols and "document_id" in cols
    assert comparison._document_uses_decimal_comma("no-such-document") is False


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


# ------------------------------------- owner decisions 2026-10-08: header units

TABLE_PAGE = """PRESSURE DATASHEET     Page 1 of 1
Item | Parameter | Value [barg] | Note
5 | Design pressure | 23.5 | see note 3
6 | Test pressure | 35 | hydro
Item | Parameter | Flow (m3/h)
7 | Rated flow | 125
Required flow
9,970 kg/hr
"""


def _table_gate(**fact):
    base = {"field": "Design pressure", "value": "23.5", "unit": "barg",
            "quote": "5 | Design pressure | 23.5 | see note 3", "kind": "offered"}
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [{**base, **fact}]}))
    return claude_datasheet.accept(proposals, TABLE_PAGE, [])


def test_hd1_a_unit_only_in_the_column_header_is_accepted_and_says_where_it_came_from():
    out = _table_gate()
    assert len(out["accepted"]) == 1, out
    assert out["accepted"][0]["unit_from"] == "column_header"


def test_hd1_a_unit_in_the_quote_says_quote():
    page = "Design pressure | 23.5 barg\n"
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [
        {"field": "Design pressure", "value": "23.5", "unit": "barg",
         "quote": "Design pressure | 23.5 barg", "kind": "offered"}]}))
    out = claude_datasheet.accept(proposals, page, [])
    assert out["accepted"][0]["unit_from"] == "quote"


def test_hd1_the_header_must_be_the_values_own_column():
    page = "Item | Parameter | Value | Pressure [barg]\n5 | Design pressure | 23.5 | ref\n"
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [
        {"field": "Design pressure", "value": "23.5", "unit": "barg",
         "quote": "5 | Design pressure | 23.5 | ref", "kind": "offered"}]}))
    out = claude_datasheet.accept(proposals, page, [])
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.UNIT_NOT_IN_QUOTE.value]


def test_hd1_a_unit_in_a_different_table_header_is_not_borrowed():
    out = _table_gate(unit="m3/h")
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.UNIT_NOT_IN_QUOTE.value]


def test_hd1_no_unit_in_the_quote_or_any_header_is_refused():
    out = _table_gate(unit="psig")
    assert [r["reason"] for r in out["rejected"]] == [claude_datasheet.Reason.UNIT_NOT_IN_QUOTE.value]


def test_hd1_a_one_cell_per_line_layout_uses_a_header_like_line_above():
    page = "Pressure (barg)\nDesign pressure\n23.5\n"
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [
        {"field": "Design pressure", "value": "23.5", "unit": "barg",
         "quote": "Design pressure\n23.5", "kind": "offered"}]}))
    out = claude_datasheet.accept(proposals, page, [])
    assert out["accepted"][0]["unit_from"] == "column_header"


# --------------------------------------- owner decisions 2026-10-08: "5 -10 mm"

@pytest.mark.parametrize("text", ["5 -10 mm", f"5 {EN}10 mm"])
def test_sd2_a_space_before_the_dash_only_is_one_unreadable_quantity(text):
    found = claims.extract_measurements(f"Use {text}.")
    assert [(m.raw_value, m.raw_unit, m.normalized_value) for m in found] == [
        (text.rsplit(" ", 1)[0], "mm", None)]


@pytest.mark.parametrize("text, ends", [("5-10 mm", [5000.0, 10000.0]), ("5 - 10 mm", [5000.0, 10000.0]),
                                        ("5 – 10 mm", [5000.0, 10000.0])])
def test_sd2_a_dash_with_no_space_or_spaces_both_sides_is_still_a_range(text, ends):
    assert [m.normalized_value for m in claims.extract_measurements(f"Use {text}.")] == ends


def test_sd2_a_negative_after_a_word_is_still_a_negative():
    assert _vals("Minimum -10 mm.") == [("-10", "mm", -10000.0)]


def test_sd2_the_ambiguous_value_goes_to_engineer_review_not_a_verdict():
    from app import comparison
    requirement = {"requirement_type": "numeric_limit", "operator": "<=", "raw_value": "20",
                   "raw_unit": "mm", "value": 20.0, "unit": "mm", "subject": "gap",
                   "requirement_text": "<= 20 mm", "source_text": "The gap shall not exceed 20 mm.",
                   "field": "gap", "exceptions": []}
    fact = {"id": "f1", "field_name": "gap", "field_value": "5 -10 mm", "raw_value": "5 -10",
            "raw_unit": "mm", "is_blank": 0, "page": 1}
    out = comparison.compare(requirement, fact)
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW


# ------------------------------------- CI regression: a quote may span cell lines

def test_m2_a_quote_that_spans_two_one_cell_per_line_rows_is_not_too_broad():
    """The production bench sheet prints each label and each value on its own
    line, so one row is two lines and a quote from one label to the next row's
    value is four. A line limit refused it; only a whole-page quote is too
    broad. (This is the reading the bench expects to be kept and flagged.)"""
    page = ("CENTRIFUGAL PUMP DATASHEET\nDoc No.: DS-0001-P\nTag No.: SYN-P-0001\nRev: 0\n"
            "Project: Synthetic Plant 0001\nRated capacity\n125 m3/h\nDifferential head\n85 m\n"
            "Suction pressure\n1.5 barg\nDischarge pressure\n9.8 barg\nPumping temperature\n45 C\n"
            "Speed\n2950 rpm\nDriver power\n55 kW\n")
    quote = "Rated capacity\n125 m3/h\nDifferential head\n85 m"
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [
        {"field": "Rated capacity", "value": "85", "unit": "m", "quote": quote, "kind": "offered"}]}))
    out = claude_datasheet.accept(proposals, page, [])
    assert [r["reason"] for r in out["rejected"]] == []
    assert len(out["accepted"]) == 1
