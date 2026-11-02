"""#1618: a unit whose case is its meaning keeps its case.

mPa is a millipascal and MPa a megapascal, a factor of 10^9. Folding case read
one as the other. All values here are invented.
"""

from __future__ import annotations

import json

import pytest

from app import (
    ai_requirements,
    answerability,
    applicability_v2,
    claims,
    claude_datasheet,
    comparison,
    compiled_rule_context,
    compiled_rule_proof,
    condition_choice,
    conditions,
    converter_gates,
    datasheet_ai,
    datasheet_checks,
    datasheets,
    db,
    dual_unit_form,
    field_copies,
    form_reader,
    form_reader_fields,
    label_match,
    numparse,
    reader_api,
    requirements_3b,
    rule_eval,
    same_value,
    standards_converter,
    submittal_review,
    unit_case,
)
from app.config import settings


def _value(number: str, unit: str) -> float | None:
    return claims.normalise(number, unit).normalized_value


# ------------------------------------------------------------- the reading


@pytest.mark.parametrize(
    "unit,expected",
    [
        ("MPa", 5.0),
        ("MPA", 5.0),
        ("Mpa", 5.0),
        ("mpa", 5.0),
        ("kPa", 0.005),
        ("KPA", 0.005),
    ],
)
def test_megapascal_and_kilopascal_stay_case_free(unit, expected):
    assert _value("5", unit) == pytest.approx(expected)
    assert claims.normalise("5", unit).normalized_unit == "MPa"


def test_millipascal_is_never_read_as_megapascal():
    measured = claims.normalise("5", "mPa")
    assert measured.normalized_value is None
    assert claims.unit_dimension("mPa") == "pressure"
    assert claims.is_unit("mPa")


def test_millipascal_has_no_strict_conversion():
    with pytest.raises(claims.UnknownUnit):
        claims.normalise_strict("5", "mPa")


@pytest.mark.parametrize("unit", ["mPag", "mPaa", "mPa(g)", "mPa (a)"])
def test_millipascal_with_a_reference_is_not_read_as_megapascal(unit):
    assert claims.normalise("5", unit).normalized_value is None
    assert claims.unit_dimension(unit) == "pressure"
    assert claims.split_reference(unit)[0] == "mPa"


@pytest.mark.parametrize("unit", ["MPag", "mpag", "MPa(g)"])
def test_megapascal_with_a_reference_still_converts(unit):
    assert _value("5", unit) == pytest.approx(5.0)
    assert claims.split_reference(unit)[1] == "gauge"


def test_a_millipascal_value_gets_no_verdict_against_a_megapascal_limit():
    observed = claims.normalise("5", "mPa")
    limit = claims.normalise("10", "MPa", "max")
    assert not claims.same_unit(observed, limit)
    assert claims._compatible(observed, limit) is None
    assert claims.compare_across_units(observed, limit) is None


def test_two_millipascal_values_still_compare_as_written():
    assert (
        claims._compatible(claims.normalise("5", "mPa"), claims.normalise("5", "mPa"))
        is True
    )


# -------------------------------------------------------- the same on a text


@pytest.mark.parametrize(
    "text", ["viscosity 5 mPa.s at 20 C", "viscosity 5 mPa·s", "viscosity 5 mPa-s"]
)
def test_viscosity_in_a_sentence_is_not_a_pressure(text):
    read = claims.extract_measurements(text)
    assert read[0].normalized_value is None
    assert claims.unit_dimension(read[0].raw_unit) == "viscosity"


@pytest.mark.parametrize("text", ["viscosity 5 MPa.s", "viscosity 5 MPa·s"])
def test_megapascal_second_in_a_sentence_is_not_a_pressure(text):
    assert not [
        m for m in claims.extract_measurements(text) if m.normalized_unit == "MPa"
    ]


@pytest.mark.parametrize("text", ["viscosity 5 Pa.s", "viscosity 5 Pa·s"])
def test_pascal_second_in_a_sentence_is_not_a_pressure(text):
    read = claims.extract_measurements(text)
    assert [claims.unit_dimension(m.raw_unit) for m in read] == ["viscosity"]
    assert read[0].normalized_value is None


@pytest.mark.parametrize(
    "text", ["The pressure is 5 MPa.", "Rated 5 MPa. Second test."]
)
def test_a_full_stop_after_a_pressure_is_not_a_viscosity(text):
    read = claims.extract_measurements(text)
    assert read[0].normalized_value == pytest.approx(5.0)


def test_a_millipascal_in_a_sentence_keeps_its_case():
    read = claims.extract_measurements("Rated 5 mPa only.")
    assert read[0].raw_unit == "mPa"
    assert read[0].normalized_value is None


# ------------------------------------------------- every other case collision


