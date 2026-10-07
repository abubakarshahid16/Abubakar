"""W2 "One number parser" (issues #445 to #449): the parser's own behaviour, and
one test per caller that was switched to it.

Every test here uses INVENTED text. Each caller test is written to FAIL on the
code as it was before W2 - the PR body says how that was proved (the fix
removed again, the test run, the fix restored).
"""
# ruff: noqa: RUF001  (the Unicode minus, dashes and spaces are the point of these tests)
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import (
    ai_engineering_check as aic,
)
from app import (
    claims,
    claude_datasheet,
    claude_recheck,
    comparison,
    numparse,
    quality,
    reader_api,
    requirements_3b,
    rule_eval,
    synthesis,
)
from app.claude_crs_comments import accept as crs_accept
from tests.test_claude_crs_comments import NC, row_for

MINUS = "−"            # U+2212 MINUS SIGN
EN_DASH = "–"
SUP_MINUS, SUP_SIX = "⁻", "⁶"


# ===================================================== the parser itself (#445)

@pytest.mark.parametrize("text, expected", [
    ("-5", -5.0), (f"{MINUS}5", -5.0), ("+5", 5.0), ("2.5", 2.5),
    ("8,300", 8300.0), ("9,0", 9.0), ("1,200", 1200.0), (".5", 0.5),
    ("10^-6", 1e-6), (f"10{SUP_MINUS}{SUP_SIX}", 1e-6), ("1.5 x 10^-3", 1.5e-3),
    ("1e-6", 1e-6), ("1.5×10^3", 1500.0),
])
def test_one_number_is_read_with_its_sign_and_exponent(text, expected):
    assert numparse.as_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["5.3.2", "1,2,3", "2.5 mm", "5 10", "", "abc", None])
def test_a_text_that_is_not_one_bare_number_is_none(text):
    assert numparse.as_number(text) is None


def test_u2212_is_a_minus_sign_in_a_sentence():
    """#447. The typographic minus was dropped, so -29 was read as +29."""
    found = numparse.find_numbers(f"Minimum design temperature {MINUS}29 °C.")
    assert [n.value for n in found] == [-29.0]
    assert numparse.parse_value(f"{MINUS}29") == -29.0
    assert numparse.number_keys(f"T = {MINUS}29") == {-29.0}


@pytest.mark.parametrize("text, values", [
    ("range 29-343 °C", [29.0, 343.0]),         # a range, not a minus
    ("grade T-29", [29.0]),                          # glued to a letter
    ("ISO 8501-1", [8501.0, 1.0]),                   # an identifier
    ("tolerance +/-0.5 mm", [0.5]),                  # a tolerance, not a negative
    ("(-5)", [-5.0]),                                # a minus after a bracket
    ("min -29 °C", [-29.0]),                    # a minus after a space
    (f"min {EN_DASH}29 °C", [-29.0]),           # Word writes its minus as an en dash
    (f"5 {EN_DASH}10 mm", [5.0, 10.0]),              # a dash that may be a range: no sign
])
def test_a_dash_is_a_minus_only_where_it_can_only_be_one(text, values):
    assert [n.value for n in numparse.find_numbers(text)] == values


def test_a_token_that_is_not_one_number_is_a_compound_never_a_float():
    found = numparse.find_numbers("clause 5.3.2 and items 1,2,3")
    assert [(n.value, n.raw) for n in found] == [(None, "5.3.2"), (None, "1,2,3")]
    assert numparse.number_keys("clause 5.3.2") == {"5.3.2"}


def test_number_keys_are_signed_so_minus_five_is_not_five():
    assert numparse.number_keys("-5") != numparse.number_keys("5")
    assert numparse.number_keys(f"{MINUS}5") == numparse.number_keys("-5")


