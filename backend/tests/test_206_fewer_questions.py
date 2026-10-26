"""Order 206.1 (#882): fewer AI questions per page, no loss in values found.

The form reader asked the model for EVERY field of the type's list on EVERY
page, in batches (8 fields, two runs each: 16 questions a page for 60 fields).
`verify` refuses any value whose quote lacks the field's label, and a quote is
a piece of the page, so a field whose label is printed nowhere on the page can
never be answered. It is no longer asked. Fake model, invented text, no AI, no
database, a few seconds (Rule A).
"""

from __future__ import annotations

import json
import re

import pytest

from app import claude_datasheet, datasheet_checks, form_reader, form_reader_fields
from app.form_reader_fields import Field

PUMP = "Centrifugal Pump"
LONG = "Pressure Safety Valve"  # a long field list: several batches of 8
PAGE = """EQUIPMENT DATASHEET - CENTRIFUGAL PUMP
Design pressure: 23.5 barg
Design temperature: 120 °C
Rated flow: 42 m3/h
"""
ROWS = {
    "design_pressure": ("23.5", "barg", "Design pressure: 23.5 barg"),
    "design_temperature": ("120", "°C", "Design temperature: 120 °C"),
    "rated_flow": ("42", "m3/h", "Rated flow: 42 m3/h"),
}


class Model:
    """Answers every asked field it has a row for; counts the questions."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        asked = re.findall(r"^  - (\w+): ", prompt, flags=re.MULTILINE)
        out = []
        for key in asked:
            if key in ROWS:
                value, unit, quote = ROWS[key]
                out.append(
                    {
                        "field_key": key,
                        "value": value,
                        "unit": unit,
                        "quote": quote,
                        "status": "found",
                    }
                )
            else:
                out.append(
                    {
                        "field_key": key,
                        "value": "",
                        "unit": "",
                        "quote": "",
                        "status": "not_on_page",
                    }
                )
        return json.dumps({"fields": out})


def _read(text, monkeypatch=None, everything=False, equipment=PUMP, **kw):
    if everything:  # the reader as it was: every field asked on every page
        monkeypatch.setattr(form_reader, "label_on_page", lambda *a, **k: True)
    model = Model()
    reading = form_reader.read_form({1: text}, equipment, model, **kw)
    return reading, model


def _facts(reading):
    return sorted((f["field_key"], f["value"], f["unit"]) for f in reading.facts)


def test_fewer_questions_and_the_same_facts(monkeypatch):
    """THE CASE: a page that prints 3 of the type's fields is asked about those, not all."""
    asked_now, now = _read(PAGE, equipment=LONG, batch_size=8)
    asked_before, before = _read(
        PAGE, monkeypatch, everything=True, equipment=LONG, batch_size=8
    )
    assert len(before.prompts) > len(now.prompts) > 0
    assert _facts(asked_now) == _facts(asked_before)
    assert len(_facts(asked_now)) >= 2  # not equal because both are empty


def test_a_page_that_prints_no_label_asks_nothing_and_is_not_on_page():
    reading, model = _read("Revision A - issued for review\nSheet 1 of 4\n")
    assert model.prompts == []
    assert reading.pages_read == [1] and reading.facts == []
    assert set(reading.status.values()) == {form_reader.NOT_ON_PAGE}


def test_a_field_whose_only_label_is_a_synonym_is_still_asked():
    f = Field(
        key="req_capacity",
        name="Capacity",
        unit_kind=None,
        synonyms=("throughput rate",),
    )
    model = Model()
    form_reader.read_form({1: "Throughput rate: 5 kg/s\n"}, None, model, fields=[f])
    assert len(model.prompts) == 2  # two runs of one batch


def test_a_field_whose_label_is_nowhere_on_the_page_is_not_asked():
    f = Field(
        key="req_capacity",
        name="Capacity",
        unit_kind=None,
        synonyms=("throughput rate",),
    )
    model = Model()
    form_reader.read_form({1: "Design pressure: 23.5 barg\n"}, None, model, fields=[f])
    assert model.prompts == []


def test_whatever_the_gate_would_accept_the_filter_keeps():
    """The property behind zero loss: every quote (here every line, and every
    run of two lines) whose label the gate accepts comes from a page the filter
    keeps the field for."""
    rules = datasheet_checks.load_rules()
    fields = form_reader_fields.field_list_for(PUMP, rules)
    lines = PAGE.splitlines()
    quotes = lines + [" ".join(lines[i : i + 2]) for i in range(len(lines) - 1)]
    for f in fields:
        for quote in quotes:
            printed = claude_datasheet.without_fill(form_reader._fold(quote))
            if form_reader.label_in_quote(f, printed, rules):
                assert form_reader.label_on_page(f, PAGE, rules), (f.key, quote)


@pytest.mark.parametrize("text", ["", "   \n"])
def test_a_page_without_text_is_still_skipped_by_the_page_rule(text):
    reading, model = _read(text)
    assert model.prompts == [] and reading.errors == {1: "no text on this page"}


def test_the_summary_counts_the_questions_and_the_fields_not_asked_per_page():
    reading, model = _read(PAGE, equipment=LONG, batch_size=8)
    counts = reading.counts()
    assert counts["questions_asked"] == len(model.prompts) > 0
    assert counts["fields_not_asked"] == len(reading.fields) - sum(
        1
        for f in reading.fields
        if form_reader.label_on_page(f, PAGE, datasheet_checks.load_rules())
    )
    assert counts["per_page"][1] == {
        "questions": counts["questions_asked"],
        "fields_not_asked": counts["fields_not_asked"],
    }


def test_a_page_that_prints_no_label_counts_zero_questions_and_all_fields_not_asked():
    reading, _ = _read("Revision A - issued for review\n", equipment=LONG)
    counts = reading.counts()
    assert counts["questions_asked"] == 0
    assert counts["fields_not_asked"] == len(reading.fields)