@pytest.mark.parametrize(
    "kept,owner",
    [
        ("mW", "MW"),
        ("mJ", "MJ"),
        ("mS", "ms"),
        ("MA", "mA"),
        ("MV", "mV"),
        ("Mg", "mg"),
        ("ML", "mL"),
        ("mPa", "MPa"),
    ],
)
def test_a_case_collision_is_two_units(kept, owner):
    assert claims._fold_unit(kept) != claims._fold_unit(owner)
    assert claims.is_unit(kept) and claims.is_unit(owner)
    assert not claims.same_unit(
        claims.normalise("5", kept), claims.normalise("5", owner)
    )


def test_every_unit_in_the_tables_keeps_its_case():
    from_tables = set(unit_case.UNCONVERTED) | set(unit_case.REFERENCE_SUFFIX)
    assert from_tables - {"pa·s", "pa.s", "pa-s"} <= numparse.CASE_KEPT_UNITS


def test_mega_ampere_is_not_read_as_milliampere():
    assert _value("5", "mA") == pytest.approx(0.005)
    assert _value("5", "ma") == pytest.approx(0.005)
    assert _value("5", "MA") is None
    assert claims.unit_dimension("MA") == "current"


def test_siemens_is_not_a_time():
    assert claims.unit_dimension("ms") == "time"
    assert claims.unit_dimension("mS") is None


def test_megalitre_rate_is_not_read_as_millilitre_rate():
    assert _value("5", "ml/d") is not None
    assert _value("5", "mL/d") == _value("5", "ml/d")
    assert _value("5", "ML/d") is None
    assert claims.is_unit("ML/d")


@pytest.mark.parametrize("unit", ["mW/m2", "mW/m²", "mWh/d", "Mg/m3", "ML/d", "mJ/kg"])
def test_a_rate_keeps_its_case_and_stays_a_unit(unit):
    folded = claims._fold_unit(unit)
    assert folded != folded.lower()
    assert claims.is_rate_unit(unit)


def test_the_denominator_of_a_kept_rate_still_folds():
    assert claims._fold_unit("mW/M2") == claims._fold_unit("mW/m2") == "mW/m2"


@pytest.mark.parametrize(
    "a,b",
    [
        ("MM", "mm"),
        ("mL", "ml"),
        ("BAR", "bar"),
        ("PSI", "psi"),
        ("KG/CM2", "kg/cm2"),
        ("kV", "KV"),
        ("Deg C", "degc"),
        ("M", "m"),
        ("wt %", "wt%"),
        ("dB(A)", "dba"),
        ("MW", "mw"),
        ("MJ", "mj"),
    ],
)
def test_no_clash_stays_case_free(a, b):
    assert claims._fold_unit(a) == claims._fold_unit(b)


# ------------------------------------------------------------ the other homes


@pytest.mark.parametrize(
    "value,text,stated",
    [
        ("10 MPa", "rated 10 MPa", True),
        ("10 MPa", "RATED 10 MPA", True),
        ("10 MPa", "rated 10 mPa", False),
        ("10 mPa", "rated 10 MPa", False),
        ("10 mPa", "rated 10 mPa", True),
        ("10 MPa", "at 5 mPa and 10 MPa", True),
        ("5 mW", "rated 5 MW", False),
        ("316L", "grade 316l", True),
        ("MPa", "rated at mPa", False),
        ("mPa", "rated at mPa", True),
    ],
)
def test_a_quote_does_not_prove_the_other_unit(value, text, stated):
    assert numparse.value_in_text(value, text) is stated


@pytest.mark.parametrize(
    "unit,expected",
    [
        (None, ""),
        ("  MPa ", "mpa"),
        ("kg / cm2", "kg / cm2"),
        ("mPa", "mPa"),
        (" m Pa", "mPa"),
        ("M Pa", "m pa"),
        ("mW / M2", "mW/m2"),
    ],
)
def test_fold_unit(unit, expected):
    assert unit_case.fold_unit(unit) == expected


@pytest.mark.parametrize(
    "unit,quote,printed",
    [
        ("MPa", "rated 10 MPa", True),
        ("MPa", "RATED 10 MPA", True),
        ("MPa", "rated 10MPa", True),
        ("MPa", "rated 10 mPa", False),
        ("mPa", "rated 10 MPa", False),
        ("mPa", "rated 10 mPa", True),
        ("kW", "rated 75kW", True),
        ("m3/h", "rated 5 Nm3/h", False),
    ],
)
def test_a_quote_does_not_print_the_other_unit(unit, quote, printed):
    assert datasheet_ai.unit_in_quote(unit, quote) is printed


def test_a_calculation_does_not_convert_millipascal():
    table = {"mpa": 1000.0, "kpa": 1.0}
    fact = {"raw_value": "5", "raw_unit": "mPa", "field_name": "pressure"}
    rules = {"calc_units": {"pressure_kpa": table}}
    with pytest.raises(datasheet_checks._NotCalculated):
        datasheet_checks._converted(fact, "pressure", "pressure_kpa", rules)
    fact["raw_unit"] = "MPa"
    assert (
        datasheet_checks._converted(fact, "pressure", "pressure_kpa", rules) == 5000.0
    )


