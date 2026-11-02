"""#1618: a unit whose case is its meaning keeps its case.

mPa is a millipascal and MPa a megapascal, a factor of 10^9. Folding case read
one as the other. All values here are invented.
"""

from __future__ import annotations

import pytest

from app import (
    answerability,
    applicability_v2,
    claims,
    condition_choice,
    datasheet_ai,
    datasheet_checks,
    dual_unit_form,
    field_copies,
    label_match,
    numparse,
    rule_eval,
    same_value,
    unit_case,
)


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


def test_a_rule_unit_is_not_proven_by_the_other_unit():
    assert rule_eval.unit_in_text("MPa", "rated 5 MPA")
    assert rule_eval.unit_in_text("MPag", "rated 5 mpa(g)")
    assert not rule_eval.unit_in_text("MPa", "rated 5 mPa")
    assert not rule_eval.unit_in_text("mPa", "rated 5 MPa")
    assert rule_eval.unit_in_text("mPa", "rated 5 mPa")


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
