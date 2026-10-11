"""Planner 2026-10-11 (the reader job, roadmap R11): the reader keeps the
answers the checklist needs.

#764's coverage line listed ten relief-valve checklist fields "on the sheet but
not read". On the real sheet every one of those label-value pairs WAS
recovered - and then thrown away:

  * a free-text answer ("Valve type: Balanced bellows", "Fluid: ...",
    a spring or bellows material) failed the value gate, which treats free
    text as a caption (audit 69);
  * "Required relieving capacity: <n> kg/h Note - <n>" was not a number,
    because a trailing note reference read as prose after it;
  * "Body: <one material>" - the same answer on every valve of a
    one-valve-per-page sheet - was stripped as page furniture.

The fix is generic and the labels are DATA: a label the reference data names
as a field (`datasheet_checks.json` roles, the same match the checklist uses)
is a field, not a caption and not furniture. A label the data does not name
is gated exactly as before. Invented data only.
"""
from __future__ import annotations

import pytest

from app import datasheets, db, submittal_review
from app.config import settings
from tests.test_179_layouts import _ingest, _ruled_pdf


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rd.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


# ------------------------------------------------ the note reference

def test_a_trailing_note_reference_does_not_hide_the_number():
    value, unit, measured = datasheets.measure_value("5200 kg/h Note – 3")
    assert (value, unit) == ("5200", "kg/h")
    assert measured is not None and measured.normalized_value == 5200.0
    assert datasheets.measure_value("120 kg/h Notes 2 & 4")[0] == "120"
    assert datasheets.states_a_value("5200 kg/h Note – 3")


def test_prose_after_a_number_is_still_not_a_measurement():
    assert datasheets.measure_value("3rd Floor Store") == (None, None, None)
    assert datasheets.measure_value("5200 kg/h Pump A only") == (None, None, None)
    assert datasheets.measure_value("12 Notebook stands") == (None, None, None)


# ------------------------------------------------ a named text field

def test_a_named_text_fields_words_are_its_value():
    assert datasheets.states_a_named_text_value("Valve type", "Balanced bellows")
    assert datasheets.states_a_named_text_value("Fluid", "Natural gas")
    assert datasheets.states_a_named_text_value("Spring material", "Alloy 718")


def test_a_caption_a_blank_and_a_quantity_field_are_not():
    # audit 69 holds: a label the data does not name stays a caption
    assert not datasheets.states_a_named_text_value("Prepared by", "A. Engineer")
    assert not datasheets.states_a_named_text_value("Location", "North Unit")
    # a blank is still no value, whatever the label
    assert not datasheets.states_a_named_text_value("Valve type", "By Contractor")
    assert not datasheets.states_a_named_text_value("Valve type", "")
    assert not datasheets.states_a_named_text_value("Valve type", "--")
    # words under a QUANTITY field are not its value ("Set pressure": "high")
    assert not datasheets.states_a_named_text_value("Set pressure", "see note")
    # a nozzle table's header row (F1 pump sheet) is no answer
    assert not datasheets.states_a_named_text_value("Type", "Facing")
    assert datasheets.states_a_named_text_value("Type", "Conventional spring loaded")


def test_the_trim_is_read_under_the_names_a_valve_sheet_prints():
    """`datasheet_checks.json` trim_material: the sheet prints the trim as
    "Nozzle/ base material" and "Disc insert material"."""
    from app import datasheet_checks
    rules = datasheet_checks.load_rules()
    role = lambda label: datasheet_checks.role_of(datasheets.normalise_field_name(label), rules)
    assert role("Nozzle/ base material") == "trim_material"
    assert role("Disc insert material") == "trim_material"
    assert role("Disc material") == "trim_material"
    assert role("Disc holder material") is None        # a holder is not the trim


# ------------------------------------------------ furniture

def test_a_named_field_with_one_answer_on_every_page_is_not_furniture():
    pages = {p: [("Body", "SA-105"), ("Valve type", "Balanced bellows"),
                 ("DOCUMENT NO.", "DS-0001")] for p in range(1, 6)}
    furniture = datasheets.furniture_labels(pages)
    assert "body" not in furniture and "valve type" not in furniture
    assert "document no" in furniture          # the title block is still stripped


# ------------------------------------------------ end to end

def _sheet(tmp_path, pages, doc_id="doc_rd"):
    """A ruled numbered form, one valve per page (`| no | label | value |`),
    stored and chunked the way an upload leaves it."""
    path = _ruled_pdf(tmp_path / f"{doc_id}.pdf", pages, [24, 160, 220])
    return _ingest(path, doc_id)


def test_the_reader_keeps_the_checklist_answers_on_every_page(tmp_path):
    rows = [("1", "Fluid", "Natural gas"),
            ("2", "Required relieving capacity", "5200 kg/h Note - 3"),
            ("3", "Valve type", "Balanced bellows"),
            ("4", "Body", "SA-105"),
            ("5", "Spring material", "Alloy 718"),
            ("6", "Prepared by", "A. Engineer")]
    pages = [[("Sl. No", "PROCESS DATA", ""), *rows, ("7", "Set pressure", f"{300 + p * 10} psig")]
             for p in range(1, 5)]
    doc = _sheet(tmp_path, pages)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset([doc]))
    facts = datasheets.list_facts(doc, allowed_document_ids=frozenset([doc]))
    by_label: dict[str, set] = {}
    for f in facts:
        by_label.setdefault(f["field_label"], set()).add(f["page"])
    for label in ("Fluid", "Required relieving capacity", "Valve type", "Body", "Spring material"):
        assert by_label.get(label) == {1, 2, 3, 4}, (label, sorted(by_label))
    assert "Prepared by" not in by_label                 # still a caption
    capacity = next(f for f in facts if f["field_label"] == "Required relieving capacity")
    assert capacity["raw_unit"] == "kg/h" and not capacity["is_blank"]
