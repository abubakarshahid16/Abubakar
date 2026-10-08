"""Datasheet benchmark fixes, round 1 (2026-09-30). Every value is made up.

  1. A ruled/grid table with a UNIT column (headed Units/Unit/UoM, or any
     header when its body is only units) or a unit in the value header
     ("Rated (kW)") gives the value its unit: "75" for a 75 kW motor was read
     as a WRONG value. The unit cell is no longer a fact of its own, and the
     geometry reader's glued "<row> <column header>" label is dropped when the
     table is KEY | UNIT | VALUE.
  2. The AI gate refuses a proposal whose value is a printed "not provided"
     marker, from the project's one list (`blank_markers`), whatever the model
     was told. The bench's ai-only reader showed 7 such cells as values
     because it records every accepted proposal as a value; hybrid stored them
     through `create_fact`, which classifies the text and blanks them.

The shapes that were already read stay read EXACTLY as before: the
characterisation cases below were taken from the code at bf009f1.

Mutations: M1760-M1779 (`scripts/mutations/datasheet_fix1.py`).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import blank_markers, datasheet_offline, datasheets
from app import claude_datasheet as cd
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "datasheet_bench_fix1_under_test", REPO / "scripts" / "datasheet_bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

pairs = datasheets.pairs_from_table_shape

# ============================================ 1. the unit on the value

def test_a_units_column_in_the_middle_gives_the_value_its_unit():
    out = pairs([["Parameter", "Units", "Value"], ["Rated power", "kW", "75"],
                 ["Frequency", "Hz", "50"]])
    assert out == [("Rated power - Value", "75 kW"), ("Frequency - Value", "50 Hz")]


def test_the_unit_cell_is_not_a_fact_of_its_own():
    out = pairs([["Item", "Unit", "Value"], ["Motor power", "kW", "75"]])
    assert not [f for f, _v in out if f.endswith("Unit")]


def test_a_uom_column_after_the_value_works_too():
    out = pairs([["Item", "Value", "UoM"], ["Motor power", "75", "kW"]])
    assert out == [("Motor power - Value", "75 kW")]


def test_a_unit_column_is_found_by_its_body_when_the_header_is_another_word():
    out = pairs([["Attribute", "Measure", "Figure"], ["Range", "bar", "40"],
                 ["Supply", "V", "24"], ["Protocol", "", "HART"]])
    assert out == [("Range - Figure", "40 bar"), ("Supply - Figure", "24 V"),
                   ("Protocol - Figure", "HART")]


def test_a_dash_or_blank_unit_leaves_the_value_bare():
    out = pairs([["Parameter", "Units", "Value"], ["Power factor", "-", "0.87"],
                 ["Weight", "kg", "520"], ["Class", "", "F"]])
    assert out == [("Power factor - Value", "0.87"), ("Weight - Value", "520 kg"),
                   ("Class - Value", "F")]


def test_only_a_bare_number_takes_the_unit():
    out = pairs([["Parameter", "Units", "Value"], ["Design pressure", "barg", "10 barg"],
                 ["Vendor item", "kW", "By Vendor"], ["Range", "mm", "5-10"],
                 ["Case", "kg", "Cast iron"], ["Weight", "kg", "520"]])
    assert out[0] == ("Design pressure - Value", "10 barg")
    assert out[1] == ("Vendor item - Value", "By Vendor")
    assert out[3] == ("Case - Value", "Cast iron")
    assert out[4] == ("Weight - Value", "520 kg")


def test_several_value_columns_share_the_rows_unit():
    out = pairs([["Item", "Unit", "Required", "Offered"], ["Flow", "m3/h", "50", "55"]])
    assert out == [("Flow - Required", "50 m3/h"), ("Flow - Offered", "55 m3/h")]


def test_a_unit_named_in_the_value_header_goes_on_the_value():
    out = pairs([["Item", "Rated (kW)", "Notes"], ["Motor", "75", "see note"],
                 ["Fan", "By Vendor", "x"]])
    assert out == [("Motor - Rated", "75 kW"), ("Motor - Notes", "see note"),
                   ("Fan - Rated", "By Vendor"), ("Fan - Notes", "x")]


def test_the_row_unit_wins_over_the_header_unit():
    out = pairs([["Item", "Unit", "Flow [m3/h]"], ["Pump", "l/h", "40"]])
    assert out == [("Pump - Flow", "40 l/h")]


def test_a_bracket_that_is_not_a_unit_changes_nothing():
    assert pairs([["Item", "Rated (design)", "Offered"], ["Motor", "75", "80"]]) == [
        ("Motor - Rated (design)", "75"), ("Motor - Offered", "80")]


# ---- what was read before is read the same (taken from bf009f1)

def test_a_table_without_units_is_unchanged():
    assert pairs([["Item", "Required", "Offered"], ["Design pressure", "10 barg", "12 barg"],
                  ["Flow", "5", "6"]]) == [
        ("Design pressure - Required", "10 barg"), ("Design pressure - Offered", "12 barg"),
        ("Flow - Required", "5"), ("Flow - Offered", "6")]


def test_a_notes_column_is_not_a_unit_column():
    assert pairs([["Item", "Value", "Notes"], ["Motor", "75", "see note"],
                  ["Fan", "By Vendor", "x"]]) == [
        ("Motor - Value", "75"), ("Motor - Notes", "see note"),
        ("Fan - Value", "By Vendor"), ("Fan - Notes", "x")]


def test_columns_of_ambiguous_letters_are_answers_not_units():
    # "F" and "A" are units AND grades; a column of nothing else is answers.
    assert pairs([["Item", "Class", "Grade"], ["Insulation", "F", "A"],
                  ["Enclosure", "B", "A"]]) == [
        ("Insulation - Class", "F"), ("Insulation - Grade", "A"),
        ("Enclosure - Class", "B"), ("Enclosure - Grade", "A")]


def test_the_two_tag_layout_is_unchanged():
    tag = datasheets._TAG_MARK
    assert pairs([["ITEM", "UNIT", "P-101A", "P-101B"], ["Noise level", "dB(A)", "85", "86"],
                  ["Vibration", "mm/s", "3.5", "*"]]) == [
        (f"Noise level{tag}P-101A", "85 dB(A)"), (f"Noise level{tag}P-101B", "86 dB(A)"),
        (f"Vibration{tag}P-101A", "3.5 mm/s"), (f"Vibration{tag}P-101B", "*")]


def test_a_spanning_header_table_is_unchanged():
    assert pairs([["TYPE", "METHODS", "ACCEPTANCE", ""], ["", "", "FABRICATIONS", "CASTINGS"],
                  ["RADIOGRAPHY", "RT", "10%", "100%"]]) == [
        ("RADIOGRAPHY - METHODS", "RT"),
        ("RADIOGRAPHY - ACCEPTANCE - FABRICATIONS", "10%"),
        ("RADIOGRAPHY - ACCEPTANCE - CASTINGS", "100%")]


def test_a_two_column_shape_is_unchanged():
    assert pairs([["Item", "Value"], ["Motor", "75 kW"]]) == [("Item", "Value"), ("Motor", "75 kW")]


# ---- the helpers

def test_is_table_unit_reads_the_shared_vocabulary():
    assert all(datasheets.is_table_unit(u) for u in ("kW", "m3/h", "barg", "%", "°C", "rpm"))
    assert not any(datasheets.is_table_unit(u) for u in ("-", "", "HART", "IP55", "Class 600"))


# ---- geometry side (rows as the geometry reader hands them over)

def _row(table, row, column, text, label, unit_label="x"):
    return {"source": "table", "table_id": table, "row": row, "column": column,
            "value_text": text, "column_label": label}


def test_geometry_finds_a_unit_column_by_header_and_by_body():
    rows = [_row("t", 1, 1, "kW", "Units"), _row("t", 1, 2, "75", "Value"),
            _row("t", 2, 1, "V", "Units"), _row("t", 2, 2, "400", "Value"),
            _row("u", 1, 1, "bar", "Measure"), _row("u", 1, 2, "40", "Figure"),
            _row("u", 2, 1, "V", "Measure"), _row("u", 2, 2, "24", "Figure"),
            _row("w", 1, 1, "F", "Class"), _row("w", 2, 1, "A", "Class")]
    assert datasheets.geometry_unit_columns(rows) == {("t", 1), ("u", 1)}
    assert datasheets.geometry_single_value_tables(
        rows, datasheets.geometry_unit_columns(rows)) == {"t", "u"}


def test_a_table_with_two_value_columns_keeps_its_glued_header():
    rows = [_row("t", 1, 1, "kW", "Unit"), _row("t", 1, 2, "75", "Required"),
            _row("t", 1, 3, "80", "Offered")]
    cols = datasheets.geometry_unit_columns(rows)
    assert datasheets.geometry_single_value_tables(rows, cols) == set()


# ---- end to end: the made-up grid datasheets through the production path

BENCH = bench.BENCH


@pytest.fixture(autouse=True)
def switches_off(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")


def test_the_unit_grid_reads_right_values_with_no_glued_label():
    key = bench.load_key()
    for name in ("ds05_motor_units_grid.pdf", "ds06_transmitter_odd_headers.pdf"):
        reading = bench.read_file_with("rules", BENCH / name)
        score = bench.score_file(key["files"][name], reading["facts"])
        assert score["wrong_value"] == 0, (name, score["errors"])
        assert score["extra"] == 0, (name, score["errors"])
        assert score["found"] >= score["expected"] - 0, (name, score["missed"])


# ============================================ 2. the AI gate and blanks

PAGE = """PUMP DATASHEET
Design pressure | By Vendor
Set pressure | 340 psig
Rated flow | TBD
Casing | -
Motor power | to be confirmed
Seal plan | As per vendor
Noise | N/A
"""


def _gate(*facts):
    return cd.accept([{"field": f, "value": v, "unit": u, "quote": q, "kind": "offered"}
                      for f, v, u, q in facts], PAGE)


BLANKS = [("Design pressure", "By Vendor", "Design pressure | By Vendor"),
          ("Rated flow", "TBD", "Rated flow | TBD"),
          ("Casing", "-", "Casing | -"),
          ("Motor power", "to be confirmed", "Motor power | to be confirmed"),
          ("Seal plan", "As per vendor", "Seal plan | As per vendor")]


@pytest.mark.parametrize("field,value,quote", BLANKS)
def test_the_gate_refuses_a_blank_marker_whatever_the_model_says(field, value, quote):
    out = _gate((field, value, None, quote))
    assert out["accepted"] == []
    assert out["counts"] == {cd.Reason.VALUE_IS_BLANK_MARKER.value: 1}


def test_the_gate_still_keeps_a_real_value_beside_the_blanks():
    out = _gate(("Design pressure", "By Vendor", None, "Design pressure | By Vendor"),
                ("Set pressure", "340", "psig", "Set pressure | 340 psig"))
    assert [p["field"] for p in out["accepted"]] == ["Set pressure"]


def test_a_marker_written_with_a_unit_is_still_refused():
    out = _gate(("Design pressure", "By Vendor", "barg", "Design pressure | By Vendor"))
    assert out["counts"] == {cd.Reason.VALUE_IS_BLANK_MARKER.value: 1}


def test_na_stays_an_answer_as_the_project_one_list_says():
    out = _gate(("Noise", "N/A", None, "Noise | N/A"))
    assert len(out["accepted"]) == 1


def test_the_gate_reads_the_one_marker_list():
    assert blank_markers.classify("as per vendor")[0]
    assert blank_markers.classify("By others")[0]
    assert not blank_markers.classify("as per API 610")[0]


def test_the_ai_only_bench_reader_no_longer_reports_blank_cells(monkeypatch):
    key = bench.load_key()
    name = "ds14_blanks_by_vendor.pdf"
    entry = key["files"][name]
    # a model that reports every row of the page, blanks included, with a
    # quote copied from the page text it was handed
    def greedy(prompt):
        page = bench._prompt_page_text(prompt)
        facts = []
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()][5:-2]
        for label, value in zip(lines[0::2], lines[1::2]):
            facts.append({"field": label, "value": value, "unit": None,
                          "quote": f"{label}\n{value}", "kind": "offered"})
        return json.dumps({"facts": facts})
    greedy.engine = "fake"
    reading = bench.read_file_with("ai-only:ollama", BENCH / name, model_call=greedy)
    assert reading["status"] == "read"
    score = bench.score_file(entry, reading["facts"])
    assert score["forbidden"] == 0, score["errors"]
    assert reading["rejected"].get(cd.Reason.VALUE_IS_BLANK_MARKER.value, 0) >= 1