@pytest.mark.parametrize("value, text, stated", [
    ("5", "the limit is -5 degC", False),            # F01
    ("5", f"the limit is {MINUS}5 degC", False),     # F01 with U+2212
    ("5", "the gap is 2.5 mm", False),               # F02/F03
    ("5", "the gap is 25 mm", False),
    ("5", "the gap is 5 mm", True),
    ("-5", f"the limit is {MINUS}5 degC", True),     # the two minus spellings agree
    ("8300", "stress 8,300 kPa", True),              # printing, not a different number
    ("370.0", "content 370 kg/m3", True),
    ("23.55", "row 23.55", True),
    ("99.9", "row 23.55", False),
    ("5 mm", "gap -5 mm", False),                    # a figure with a unit: same rule
    ("5 mm", "gap 2.5 mm", False),
    ("5 mm", "gap 5 mm", True),
    ("316L", "tube grade 316L", True),
    ("", "anything", False),
])
def test_value_in_text_compares_whole_signed_numbers(value, text, stated):
    assert numparse.value_in_text(value, text) is stated


# ====================================================== #448: NFC plus a map

def test_a_superscript_exponent_survives_text_extraction():
    """F14. NFKC turned 10^-6 into the arithmetic "10-6"."""
    out = quality.normalise_text(f"vacuum 10{SUP_MINUS}{SUP_SIX} mbar")
    assert out == "vacuum 10^-6 mbar"
    assert numparse.find_numbers(out)[0].value == pytest.approx(1e-6)
    assert "10-6" not in out


def test_a_positive_superscript_exponent_is_not_read_as_a_longer_number():
    out = quality.normalise_text("10² Pa")          # NFKC gave "102 Pa"
    assert out == "10^2 Pa"
    assert numparse.find_numbers(out)[0].value == 100.0


def test_a_unit_power_stays_the_plain_digit_the_unit_tables_spell():
    assert quality.normalise_text("density 7850 kg/m³") == "density 7850 kg/m3"
    assert quality.normalise_text("flow 12 m³/h") == "flow 12 m3/h"


def test_the_explicit_map_keeps_what_the_pipeline_relied_on_from_nfkc():
    assert quality.normalise_text("ﬁller ﬂange ℃") == "filler flange °C"
    assert quality.normalise_text("a b c") == "a b c"
    assert quality.normalise_text(f"{MINUS}29") == "-29"
    assert quality.normalise_text("H\u2082S and CO\u2082") == "H2S and CO2"
    assert quality.normalise_text("5 \u339c") == "5 mm"


# ============================================ #446: the reader value gates

SENTENCE_MIN = "The minimum design metal temperature shall not be less than -5 degC."
SENTENCE_GAP = "The clearance shall not be less than 2.5 mm."


def _limit(sentence, value, quote, unit, subject):
    return {"kind": "limit", "operator": ">=", "value": value, "unit": unit,
            "subject": subject, "quote": quote}


def _reader_reasons(sentence, proposal):
    out = reader_api.accept([proposal], sentence)
    return [r["reason"] for r in out["rejected"]], out["accepted"]


@pytest.mark.parametrize("sentence, quote, wrong, right, unit, subject", [
    (SENTENCE_MIN, "design metal temperature shall not be less than -5 degC", "5", "-5", "degC", "design metal temperature"),
    (SENTENCE_GAP, "clearance shall not be less than 2.5 mm", "5", "2.5", "mm", "clearance"),
    (f"The minimum design metal temperature shall not be less than {MINUS}5 degC.",
     f"design metal temperature shall not be less than {MINUS}5 degC", "5", "-5", "degC", "design metal temperature"),
])
def test_the_reader_gate_refuses_5_for_a_quote_that_says_minus_5_or_2_5(
        sentence, quote, wrong, right, unit, subject):
    """#446 / audit F01-F03. 5 was 'in' "-5" and in "2.5" because the whole-word
    test treats "-" and "." as word boundaries."""
    reasons, accepted = _reader_reasons(sentence, _limit(sentence, wrong, quote, unit, subject))
    assert reasons == [reader_api.Reason.VALUE_NOT_IN_QUOTE.value], reasons
    assert accepted == []
    reasons, accepted = _reader_reasons(sentence, _limit(sentence, right, quote, unit, subject))
    assert reasons == [] and len(accepted) == 1


