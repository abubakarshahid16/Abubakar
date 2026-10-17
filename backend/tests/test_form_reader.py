"""THE FORM READER: one general path, any layout, code only verifies.

`form_reader.py` + `form_reader_fields.py` + `form_reader_run.py`, behind
DATASHEET_READER_MODE=form (the default since #882; "merge" is the old path). Every model here
is a FAKE scripted callable: no network, no Ollama, no Claude, and every page
text is invented.

What is proved:
  * one field list, three invented layouts (label: value lines, a table
    rendered as text, a sentence) -> the same verified facts, with no layout
    code anywhere in the reader;
  * the field list comes from the reference data only (a role added to the
    data appears; an unknown type gets the generic list);
  * each gate rejects with its named reason: quote not on the page, value not
    in the quote, label not in the quote, wrong unit kind, two runs disagree;
  * a malformed / failing / timed-out model is a reason, never a raise;
  * two pages stating two values -> both kept, CONFLICT;
  * the default setting runs the old path and never the form reader; "form"
    writes the form reader's facts through the existing merge.
"""

from __future__ import annotations

import json
import re

import pytest

from app import (
    datasheet_ai,
    datasheet_checks,
    datasheets,
    db,
    form_reader,
    form_reader_fields,
    form_reader_run,
    submittal_review,
)
from app.config import Settings, settings

PUMP = "Centrifugal Pump"

LINES = """EQUIPMENT DATASHEET - CENTRIFUGAL PUMP
Design pressure: 23.5 barg
Design temperature: 120 °C
Rated flow: 42 m3/h
Operating temperature: 85 °C
"""

TABLE = """| Item | Description        | Unit | Value |
|------|--------------------|------|-------|
| 1    | Rated flow         | m3/h | 42    |
| 2    | Design pressure    | barg | 23.5  |
| 3    | Design temperature | °C   | 120   |
| 4    | Operating temp.    | °C   | 85    |
"""

PROSE = ("The pump is built for a design pressure of 23.5 barg at a design\n"
         "temperature of 120 °C. It delivers a rated flow of 42 m3/h while the\n"
         "operating temperature is 85 °C.\n")


def row(key, value="", unit="", quote="", status="found"):
    return {"field_key": key, "value": value, "unit": unit, "quote": quote, "status": status}


def absent(key):
    return row(key, status="not_on_page")


class FakeModel:
    """`prompt -> text`. `script[page]` is a list of answers, one per call on
    that page (the last repeats); an answer is a list of rows, raw text, or an
    exception to raise. Only the rows whose key the prompt asks for are sent,
    as a batching model would."""

    engine = "fake-engine"
    model = "fake-model"

    def __init__(self, script):
        self.script = script
        self.calls: list[int] = []
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        page = int(re.search(r"\nPAGE (\d+):\n", prompt).group(1))
        self.calls.append(page)
        self.prompts.append(prompt)
        answers = self.script[page]
        answer = answers[min(self.calls.count(page) - 1, len(answers) - 1)]
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, str):
            return answer
        asked = set(re.findall(r"^  - (\w+): ", prompt, flags=re.MULTILINE))
        return json.dumps({"fields": [r for r in answer if r["field_key"] in asked]})


def _read(text, rows, equipment_type=PUMP, **kw):
    model = FakeModel({1: [rows]})
    return form_reader.read_form({1: text}, equipment_type, model, **kw), model


def _values(reading):
    return sorted((f["field_key"], f["value"], f["unit"]) for f in reading.facts)


EXPECTED = [("design_pressure", "23.5", "barg"), ("design_temperature", "120", "°C"),
            ("operating_temperature", "85", "°C"), ("rated_flow", "42", "m3/h")]


# ===================================================== layout independence