def test_a_reference_on_millipascal_is_kept_in_a_calculation():
    assert datasheet_checks._printed_unit({"raw_unit": "mPa(g)"}) == ("mPa", "gauge")
    assert datasheet_checks._printed_unit({"raw_unit": "MPa(g)"}) == ("mpa", "gauge")


def test_condition_reader_does_not_convert_millipascal():
    assert condition_choice._quantity("pressure", "5 MPa") == pytest.approx(
        (725.19, "p")
    )
    assert condition_choice._quantity("pressure", "5 mPa") is None


def test_applicability_does_not_convert_millipascal():
    assert applicability_v2._in_base(5.0, "MPa", "pressure") == 5.0
    assert applicability_v2._in_base(5.0, "mPa", "pressure") is None


def test_two_copies_in_a_colliding_unit_are_not_one_value():
    def fact(unit):
        return {"raw_value": "5", "raw_unit": unit}

    assert rule_eval.same_value_key(fact("mW")) != rule_eval.same_value_key(fact("MW"))
    assert rule_eval.same_value_key(fact("dB")) == rule_eval.same_value_key(fact("DB"))
    assert field_copies._value_signature(fact("mW")) != field_copies._value_signature(
        fact("MW")
    )
    assert field_copies._value_signature(fact("dB")) == field_copies._value_signature(
        fact("DB")
    )


def test_two_ranges_in_a_colliding_unit_are_not_one_value():
    def fact(unit):
        return {
            "value_min": 4.0,
            "value_max": 8.0,
            "raw_unit": unit,
            "field_value": f"4-8 {unit}",
        }

    assert same_value._range_key(fact("mW")) != same_value._range_key(fact("MW"))
    assert same_value._range_key(fact("cP")) == same_value._range_key(fact("CP"))


def test_a_table_mixing_the_two_units_is_refused():
    def table(first, second):
        text = f"up to 5 {first} | 1\nover 5 {first} to 9 {second} | 2\n"
        return rule_eval.parse_rule(
            text.replace("| 1", "| 1 x mop").replace("| 2", "| 2 x mop"),
            output="x",
            input_names=["mop"],
        )

    assert table("MPa", "MPA") is not None
    assert table("mPa", "MPa") is None


def test_a_unit_less_twin_is_not_joined_across_a_collision():
    readings = [
        {"raw_value": "5", "raw_unit": "mW", "field_value": "5 mW"},
        {"raw_value": "5", "raw_unit": "MW", "field_value": "5 MW"},
        {"raw_value": "5", "raw_unit": "", "field_value": "5"},
    ]
    assert len(label_match.drop_unit_less_twins(readings)) == 3
    readings[1]["raw_unit"] = "mw"
    readings[0]["raw_unit"] = "MW"
    assert len(label_match.drop_unit_less_twins(readings)) == 2


def test_a_dual_unit_cell_in_two_case_spellings_is_two_units():
    assert dual_unit_form._fold("mPa") != dual_unit_form._fold("MPa")
    assert dual_unit_form._fold("KPA") == dual_unit_form._fold("kPa")


def test_a_passage_conflict_keeps_the_two_units_apart():
    found = answerability._quantities("rated 5 mPa and rated 7 MPa")
    assert found.get("mPa") == {"5"} and found.get("mpa") == {"7"}


# ------------------------------------------------- through the real gates

PRESSURE = "design pressure"
TRUE_READINGS = ["10 mPa", "5 mPa.s", "2 mW", "4-20 MA", "10 MPa", "10 MPA", "20 mA"]


def _accept(value, quote, page=None, unit=None):
    proposal = {"field": PRESSURE, "value": value, "kind": "offered", "quote": quote}
    if unit:
        proposal["unit"] = unit
    done = claude_datasheet.accept([proposal], page or f"{quote}\n")
    return [r["reason"] for r in done["rejected"]]


def _form(value, quote, page=None, unit=""):
    field = form_reader_fields.Field("design_pressure", PRESSURE, None, ())
    item = {"value": value, "unit": unit, "quote": quote, "status": "found"}
    rules = datasheet_checks.load_rules()
    return form_reader.verify(field, item, page or f"{quote}\n", rules)


def _api(value, quote, sentence=None):
    proposal = {"kind": "statement", "value": value, "quote": quote}
    done = reader_api.accept([proposal], sentence or quote)
    return [r["reason"] for r in done["rejected"]]


@pytest.mark.parametrize("value", TRUE_READINGS)
def test_a_true_reading_passes_every_gate(value):
    quote = f"{PRESSURE} {value}"
    assert _accept(value, quote) == []
    assert _form(value, quote) is None
    assert _api(value, quote) == []