DATASHEET_PAGE = """MIN TEMPERATURE DATASHEET     Page 1 of 1
7 | Minimum design temperature | -5 C
8 | Clearance | 2.5 mm
9 | Cold service | −29 C
"""


@pytest.mark.parametrize("field, quote, wrong, unit", [
    ("Minimum design temperature", "Minimum design temperature | -5 C", "5", "C"),
    ("Clearance", "Clearance | 2.5 mm", "5", "mm"),
    ("Cold service", "Cold service | −29 C", "29", "C"),
])
def test_the_datasheet_reader_gate_refuses_a_value_with_the_sign_or_decimals_dropped(
        field, quote, wrong, unit):
    fact = {"field": field, "value": wrong, "unit": unit, "quote": quote, "kind": "offered"}
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [fact]}))
    out = claude_datasheet.accept(proposals, DATASHEET_PAGE, [])
    assert out["accepted"] == [], out
    assert [r["reason"] for r in out["rejected"]] == [
        claude_datasheet.Reason.VALUE_NOT_IN_QUOTE.value]


def test_the_datasheet_reader_gate_keeps_the_true_signed_value():
    fact = {"field": "Cold service", "value": "-29", "unit": "C",
            "quote": "Cold service | −29 C", "kind": "offered"}
    proposals, _ = claude_datasheet.parse_response(json.dumps({"facts": [fact]}))
    out = claude_datasheet.accept(proposals, DATASHEET_PAGE, [])
    assert len(out["accepted"]) == 1, out


def test_the_ai_check_refuses_a_value_that_is_only_inside_a_longer_number():
    pages = {1: "Minimum design temperature -5 C. Clearance 2.5 mm."}
    item = {"topic": "Temperature", "page": 1, "field": "Minimum design temperature",
            "value": "5 C", "observation": "The minimum design temperature is stated.",
            "action": "Contractor to confirm.", "relates_to": None, "clause": None,
            "confidence": "medium"}
    out = aic.accept(item, pages, {}, [])
    assert out["accepted"] is False and out["reason"] == aic.Reason.VALUE_NOT_ON_PAGE.value
    kept = aic.accept({**item, "value": "-5 C"}, pages, {}, [])
    assert kept["accepted"] is True, kept


# ============================================== #449: the other callers

def test_the_crs_comment_gate_does_not_read_u2212_as_a_positive_number():
    """The inputs say the limit is U+2212 5. A comment that says 5 states a
    different number; the old float regex read U+2212 5 as 5 and let it by."""
    finding = {**NC, "requirement_source_text":
               f"The metal temperature shall not be less than {MINUS}5 degC.",
               "contractor_evidence_text": "-10 degC", "required_value": f"{MINUS}5",
               "required_unit": "degC", "comparator": ">=", "matched_phrase": "metal temperature"}
    row = row_for(finding)
    base = "SAES-D-001 Para. 6.2.3 requires {limit} degC; the submittal states -10 degC."
    refused = crs_accept({"comment": base.format(limit="5"), "action": None}, finding, row)
    assert refused["accepted"] is False and refused["reason"] == "number_not_in_inputs", refused
    kept = crs_accept({"comment": base.format(limit="-5"), "action": None}, finding, row)
    assert kept["accepted"] is True, kept


def test_the_recheck_gate_does_not_read_u2212_as_a_positive_number():
    finding = {
        "id": "f1", "compliance_status": comparison.COMPLIANT,
        "requirement": f"The metal temperature shall not be less than {MINUS}5 degC.",
        "requirement_source_text": f"The metal temperature shall not be less than {MINUS}5 degC.",
        "standard_clause": "5.3.3", "matched_phrase": "metal temperature",
        "contractor_evidence_text": "-2 degC", "value": "-2", "unit": "degC",
        "ai_rationale": "", "unresolved_evidence": [], "confirmed_by": None,
    }
    quote = "shall not be less than"
    wrong = claude_recheck.accept({"agree": False, "quote": quote,
                                   "reason": "the limit is 5 degC"}, finding)
    assert wrong["accepted"] is None
    assert wrong["counts"] == {claude_recheck.Reason.NUMBER_NOT_IN_INPUTS.value: 1}
    right = claude_recheck.accept({"agree": False, "quote": quote,
                                   "reason": "the limit is -5 degC"}, finding)
    assert right["accepted"] is not None