@pytest.mark.parametrize("text, rows", [
    (LINES, [row("design_pressure", "23.5", "barg", "Design pressure: 23.5 barg"),
             row("design_temperature", "120", "°C", "Design temperature: 120 °C"),
             row("rated_flow", "42", "m3/h", "Rated flow: 42 m3/h"),
             row("operating_temperature", "85", "°C", "Operating temperature: 85 °C")]),
    (TABLE, [row("design_pressure", "23.5", "barg", "| 2    | Design pressure    | barg | 23.5  |"),
             row("design_temperature", "120", "°C", "| 3    | Design temperature | °C   | 120   |"),
             row("rated_flow", "42", "m3/h", "| 1    | Rated flow         | m3/h | 42    |"),
             row("operating_temperature", "85", "°C", "| 4    | Operating temp.    | °C   | 85    |")]),
    (PROSE, [row("design_pressure", "23.5", "barg", "design pressure of 23.5 barg"),
             row("design_temperature", "120", "°C", "design\ntemperature of 120 °C"),
             row("rated_flow", "42", "m3/h", "rated flow of 42 m3/h"),
             row("operating_temperature", "85", "°C", "operating temperature is 85 °C")]),
], ids=["label-value-lines", "table-as-text", "sentences"])
def test_one_field_list_three_layouts_the_same_facts(text, rows):
    reading, model = _read(text, rows)
    assert _values(reading) == EXPECTED
    assert reading.rejected == []
    assert set(reading.status.values()) == {form_reader.FILLED}
    assert model.calls == [1, 1]                      # two runs, one batch
    fact = reading.facts[0]
    assert fact["extraction_method"] == "model" and fact["kind"] == "offered"
    assert fact["provenance"]["reader"] == "form_reader"
    assert fact["provenance"]["page"] == 1 and fact["provenance"]["field_key"] == fact["field_key"]
    assert fact["field_name"] == datasheets.normalise_field_name(fact["field"])


def test_the_written_field_name_is_one_the_review_maps_back_to_its_role():
    rules = datasheet_checks.load_rules()
    for kind in (PUMP, "Pressure Vessel", "Heat Exchanger"):
        for f in form_reader_fields.field_list_for(kind, rules):
            assert datasheet_checks.role_of(datasheets.normalise_field_name(f.name), rules) == f.key
    # The PSV list: every role but one. "rated capacity" is claimed by the
    # earlier role `rated_flow` in the data ('^rated (flow|capacity)$'), so
    # no spelling the data gives maps back to `rated_capacity` - a DATA
    # finding, reported, not patched here.
    psv = form_reader_fields.field_list_for("Pressure Safety Valve", rules)
    off = [f.key for f in psv
           if datasheet_checks.role_of(datasheets.normalise_field_name(f.name), rules) != f.key]
    assert off == ["rated_capacity"]


# ===================================================== the field list is data

def test_an_unknown_equipment_type_gets_the_generic_list():
    rules = datasheet_checks.load_rules()
    keys = [f.key for f in form_reader_fields.field_list_for("Space elevator", rules)]
    assert keys == rules["mandatory"]["_generic"]
    assert [f.key for f in form_reader_fields.field_list_for(None, rules)] == keys


def test_the_field_list_follows_the_reference_data_not_code():
    rules = datasheet_checks.load_rules()
    rules["roles"]["paint_system"] = {"kind": "text", "names": ["^paint system$"]}
    rules["mandatory"]["_generic"] = [*rules["mandatory"]["_generic"], "paint_system"]
    fields = form_reader_fields.field_list_for(None, rules)
    assert [f.key for f in fields][-1] == "paint_system"
    assert fields[-1].name == "Paint system" and fields[-1].unit_kind == "text"


def test_the_schema_is_flat():
    schema = form_reader_fields.schema_for(form_reader_fields.field_list_for(PUMP))
    assert "$defs" not in json.dumps(schema)
    items = schema["properties"]["fields"]["items"]
    assert all(p["type"] == "string" for p in items["properties"].values())
    assert set(items["required"]) == {"field_key", "value", "unit", "quote", "status"}