def _read(value, quote, page=None, unit=None):
    """What `claude_datasheet.accept` keeps of one reading."""
    proposal = {"field": PRESSURE, "value": value, "kind": "offered", "quote": quote}
    if unit:
        proposal["unit"] = unit
    done = claude_datasheet.accept([proposal], page or f"{quote}\n")
    assert done["rejected"] == []
    return done["accepted"][0]


@pytest.mark.parametrize(
    "value,printed",
    [("10 MPa", "10 mPa"), ("10 mPa", "10 MPa"), ("5 mW", "5 MW"), ("20 mA", "20 MA")],
)
def test_a_value_is_not_proved_by_the_other_unit(value, printed):
    quote = f"{PRESSURE} {printed}"
    assert _form(value, quote) is form_reader.Reason.VALUE_NOT_IN_QUOTE
    assert _api(value, quote) == [reader_api.Reason.VALUE_NOT_IN_QUOTE.value]


@pytest.mark.parametrize(
    "value,printed",
    [("10 MPa", "10 mPa"), ("10 mPa", "10 MPa"), ("5 mW", "5 MW"), ("20 mA", "20 MA")],
)
def test_a_retyped_value_takes_the_spelling_the_page_prints(value, printed):
    read = _read(value, f"{PRESSURE} {value}", f"{PRESSURE} {printed}\n")
    assert read["value"] == printed and read["quote"] == f"{PRESSURE} {printed}"
    assert _read(value, f"{PRESSURE} {printed}")["value"] == printed


def test_a_quote_retyped_in_the_other_case_stays_refused_for_a_rule():
    quote, page = f"{PRESSURE} 10 MPa", f"{PRESSURE} 10 mPa\n"
    assert _form("10 MPa", quote, page) is form_reader.Reason.QUOTE_NOT_ON_PAGE
    assert _api("10 MPa", quote, page) == [
        reader_api.Reason.QUOTE_NOT_IN_SENTENCE.value
    ]


def test_a_quote_not_on_the_page_stays_refused_whatever_its_case():
    assert _accept("10 MPa", f"{PRESSURE} 10 MPa", f"{PRESSURE} 12 mPa\n") == [
        claude_datasheet.Reason.QUOTE_NOT_ON_PAGE.value
    ]


def test_a_quote_on_the_page_in_its_own_case_keeps_it():
    page = f"{PRESSURE} 10 mPa\n{PRESSURE} 10 MPa\n"
    assert _read("10 MPa", f"{PRESSURE} 10 MPa", page)["value"] == "10 MPa"
    assert _read("10 mPa", f"{PRESSURE} 10 mPa", page)["value"] == "10 mPa"


def test_a_unit_is_not_proved_by_the_other_unit():
    quote = f"{PRESSURE} 10 mPa"
    assert _form("10", quote, unit="MPa") is form_reader.Reason.UNIT_NOT_IN_QUOTE
    assert _form("10", quote, unit="mPa") is None
    assert _read("10", quote, unit="MPa")["unit"] == "mPa"
    assert _read("10", quote, unit="mPa")["unit"] == "mPa"


def test_a_column_header_gives_the_printed_unit():
    page = f"Item | mPa\n{PRESSURE} | 10\n"
    quote = f"{PRESSURE} | 10"
    assert _read("10", quote, page, unit="MPa")["unit"] == "mPa"
    assert _read("10", quote, page, unit="mPa")["unit"] == "mPa"


@pytest.mark.parametrize(
    "text,printed,expected",
    [
        ("20 mA", "SIGNAL 20 MA", "20 MA"),
        ("20 MA", "signal 20 mA", "20 mA"),
        ("5 MPA", "rated 5 MPa", "5 MPA"),
        ("5 mm", "RATED 5 MM", "5 mm"),
        ("5 MPa", "at 5 mPa and 5 MPa", "5 MPa"),
        ("5 mPa", "at 5 mPa and 5 MPa", "5 mPa"),
    ],
)
def test_as_printed(text, printed, expected):
    assert numparse.as_printed(text, printed) == expected


def _requirement(value, unit, sentence, quote=None):
    proposal = {
        "has_limit": True,
        "field": PRESSURE,
        "operator": "<=",
        "value": value,
        "unit": unit,
        "quote": quote or sentence,
    }
    return ai_requirements.verify_proposal(proposal, sentence)


def test_ai_requirements_tells_the_two_units_apart():
    said = f"The {PRESSURE} shall not exceed 10 mPa."
    assert _requirement("10", "MPa", said)[1] == ai_requirements.UNIT_NOT_IN_QUOTE
    assert _requirement("10 MPa", None, said)[1] == ai_requirements.VALUE_NOT_IN_QUOTE
    retyped = f"The {PRESSURE} shall not exceed 10 MPa."
    assert (
        _requirement("10", "MPa", said, retyped)[1]
        == ai_requirements.QUOTE_NOT_IN_SOURCE
    )
    check, why = _requirement("10", "mPa", said)
    assert why is None and check["unit"] == "mPa"
    check, why = _requirement("10", "MPa", retyped)
    assert why is None and check["unit"] == "mpa"


