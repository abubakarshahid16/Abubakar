"""#1518: the datasheet reader, rule tables, answer figures and nominal clauses
also read a leading-dot decimal (".5 mm") when LEADING_DOT_DECIMAL_ENABLED is
on. Off, today's drop is pinned. Values are invented."""

from __future__ import annotations

import pytest

from app import answer, claims, datasheets, requirements_3b, rule_eval
from app.config import settings

TABLE = "Up to .5 mm | MOP + .5 mm\nOver .5 up to 3 mm | 1.1 x MOP\nOver 3 mm | 2 x MOP"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "leading_dot_decimal_enabled", True)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "leading_dot_decimal_enabled", False)


def _rows():
    rule = rule_eval.parse_rule(TABLE, output="x", input_names=["mop"])
    return [(r["from"], r["to"]) for r in rule["rows"]]


def _figures(text):
    return [(f["value"], f["sign"], f["unit"]) for f in answer._figure_occurrences(text)]


def test_off_the_datasheet_reader_drops_a_leading_dot_value(off):
    assert datasheets.measure_value(".5 mm") == (None, None, None)
    assert datasheets._is_numeric_cell(".5") is False


def test_on_the_datasheet_reader_reads_a_leading_dot_value(on):
    value, unit, measured = datasheets.measure_value(".5 mm")
    assert (value, unit) == (".5", "mm")
    assert measured.normalized_value == claims.normalise("0.5", "mm").normalized_value
    value, unit, measured = datasheets.measure_value("-.5 C")
    assert (value, unit) == ("-.5", "C") and measured.normalized_value < 0
    assert datasheets._is_numeric_cell(".5") and datasheets._is_numeric_cell("< .25")


@pytest.mark.parametrize("text", [".5.3 mm", "...5 mm", ". 5 mm", ".5.3"])
def test_on_an_ambiguous_dot_is_no_value(on, text):
    assert datasheets.measure_value(text) == (None, None, None)
    assert datasheets._is_numeric_cell(".5.3") is False


def test_on_the_reader_is_unchanged_for_ordinary_values(on):
    assert datasheets.measure_value("5 mm")[:2] == ("5", "mm")
    assert datasheets.measure_value("0.5 mm")[:2] == ("0.5", "mm")
    assert datasheets.measure_value("340 psig")[:2] == ("340", "psig")
    assert datasheets.measure_value("approx. 5") == (None, None, None)
    assert datasheets.measure_value("p.4") == (None, None, None)


def test_off_a_rule_table_loses_the_leading_dot_rows(off):
    assert _rows() == [(3.0, None)]


def test_on_a_rule_table_reads_the_leading_dot_bounds(on):
    assert _rows() == [(None, 0.5), (0.5, 3.0), (3.0, None)]
    term = rule_eval.parse_rule(TABLE, output="x", input_names=["mop"])["rows"][0]["terms"][0]
    assert term == {"k": 1.0, "c": 0.5}


def test_on_a_rule_table_stranded_dot_is_no_bound(on):
    rule = rule_eval.parse_rule("Up to .5.3 mm | MOP\nOver 3 mm | 2 x MOP", output="x", input_names=["mop"])
    assert [(r["from"], r["to"]) for r in rule["rows"]] == [(3.0, None)]


def test_off_an_answer_figure_has_no_unit_for_a_leading_dot_value(off):
    assert _figures("gap .5 mm") == [("0.5", "+", None)]


def test_on_an_answer_figure_binds_its_unit(on):
    assert _figures("gap .5 mm and -.5 C") == [("0.5", "+", "mm"), ("0.5", "-", "c")]
    assert _figures("p.4 mm, set to 5.") == [("4.0", "+", None), ("5.0", "+", None)]


CLAUSE = "The supply shall be 24 V DC at .5 Hz."


def test_off_a_second_leading_dot_quantity_is_not_seen(off):
    assert requirements_3b.parse_nominal(CLAUSE) is not None


def test_on_a_second_leading_dot_quantity_is_a_second_claim(on):
    assert requirements_3b.parse_nominal(CLAUSE) is None
    assert requirements_3b.parse_nominal("The supply shall be 24 V DC.")["raw_value"] == "24"