def test_a_long_list_is_read_in_batches_of_at_most_25():
    fields = form_reader_fields.field_list_for("Pressure Safety Valve")
    assert len(fields) > 25
    reading, model = _read(LINES, [absent(f.key) for f in fields],
                           equipment_type="Pressure Safety Valve")
    assert len(model.calls) == 4                      # two batches, two runs each
    assert all(len(re.findall(r"^  - \w+: ", p, flags=re.MULTILINE)) <= 25 for p in model.prompts)
    assert reading.status["design_pressure"] == form_reader.NOT_ON_PAGE


# ===================================================== the gates

def _one(text, the_row, key="design_pressure"):
    reading, _ = _read(text, [the_row])
    return reading.status[key], [r["reason"] for r in reading.rejected if r["field_key"] == key]


def test_a_quote_not_on_the_page_is_rejected():
    assert _one(LINES, row("design_pressure", "23.5", "barg", "Design pressure: 23.5 barg max")) == (
        form_reader.MISSING, ["quote_not_on_page"])


def test_a_value_not_in_the_quote_is_rejected():
    assert _one(LINES, row("design_pressure", "25", "barg", "Design pressure: 23.5 barg")) == (
        form_reader.MISSING, ["value_not_in_quote"])


def test_a_quote_without_the_fields_label_is_rejected():
    status, why = _one(LINES, row("design_pressure", "120", "°C", "Design temperature: 120 °C"))
    assert (status, why) == (form_reader.MISSING, ["label_not_in_quote"])


def test_a_unit_of_the_wrong_kind_is_rejected():
    text = "Design pressure: 120 °C\n"
    assert _one(text, row("design_pressure", "120", "°C", "Design pressure: 120 °C")) == (
        form_reader.MISSING, ["wrong_unit_kind"])


def test_a_unit_not_printed_in_the_quote_is_rejected():
    assert _one(LINES, row("design_pressure", "23.5", "psig", "Design pressure: 23.5 barg")) == (
        form_reader.MISSING, ["unit_not_in_quote"])


def test_two_runs_that_disagree_are_not_accepted():
    good = row("design_pressure", "23.5", "barg", "Design pressure: 23.5 barg")
    other = row("design_temperature", "120", "°C", "Design temperature: 120 °C")
    model = FakeModel({1: [[good, other], [{**good, "value": "25"}, other]]})
    reading = form_reader.read_form({1: LINES}, PUMP, model)
    assert reading.status["design_pressure"] == form_reader.MISSING
    assert {"field_key": "design_pressure", "page": 1, "reason": "model_unstable"} in reading.rejected
    assert reading.status["design_temperature"] == form_reader.FILLED


def test_one_run_when_asked():
    reading, model = _read(LINES, [row("design_pressure", "23.5", "barg",
                                       "Design pressure: 23.5 barg")], runs=1)
    assert model.calls == [1] and reading.status["design_pressure"] == form_reader.FILLED


def test_a_blank_marker_is_not_a_value():
    text = "Design pressure: TBA\n"
    assert _one(text, row("design_pressure", "TBA", "", "Design pressure: TBA")) == (
        form_reader.MISSING, ["value_is_blank_marker"])


# ===================================================== never raises

@pytest.mark.parametrize("answer, reason", [
    ('{"fields": [ {"field_key": "design_pressure", "val', "model_malformed"),
    ("I could not read this page.", "model_malformed"),
    (RuntimeError("engine down"), "model_failed"),
    (TimeoutError("slow"), "model_timed_out"),
])
def test_a_bad_model_is_a_reason_never_a_raise(answer, reason):
    model = FakeModel({1: [answer]})
    reading = form_reader.read_form({1: LINES}, PUMP, model)
    assert reading.facts == []
    assert set(reading.status.values()) == {form_reader.MISSING}
    assert reading.counts()["rejected_by_reason"] == {reason: 4}
    assert reason in reading.errors[1]