def test_the_figure_reader_does_not_read_a_viscosity_as_a_pressure():
    read = ai_requirements.read_figures("viscosity shall not exceed 5 MPa.s")
    assert not [f for f in read if f["unit"] == "mpa"]


def test_the_converter_unit_gate_tells_the_two_units_apart():
    assert not standards_converter._has_unit("shall not exceed 10 mPa", "MPa")
    assert not standards_converter._has_unit("shall not exceed 10 MPa", "mPa")
    assert standards_converter._has_unit("shall not exceed 10 mPa", "mPa")
    assert standards_converter._has_unit("shall not exceed 10 MPA", "MPa")


def _converter(unit, sentence):
    names = [PRESSURE]
    answer = {
        "condition": None,
        "field": 0,
        "comparator": "<=",
        "limit": "10",
        "unit": unit,
        "quote": f"{PRESSURE} shall not exceed 10 {sentence}",
    }
    row = {
        "requirement_text": f"The casing {answer['quote']}.",
        "clause": "6.1",
        "requirement_type": "statement",
    }
    return standards_converter.verify(
        answer, row, names, {PRESSURE: "design_pressure"}, {PRESSURE: ("pressure",)}
    )


def test_the_converter_verifies_only_the_printed_unit():
    assert _converter("MPa", "mPa")[:2] == ("unproven", "unit_not_in_quote")
    assert _converter("mPa", "mPa")[0] == "verified"
    assert _converter("MPa", "MPa")[0] == "verified"


def test_a_compiled_rule_quote_is_not_placed_on_the_other_unit():
    page = "Rated 10 mPa here. Rated 10 MPa there."
    assert compiled_rule_context.quote_span("Rated 10 MPa", page) == (19, 31)
    assert compiled_rule_context.quote_span("rated 10 mPa", page) == (0, 12)
    assert compiled_rule_context.quote_span("Rated 7 MPa", page) == (None, None)


# ------------------------------------------------- the spellings around mPa


@pytest.mark.parametrize("unit", ["mPA", "mPaG", "mPaA"])
def test_a_lower_case_m_on_a_pascal_is_never_mega(unit):
    assert _value("5", unit) is None
    assert claims.unit_dimension(unit) == "pressure"


@pytest.mark.parametrize(
    "text,dimension",
    [
        ("viscosity 5 mPa s at 20 C", "viscosity"),
        ("viscosity 5 Pa s at 20 C", "viscosity"),
    ],
)
def test_a_pascal_second_with_a_space_is_a_viscosity(text, dimension):
    read = claims.extract_measurements(text)
    assert claims.unit_dimension(read[0].raw_unit) == dimension
    assert read[0].normalized_value is None


def test_a_megapascal_second_with_a_space_is_not_a_pressure():
    assert not [
        m
        for m in claims.extract_measurements("viscosity 5 MPa s")
        if m.normalized_unit == "MPa"
    ]


def test_a_word_after_a_pressure_is_not_a_second():
    read = claims.extract_measurements("rated 5 MPa steady")
    assert read[0].normalized_value == pytest.approx(5.0)


# ------------------------------------------------- the known cost, pinned


@pytest.mark.parametrize("unit", ["MA", "ML/MIN", "MV"])
def test_a_capitals_sheet_loses_the_number_and_goes_to_review(unit):
    """A bare capital unit cannot say whether its sheet is all capitals, and on a
    capitals sheet the case says nothing either way: no number, no verdict."""
    assert _value("20", unit) is None


@pytest.mark.parametrize("unit,expected", [("MPA", 5.0), ("BAR", 0.5), ("KPA", 0.005)])
def test_a_capitals_sheet_still_reads_a_unit_with_no_clash(unit, expected):
    assert _value("5", unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    "said", ["5 MPa s", "5 MPa.s", "5 MPa·s", "5 Pa s", "5 Pa.s", "5 mPa s", "5 mPa.s"]
)
def test_a_stated_limit_in_a_viscosity_unit_is_not_a_pressure(said):
    read = requirements_3b.parse_limit(f"The viscosity shall not exceed {said}.")
    assert read["unit"] != "MPa" and read["value"] is None


def test_a_stated_limit_in_a_pressure_stays_a_pressure():
    read = requirements_3b.parse_limit("The pressure shall not exceed 5 MPa.")
    assert read["unit"] == "MPa" and read["value"] == pytest.approx(5.0)
    assert (
        requirements_3b.parse_limit("The level shall not exceed 5 mm.")["raw_unit"]
        == "mm"
    )