def test_synthesis_does_not_let_10_stand_for_10_to_the_minus_6():
    span = f"Leak rate shall not exceed 10{SUP_MINUS}{SUP_SIX} mbar.l/s."
    supported = synthesis.span_numbers(span)
    assert synthesis.first_unsupported_value("The leak rate is 10 mbar.l/s.", supported) == "10"
    assert synthesis.first_unsupported_value("The leak rate is 10^-6 mbar.l/s.", supported) is None


def test_synthesis_reads_a_decimal_comma_and_a_thousands_comma_as_numbers():
    spans = synthesis.span_numbers("Pressure 9,0 bar and stress 8,300 kPa.")
    assert synthesis.first_unsupported_value("It is 9.0 bar and 8300 kPa.", spans) is None
    assert synthesis.first_unsupported_value("It is 90 bar.", spans) == "90"


def test_rule_numbers_must_be_stated_with_their_sign():
    rule = {"rows": [{"from": 5, "to": 10, "terms": [{"k": 1, "c": 0}]}]}
    assert rule_eval.verify_numbers(rule, "from 5 to 10 mm")
    assert not rule_eval.verify_numbers(rule, f"from {MINUS}5 to 10 mm")
    assert not rule_eval.verify_numbers(rule, "from 2.5 to 10 mm")
    negative = {"rows": [{"from": -5, "to": 10, "terms": [{"k": 1, "c": 0}]}]}
    assert rule_eval.verify_numbers(negative, f"from {MINUS}5 to 10 mm")


def test_a_table_rule_with_a_decimal_comma_is_read_as_a_decimal():
    rule = rule_eval.parse_rule("Up to 1,5 m | 2 x H", output="wall", input_names=["H"])
    assert rule is not None
    assert rule["rows"][0]["to"] == 1.5


@pytest.mark.parametrize("text", [f"{MINUS}29 mm", "-29 mm", f"{EN_DASH}29 mm"])
def test_claims_extract_a_negative_measurement_with_its_sign(text):
    """#447. "U+2212 29 mm" was extracted as +29 mm; "-29 mm" was not extracted."""
    found = claims.extract_measurements(f"The minimum is {text}.")
    assert [(m.raw_value, m.normalized_value) for m in found] == [("-29", -29000.0)]


@pytest.mark.parametrize("text", ["5-10 mm", "ISO 8501-1 mm", f"T{EN_DASH}29 mm"])
def test_claims_do_not_read_a_range_or_identifier_dash_as_a_minus(text):
    assert claims.extract_measurements(f"Use {text}.") == ()


def test_claims_keep_the_comparator_in_front_of_a_negative_value():
    found = claims.extract_measurements(f"The temperature shall not be less than {MINUS}5 bar.")
    assert (found[0].comparator, found[0].normalized_value) == (">=", pytest.approx(-0.5))


# ===================================== #203: a material-selection threshold

SELECTION = "For studs greater than 25 mm, ASTM A320 L7 material shall be used."
LIMIT = "The stud diameter shall not exceed 25 mm."


def _type(sentence):
    return requirements_3b.classify(sentence, requirements_3b.parse_limit(sentence))


def test_a_material_selection_threshold_is_a_trigger_not_a_size_limit():
    assert requirements_3b.parse_limit(SELECTION), "the fixture must parse as a limit"
    assert _type(SELECTION) == requirements_3b.APPLICABILITY_TRIGGER
    assert requirements_3b.cited_document(SELECTION) == "ASTM A320 L7"