def test_a_page_without_text_is_not_sent():
    model = FakeModel({1: [[]]})
    reading = form_reader.read_form({1: "  \n"}, PUMP, model)
    assert model.calls == [] and reading.errors == {1: "no text on this page"}


# ===================================================== pages and conflicts

def test_two_pages_with_two_values_keep_both_as_a_conflict():
    page2 = "Design pressure: 25 barg\n"
    model = FakeModel({
        1: [[row("design_pressure", "23.5", "barg", "Design pressure: 23.5 barg")]],
        2: [[row("design_pressure", "25", "barg", "Design pressure: 25 barg")]]})
    reading = form_reader.read_form({1: LINES, 2: page2}, PUMP, model)
    assert reading.status["design_pressure"] == form_reader.CONFLICT
    both = [f for f in reading.facts if f["field_key"] == "design_pressure"]
    assert sorted(f["value"] for f in both) == ["23.5", "25"]
    assert all(f["form_conflict"] and f["provenance"]["conflict_pages"] == [1, 2] for f in both)
    assert reading.counts()["conflicts"] == 1


def test_the_same_value_on_two_pages_is_one_fact():
    model = FakeModel({p: [[row("design_pressure", "23.5", "barg", "Design pressure: 23.5 barg")]]
                       for p in (1, 2)})
    reading = form_reader.read_form({1: LINES, 2: LINES}, PUMP, model)
    facts = [f for f in reading.facts if f["field_key"] == "design_pressure"]
    assert len(facts) == 1 and facts[0]["provenance"]["also_on_pages"] == [2]
    counts = reading.counts()
    assert (counts["filled"], counts["missing"], counts["not_on_page"]) == (1, 3, 0)
    # the three fields the model left out are named, per page, not dropped
    assert counts["rejected_by_reason"] == {"field_not_answered": 6}


def test_a_field_the_model_says_is_not_on_any_page_is_not_on_page():
    reading, _ = _read(LINES, [absent("design_pressure")])
    assert reading.status["design_pressure"] == form_reader.NOT_ON_PAGE
    assert reading.status["rated_flow"] == form_reader.MISSING


# ===================================================== inside extraction

@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "form.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield tmp_path
    db.reset_connection()


ROWS = [("Design pressure", "23.5 barg"), ("Design temperature", "120 C")]


def _extract(tmp_path):
    from tests.test_datasheet_ai import _datasheet_pdf, _ingest
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    return result, datasheets.list_facts(doc, allowed_document_ids=frozenset({doc}))


def test_the_default_mode_is_form(monkeypatch):
    """#882: the form reader is the default reading; unset also means form."""
    assert Settings.model_fields["datasheet_reader_mode"].default == "form"
    assert Settings(_env_file=None).datasheet_reader_mode == "form"
    assert Settings(_env_file=None).form_reader_batch_size == 8
    monkeypatch.setattr(settings, "datasheet_reader_mode", "")
    assert form_reader_run.reader_mode() == "form"


def test_merge_mode_never_runs_the_form_reader(storage, monkeypatch):
    monkeypatch.setattr(settings, "datasheet_reader_mode", "merge")
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(datasheet_ai, "model_call_for",
                        lambda engine=None, packet_shape=None: (lambda p: '{"facts": []}', None))

    def refuse(*_a, **_k):
        raise AssertionError("the form reader ran in merge mode")
    monkeypatch.setattr(form_reader_run, "read_document", refuse)
    result, _facts = _extract(storage)
    assert "form" not in result["ai_reader"] and "reader" not in result["ai_reader"]