@pytest.mark.parametrize(
    "cell", ["5 MPa s", "5 Pa s", "5 MPa.s", "5 Pa.s", "5 mPa.s", "5 mPa s"]
)
def test_a_datasheet_cell_in_a_viscosity_unit_is_not_a_pressure(cell):
    _value_read, _unit_read, measured = datasheets.measure_value(cell)
    assert measured is None or measured.normalized_value is None


@pytest.mark.parametrize("low,high,same", [("mPa", "MPa", False), ("MPa", "MPA", True)])
def test_a_range_in_the_two_units_is_not_one_range(low, high, same):
    read = requirements_3b.parse_range(
        f"The pressure shall be between 5 {low} and 10 {high}."
    )
    assert (read is not None) is same


# ------------------------------------------------- the condition reader


def _condition(text, value, unit):
    fact = {
        "field_name": "design pressure",
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": 7.0,
        "extraction_method": "geometry",
        "page": 1,
    }
    return conditions._evaluate_numeric(text, [fact])


def test_a_condition_in_millipascal_is_not_read_as_megapascal():
    held = _condition("design pressure greater than 5 mPa", "7", "MPa")
    assert held["state"] == conditions.UNKNOWN
    assert "not in the unit table" in held["reason"]


def test_a_condition_in_megapascal_still_decides():
    assert (
        _condition("design pressure greater than 5 MPA", "7", "MPa")["state"]
        == conditions.SATISFIED
    )
    assert (
        _condition("design pressure GREATER THAN 5 MPa", "7", "MPa")["state"]
        == conditions.SATISFIED
    )