@pytest.mark.parametrize("verb", ["specified", "installed", "selected", "applied"])
def test_the_other_selection_verbs_are_triggers_too(verb):
    sentence = f"Where the stud diameter is greater than 40 mm, UNS S31803 shall be {verb}."
    assert _type(sentence) == requirements_3b.APPLICABILITY_TRIGGER


def test_a_genuine_dimensional_limit_is_still_a_numeric_limit():
    assert _type(LIMIT) == "numeric_limit"


@pytest.mark.parametrize("sentence", [
    # a capitalised word is not a document designation
    "For pressures greater than 50 bar, ESD valves shall be used.",
    # a number after the verb is the sentence's own quantity
    "For studs greater than 25 mm, ASTM A320 L7 shall be used with a hardness of at most 22 HRC.",
])
def test_only_a_designation_with_a_digit_and_no_quantity_after_the_verb_is_a_trigger(sentence):
    assert _type(sentence) != requirements_3b.APPLICABILITY_TRIGGER


def test_a_selection_with_no_threshold_is_not_a_trigger():
    assert not requirements_3b.is_applicability_trigger(
        "ASTM A320 L7 material shall be used.")


# ================================================ #445: no second parser

APP = Path(__file__).resolve().parent.parent / "app"

#: Modules whose number reading was switched to `numparse` in W2.
SWITCHED = ("reader_api", "claude_datasheet", "ai_engineering_check", "claude_crs_comments",
            "claude_recheck", "synthesis", "answer", "rule_eval", "claims", "quality")

#: What a private number reader looks like. If one of these is defined outside
#: `numparse`, a second parser has appeared.
_PRIVATE_PARSER = re.compile(
    r"^(?:_NUMBER_TOKEN|_ANY_NUMBER|_fold_numbers)\s*="
    r"|^def (?:_fold_numbers|_normalise_number_text)\b"
    r"|unicodedata\.normalize\(\s*[\"']NFKC",
    re.MULTILINE)

#: Other readers, NOT moved by W2 (named in the PR). Each reads a different
#: shape of text; adding to this list is a decision, not a habit.
_NOT_YET_MOVED = {
    "upload.py",           # NFKC on a FILENAME (a security fold), not on document text
}

#: The files that still define a pattern NAMED `_NUMBER` or `_THOUSANDS`, and
#: what each is. None reads a value's sign or exponent.
_NAMED_PATTERNS = {
    "chat.py": "ordinal/clause shape of a question token",
    "claims.py": "the lexical shape of a number in the measurement regex; sign is numparse's",
    "corpus.py": "number WORDS for count questions",
    "keyword.py": "joins digit groups inside identifiers for the keyword index",
    "numparse.py": "the parser",
}
_NAMED = re.compile(r"^(?:_NUMBER|_THOUSANDS)\s*=", re.MULTILINE)


def test_every_switched_module_uses_numparse_and_defines_no_number_reader():
    for name in SWITCHED:
        source = (APP / f"{name}.py").read_text(encoding="utf-8")
        assert "numparse" in source, f"{name}.py does not use numparse"
        assert not _PRIVATE_PARSER.search(source), f"{name}.py defines its own number reader"


def test_no_module_outside_the_known_list_defines_a_second_number_reader():
    offenders = [p.name for p in sorted(APP.glob("*.py"))
                 if p.name != "numparse.py" and p.name not in _NOT_YET_MOVED
                 and _PRIVATE_PARSER.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"a second number parser has appeared in {offenders}"


def test_no_new_module_defines_a_number_or_thousands_pattern():
    defining = {p.name for p in sorted(APP.glob("*.py"))
                if _NAMED.search(p.read_text(encoding="utf-8"))}
    assert defining == set(_NAMED_PATTERNS), (
        f"a new _NUMBER/_THOUSANDS pattern in {sorted(defining - set(_NAMED_PATTERNS))}: "
        "read numbers with app.numparse")


def test_the_one_parser_has_no_dependency_on_the_rest_of_the_app():
    source = (APP / "numparse.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:from \.|import app)", source, re.MULTILINE)