def test_rules_mode_asks_no_model(storage, monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(settings, "datasheet_reader_mode", "rules")
    monkeypatch.setattr(datasheet_ai, "model_call_for",
                        lambda *a, **k: pytest.fail("a model was asked in rules mode"))
    result, facts = _extract(storage)
    assert "ai_reader" not in result and facts


def test_an_unknown_mode_is_refused_at_startup():
    with pytest.raises(ValueError):
        Settings(datasheet_reader_mode="layout-patch", _env_file=None)


def test_form_mode_writes_verified_facts_through_the_existing_merge(storage, monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(settings, "datasheet_reader_mode", "form")
    asked = []

    def model_call_for(engine=None, packet_shape=None):
        asked.append(packet_shape)     # the form's call, then (#1004) the whole-page reading's
        return FakeModel({1: [[row("design_pressure", "23.5", "barg", "Design pressure 23.5 barg"),
                               row("design_temperature", "120", "C", "Design temperature 120 C")]]}), None
    monkeypatch.setattr(datasheet_ai, "model_call_for", model_call_for)
    result, facts = _extract(storage)
    assert asked[0]["prompt_version"] == form_reader_fields.PROMPT_VERSION and asked[1:] == [None]
    stats = result["ai_reader"]
    assert stats["reader"] == "form_reader" and stats["form"]["filled"] == 2
    assert stats["agreed"] == 2                       # the rule readers cross-check
    pressure = [f for f in facts if f["field_name"] == "design pressure"]
    assert len(pressure) == 1 and pressure[0]["confidence"] == datasheet_ai.AGREED_CONFIDENCE
    box = json.loads(pressure[0]["bbox"])
    assert box["reader"] == "form_reader" and box["field_key"] == "design_pressure"
    assert box["quote_on_page"] is True


# ---------------------------------------------------------------- #1004: the form adds, never replaces

def _page(accepted, error=None):
    out = {"page": 1, "engine": "ollama", "accepted": accepted, "rejected": [], "counts": {}}
    if error:
        out["error"] = error
    return out


def _fact(name, value):
    return {"field_name": name, "field": name, "value": value, "quote": f"{name} {value}", "page": 1}


def test_the_merge_reading_of_fields_the_form_did_not_read_is_kept():
    """PF1 17 Oct, a transmitter: form-only lost 4 values the merge reader had."""
    form = {"pages": {1: _page([_fact("design pressure", "10")])}, "reasons": {}, "stopped": None, "seconds": 5}
    merge = {"pages": {1: _page([_fact("design pressure", "11"), _fact("output signal", "4-20 mA")])},
             "stopped": None, "seconds": 7}
    out = form_reader_run.add_merge_reading(form, merge)
    got = {f["field_name"]: f["value"] for f in out["pages"][1]["accepted"]}
    assert got == {"design pressure": "10", "output signal": "4-20 mA"}   # the form's own value wins its field
    assert out["added_from_merge"] == 1 and out["seconds"] == 12


def test_a_page_the_form_could_not_read_takes_the_merge_reading():
    form = {"pages": {1: _page([], error="form reader could not read this page")},
            "reasons": {1: "form reader could not read this page"}, "stopped": None, "seconds": 1}
    merge = {"pages": {1: _page([_fact("enclosure rating", "IP66")])}, "stopped": None, "seconds": 2}
    out = form_reader_run.add_merge_reading(form, merge)
    assert [f["field_name"] for f in out["pages"][1]["accepted"]] == ["enclosure rating"]
    assert 1 not in out["reasons"] and out["added_from_merge"] == 1


def test_a_merge_page_with_an_error_adds_nothing():
    form = {"pages": {1: _page([_fact("design pressure", "10")])}, "reasons": {}, "stopped": None, "seconds": 1}
    merge = {"pages": {1: _page([_fact("output signal", "4-20 mA")], error="engine failed")},
             "stopped": "usd_cap_reached", "seconds": 1}
    out = form_reader_run.add_merge_reading(form, merge)
    assert len(out["pages"][1]["accepted"]) == 1 and out["added_from_merge"] == 0
    assert out["stopped"] == "usd_cap_reached"