# ---------------------------------------- a sheet that prints it goes to review


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "case.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _stored(accepted, page_text):
    """Store accepted readings the way a real run does, and read them back."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('d1','sheet.pdf','sha',1,'sheet.pdf','ready',1,'2026-09-18T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
            "text,token_count,content_hash,retrievable)"
            " VALUES ('c1','d1','sheet.pdf',1,1,1,NULL,'prose',?,1,'h1',1)",
            (page_text,),
        )
    stored = claude_datasheet.store_facts(
        None,
        "d1",
        [{**p, "page": 1} for p in accepted],
        allowed_document_ids=frozenset({"d1"}),
    )
    assert stored["refused"] == []
    return stored["facts"]


REQUIREMENT = {
    "id": "r",
    "requirement_type": "numeric_limit",
    "operator": "<=",
    "raw_value": "20",
    "raw_unit": "mA",
    "value": 0.02,
    "unit": "A",
    "normalized_value": 0.02,
    "normalized_unit": "A",
    "subject": "signal",
    "requirement_text": "signal at most 20 mA",
    "exact_span": "signal at most 20 mA",
}


def test_a_retyped_capital_unit_goes_to_review_and_never_reads_as_missing(temp_db):
    page = "SIGNAL RANGE 20 MA\n"
    proposal = {
        "field": "signal range",
        "value": "20 mA",
        "kind": "offered",
        "quote": "SIGNAL RANGE 20 mA",
    }
    done = claude_datasheet.accept([proposal], page)
    assert done["rejected"] == []
    fact = _stored(done["accepted"], page)[0]
    verdict = comparison.compare(REQUIREMENT, fact)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "Capitals carry no case" in verdict["rationale"]
    assert "not mentioned" not in verdict["rationale"].lower()
    assert (
        comparison.compare(REQUIREMENT, None)["status"]
        == comparison.MISSING_INFORMATION
    )


def test_a_retyped_mega_value_on_a_millipascal_page_goes_to_review(temp_db):
    page = "DESIGN PRESSURE 10 mPa\n"
    proposal = {
        "field": PRESSURE,
        "value": "10 MPa",
        "kind": "offered",
        "quote": "DESIGN PRESSURE 10 MPa",
    }
    done = claude_datasheet.accept([proposal], page)
    fact = _stored(done["accepted"], page)[0]
    limit = {
        **REQUIREMENT,
        "raw_unit": "MPa",
        "unit": "MPa",
        "value": 20.0,
        "normalized_unit": "MPa",
        "normalized_value": 20.0,
        "subject": PRESSURE,
    }
    assert comparison.compare(limit, fact)["status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_the_form_reader_gives_the_printed_spelling():
    answer = {
        "field_key": "design_pressure",
        "value": "10",
        "unit": "MPa",
        "quote": "Design pressure: 10 MPa",
        "status": "found",
    }

    def model(_prompt):
        return json.dumps({"fields": [answer]})

    reading = form_reader.read_form(
        {1: "Design pressure: 10 mPa\n"}, "Centrifugal Pump", model
    )
    fact = next(f for f in reading.facts if f["field_key"] == "design_pressure")
    assert (fact["value"], fact["unit"], fact["quote"]) == (
        "10",
        "mPa",
        "Design pressure: 10 mPa",
    )


def test_the_capitals_reason_names_only_a_capital_case_kept_unit():
    assert "Capitals carry no case" in unit_case.capitals_note("MA")
    assert "Capitals carry no case" in unit_case.capitals_note("ML/MIN")
    assert unit_case.capitals_note("MPA") == ""
    assert unit_case.capitals_note("mPa") == ""
    assert unit_case.capitals_note(None) == ""


# ------------------------------------------------- the mark is never kept


@pytest.mark.parametrize("word", ["MV", "MA", "Mg", "ML", "mPa"])
def test_the_private_mark_reaches_no_stored_or_shown_field(temp_db, word):
    mark = numparse.CASE_KEPT_MARK
    limit = "10"
    condition = f"at {word} level"
    sentence = f"When {condition}, the {PRESSURE} shall not exceed {limit} bar."
    quote = f"{PRESSURE} shall not exceed {limit} bar"
    row = {
        "requirement_text": sentence,
        "clause": "6.1",
        "requirement_type": "statement",
    }
    answer = {
        "condition": condition,
        "field": 0,
        "comparator": "<=",
        "limit": limit,
        "unit": "bar",
        "quote": quote,
    }
    status, why, check = standards_converter.verify(
        answer,
        row,
        [PRESSURE],
        {PRESSURE: "design_pressure"},
        {PRESSURE: ("pressure",)},
    )
    assert status == "verified", why
    assert mark not in repr(check)
    assert mark not in standards_converter._fold(condition)

    kept = compiled_rule_proof._kept_rule(
        {"clause": "6.1", "page": 1},
        {
            "quote": quote,
            "limit": limit,
            "unit": "bar",
            "applies_to": "pump",
            "condition": condition,
            "exception": condition,
            "name": PRESSURE,
            "comparator": "<=",
        },
        [],
        "shall",
        sentence,
    )
    assert kept["condition_text"] == condition
    assert mark not in json.dumps(kept, ensure_ascii=False)

    said = f"The {PRESSURE} at {word} level shall not exceed 10 bar."
    checked, _why = ai_requirements.verify_proposal(
        {
            "has_limit": True,
            "field": PRESSURE,
            "operator": "<=",
            "value": "10",
            "unit": "bar",
            "quote": said,
            "condition": None,
        },
        said,
    )
    assert mark not in repr(checked)
    done = reader_api.accept(
        [{"kind": "statement", "value": "10", "quote": said, "subject": PRESSURE}], said
    )
    assert mark not in repr(done)

    page = f"{PRESSURE} 5 {word} at {word} level\n"
    read = claude_datasheet.accept(
        [
            {
                "field": PRESSURE,
                "value": f"5 {word}",
                "kind": "offered",
                "quote": page.strip(),
            }
        ],
        page,
    )
    assert mark not in repr(read)
    _stored(read["accepted"], page)
    with db.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            for line in conn.execute(f'SELECT * FROM "{table}"').fetchall():
                assert mark not in repr(tuple(line)), table


def test_a_calculation_says_why_a_capital_unit_got_no_number():
    rules = {"calc_units": {"pressure_kpa": {"kpa": 1.0}}}
    fact = {"raw_value": "5", "raw_unit": "MA", "field_name": "pressure"}
    with pytest.raises(datasheet_checks._NotCalculated, match="Capitals carry no case"):
        datasheet_checks._converted(fact, "pressure", "pressure_kpa", rules)


def test_the_converter_refuses_a_quote_retyped_in_the_other_case():
    answer = {
        "condition": None,
        "field": 0,
        "comparator": "<=",
        "limit": "10",
        "unit": "MPa",
        "quote": f"{PRESSURE} shall not exceed 10 MPa",
    }
    row = {
        "requirement_text": f"The casing {PRESSURE} shall not exceed 10 mPa.",
        "clause": "6.1",
        "requirement_type": "statement",
    }
    status, _why, check = standards_converter.verify(
        answer,
        row,
        [PRESSURE],
        {PRESSURE: "design_pressure"},
        {PRESSURE: ("pressure",)},
    )
    assert status == "unproven" and check is None


# ---------------------------------------------- a stored condition is read again


FACT_7_MPA = {
    "field_name": "design pressure",
    "field_value": "7 MPa",
    "raw_value": "7",
    "raw_unit": "MPa",
    "normalized_value": 7.0,
    "extraction_method": "geometry",
    "page": 1,
}


def _evaluated(condition):
    requirement = {"requirement_type": conditions.GATED_TYPE, "condition": condition}
    return conditions.evaluate(requirement, [FACT_7_MPA])["state"]


def test_a_stored_converter_condition_in_megapascal_still_decides():
    answer_case = standards_converter.verify(
        {
            "condition": "design pressure greater than 5 MPa",
            "field": 0,
            "comparator": "<=",
            "limit": "10",
            "unit": "bar",
            "quote": f"{PRESSURE} shall not exceed 10 bar",
        },
        {
            "requirement_text": f"When design pressure greater than 5 MPa, the {PRESSURE} shall not exceed 10 bar.",
            "clause": "6.1",
            "requirement_type": "statement",
        },
        [PRESSURE],
        {PRESSURE: "design_pressure"},
        {PRESSURE: ("pressure",)},
    )
    assert answer_case[0] == "verified", answer_case[1]
    assert answer_case[2].condition == "design pressure greater than 5 MPa"
    assert _evaluated(answer_case[2].condition) == conditions.SATISFIED


def test_a_converter_condition_in_millipascal_is_stored_as_printed():
    condition = "design pressure greater than 5 mPa"
    status, why, check = standards_converter.verify(
        {
            "condition": condition,
            "field": 0,
            "comparator": "<=",
            "limit": "10",
            "unit": "bar",
            "quote": f"{PRESSURE} shall not exceed 10 bar",
        },
        {
            "requirement_text": f"When {condition}, the {PRESSURE} shall not exceed 10 bar.",
            "clause": "6.1",
            "requirement_type": "statement",
        },
        [PRESSURE],
        {PRESSURE: "design_pressure"},
        {PRESSURE: ("pressure",)},
    )
    assert status == "verified", why
    assert check.condition == condition
    assert _evaluated(check.condition) == conditions.UNKNOWN


def _compiled(condition, exception, text):
    return compiled_rule_proof._kept_rule(
        {"clause": "6.1", "page": 1},
        {
            "quote": "the level shall not exceed 10 bar",
            "limit": "10",
            "unit": "bar",
            "applies_to": "pump",
            "condition": condition,
            "exception": exception,
            "name": "level",
            "comparator": "<=",
        },
        [],
        "shall",
        text,
    )


def test_a_stored_compiled_condition_keeps_the_printed_case():
    text = "When design pressure greater than 5 mPa, except above 9 mPa, the level shall not exceed 10 bar."
    kept = _compiled("design pressure greater than 5 mPa", "except above 9 mPa", text)
    assert kept["condition_text"] == "design pressure greater than 5 mPa"
    assert kept["exception_text"] == "except above 9 mPa"
    assert _evaluated(kept["condition_text"]) == conditions.UNKNOWN


def test_a_compiled_condition_is_stored_as_the_page_prints_it():
    text = "When design pressure greater than 5 mPa, the level shall not exceed 10 bar."
    kept = _compiled("design  pressure greater than 5 mpa", "", text)
    assert kept["condition_text"] == "design pressure greater than 5 mPa"
    assert kept["exception_text"] is None


def test_a_condition_retyped_in_the_other_case_is_not_on_the_page():
    text = "When pressure is greater than 5 mPa, the level shall not exceed 10 bar."
    assert compiled_rule_proof._condition_on_page(
        "pressure is greater than 5 mPa", text
    )
    assert not compiled_rule_proof._condition_on_page(
        "pressure is greater than 5 MPa", text
    )


# ------------------------------------------------- a unit is a whole word


@pytest.mark.parametrize("label", ["NORMAL SIGNAL", "MAX SIGNAL", "THERMAL SIGNAL"])
def test_a_label_holding_the_letters_of_a_unit_is_not_the_unit(label):
    page = f"Item | MA\n{label} | 20\n"
    proposal = {
        "field": label.lower(),
        "value": "20",
        "unit": "mA",
        "kind": "offered",
        "quote": f"{label} | 20",
    }
    done = claude_datasheet.accept([proposal], page)
    assert done["rejected"] == []
    assert done["accepted"][0]["unit"] == "MA"


def test_a_converter_condition_retyped_in_the_other_case_is_not_in_the_clause():
    verdict = standards_converter.verify(
        {
            "condition": "design pressure greater than 5 MPa",
            "field": 0,
            "comparator": "<=",
            "limit": "10",
            "unit": "bar",
            "quote": f"{PRESSURE} shall not exceed 10 bar",
        },
        {
            "requirement_text": f"When design pressure greater than 5 mPa, the {PRESSURE} shall not exceed 10 bar.",
            "clause": "6.1",
            "requirement_type": "statement",
        },
        [PRESSURE],
        {PRESSURE: "design_pressure"},
        {PRESSURE: ("pressure",)},
    )
    assert verdict[:2] == ("unproven", "condition_not_in_clause")


@pytest.mark.parametrize(
    "part,expected",
    [
        ("ABOVE 5 MPa", "above 5 MPa"),
        ("above 5 mPa", "above 5 mPa"),
        ("above 7 bar", "above 7 bar"),
        (None, ""),
        ("", ""),
    ],
)
def test_as_printed_on_takes_the_copy_in_its_own_case(part, expected):
    assert (
        converter_gates.as_printed_on(part, "at above 5 mPa or above 5 MPa") == expected
    )
