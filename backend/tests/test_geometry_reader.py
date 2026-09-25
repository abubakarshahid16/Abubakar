"""Geometry reader (#193 section 5.1): tables and forms from PDF positions.

Two kinds of test.

* SYNTHETIC - tiny PDFs drawn in the test with PyMuPDF (ruled lines and
  inserted text). They run everywhere and carry the mutation proofs
  (M550-M553 in scripts/mutation_check.py): parent-label propagation, title-row
  dropping, underscore fields read as blank, unit splitting.
* REAL COPY - three submittal pages kept OUTSIDE the repository on the owner's
  machine (default folder below, override with GEOMETRY_BENCH_DIR). Client
  documents never enter git, so these tests read the copies at runtime and
  SKIP with the reason when the copies are absent - which is the case in CI.
  Their assertions use generic engineering facts only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from app import geometry_reader as gr  # noqa: E402

# --------------------------------------------------------------------------
# Synthetic builders
# --------------------------------------------------------------------------

#: Column edges of the synthetic nozzle-style table: Mark, Size, three
#: children under one parent, Service.
XS = [50, 110, 170, 250, 330, 410, 520]
#: Row edges: title, header A, header B, data, data, EMPTY, data.
YS = [60, 80, 100, 120, 140, 160, 180, 200]
TITLE = "Equipment connection schedule"


def _hline(page, y, x0, x1):
    page.draw_line((x0, y), (x1, y), width=0.6)


def _vline(page, x, y0, y1):
    page.draw_line((x, y0), (x, y1), width=0.6)


def _text(page, x, y, text, size=8):
    page.insert_text((x + 3, y + 13), text, fontsize=size)


def _table_page():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    left, right = XS[0], XS[-1]
    # Outer frame and every row rule, except the one between header A and
    # header B where Mark, Size and Service span both header rows.
    for y in (YS[0], YS[1], YS[3], YS[4], YS[5], YS[6], YS[7]):
        _hline(page, y, left, right)
    _hline(page, YS[2], XS[2], XS[5])  # only under the parent cell
    _vline(page, left, YS[0], YS[-1])
    _vline(page, right, YS[0], YS[-1])
    # Title row: one cell across the full width (no inner verticals).
    for x in XS[1:-1]:
        top = YS[1]
        if x in (XS[3], XS[4]):
            top = YS[2]  # parent cell spans the three child columns in header A
        _vline(page, x, top, YS[-1])
    _text(page, left, YS[0], TITLE, size=9)
    _text(page, XS[0], YS[1] + 8, "Mark")
    _text(page, XS[1], YS[1] + 8, "Size")
    _text(page, XS[2] + 60, YS[1], "Parent")
    _text(page, XS[2], YS[2], "Alpha")
    _text(page, XS[3], YS[2], "Beta")
    _text(page, XS[4], YS[2], "Gamma")
    _text(page, XS[5], YS[1] + 8, "Service")
    rows = {3: ["P1", "4", "CL-150", "weld", "RF", "Inlet"],
            4: ["P2", "2", "CL-300", "slip", "FF", "Outlet"],
            6: ["P3", "3", "CL-150", "weld", "RF", "Drain"]}
    for r, values in rows.items():
        for j, v in enumerate(values):
            _text(page, XS[j], YS[r], v)
    return doc, page


def _form_page(lines):
    """`lines` = [(x, y, text)]; each text is inserted at that baseline."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=10)
    return doc, page


def _pair(form, label):
    matches = [p for p in form["pairs"] if p["label"] == label]
    assert len(matches) == 1, (label, [p["label"] for p in form["pairs"]])
    return matches[0]


# --------------------------------------------------------------------------
# Tables (synthetic)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_table():
    doc, page = _table_page()
    result = gr.read_tables(page)
    assert result["tables"], "no table found on the synthetic page"
    yield result, result["tables"][0]
    doc.close()


def test_parent_header_cell_labels_each_child_column(synthetic_table):
    _result, table = synthetic_table
    assert table["labels"] == ["Mark", "Size", "Parent Alpha", "Parent Beta",
                               "Parent Gamma", "Service"]


def test_parent_label_reaches_the_data_cells(synthetic_table):
    _result, table = synthetic_table
    first = {c["label"]: c["text"] for c in table["rows"][0]["cells"]}
    assert first["Parent Alpha"] == "CL-150"
    assert first["Parent Beta"] == "weld"
    assert first["Parent Gamma"] == "RF"


def test_title_row_above_header_is_dropped(synthetic_table):
    _result, table = synthetic_table
    assert table["header_row_count"] == 2
    assert table["title_rows"] == [TITLE]
    everything = [c["text"] for r in table["rows"] for c in r["cells"]] + table["labels"]
    assert not any(TITLE in t for t in everything)


def test_title_row_detection_itself_on_a_full_width_cell(synthetic_table):
    _result, table = synthetic_table
    assert table["rows"][0]["cells"][0]["text"] == "P1"
    assert not any("Equipment" in label for label in table["labels"])


def test_empty_rows_are_dropped(synthetic_table):
    _result, table = synthetic_table
    assert [r["cells"][0]["text"] for r in table["rows"]] == ["P1", "P2", "P3"]
    assert table["dropped_empty_rows"] == 1
    assert all(any(c["text"] for c in r["cells"]) for r in table["rows"])


def test_table_values_keep_their_provenance(synthetic_table):
    result, table = synthetic_table
    cell = table["rows"][0]["cells"][0]
    assert cell["source"] == "table"
    assert cell["page"] == 1 and cell["table_id"] == table["table_id"]
    assert isinstance(cell["row"], int) and isinstance(cell["column"], int)
    assert cell["bbox"] and len(cell["bbox"]) == 4
    assert result["strategy"] in gr.STRATEGIES
    assert result["score"] == result["scores"][result["strategy"]]["score"]


def test_ruled_grid_wins_the_strategy_score(synthetic_table):
    result, _table = synthetic_table
    assert result["strategy"] == "lines"
    assert result["scores"]["lines"]["score"] >= result["scores"]["text"]["score"]


# --------------------------------------------------------------------------
# Forms (synthetic)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_form():
    doc, page = _form_page([
        (50, 100, "DESIGN PRESSURE: 10 barg"),
        (50, 130, "CASE MOUNTING:"),
        (220, 130, "____________"),
        (50, 160, "MATERIAL:"),
        (50, 174, "Carbon steel"),
        (50, 210, "DESIGN TEMPERATURE: 120 C"),
        (50, 240, "SIZE: 4"),
        (50, 270, "GRADE: C"),
        (50, 300, "PUMP TYPE:"), (140, 300, "OH2"),
        (300, 300, "SPEED:"), (360, 300, "2950"),
        (50, 330, "HYDROTEST:"), (140, 330, "________ bar g @ ________ oC"),
    ])
    yield gr.read_form(page)
    doc.close()


def test_form_label_value_and_unit(synthetic_form):
    p = _pair(synthetic_form, "DESIGN PRESSURE")
    assert (p["value"], p["unit"], p["is_blank"]) == ("10", "barg", False)
    assert p["value_text"] == "10 barg"
    assert p["position"] == "right"


def test_underscore_field_is_blank_not_missed(synthetic_form):
    p = _pair(synthetic_form, "CASE MOUNTING")
    assert p["is_blank"] is True
    assert p["value"] is None
    assert not any(u["label"].startswith("CASE MOUNTING")
                   for u in synthetic_form["unpaired_labels"])


def test_blank_field_with_printed_units_keeps_them(synthetic_form):
    p = _pair(synthetic_form, "HYDROTEST")
    assert p["is_blank"] is True and p["value"] is None
    assert p["expected_units"] == ["barg", "degC"]


def test_value_directly_below_the_label(synthetic_form):
    p = _pair(synthetic_form, "MATERIAL")
    assert p["value"] == "Carbon steel"
    assert p["position"] == "below"


def test_right_value_stops_at_the_next_label(synthetic_form):
    assert _pair(synthetic_form, "PUMP TYPE")["value"] == "OH2"
    assert _pair(synthetic_form, "SPEED")["value"] == "2950"


def test_form_unit_after_a_number_c_is_celsius(synthetic_form):
    p = _pair(synthetic_form, "DESIGN TEMPERATURE")
    assert (p["value"], p["unit"]) == ("120", "degC")


def test_form_unit_negative_cases(synthetic_form):
    size = _pair(synthetic_form, "SIZE")
    assert (size["value"], size["unit"]) == ("4", None)
    grade = _pair(synthetic_form, "GRADE")
    assert (grade["value"], grade["unit"]) == ("C", None)


# ---------------------------------------- blank needs evidence (addendum 3.7)

@pytest.fixture(scope="module")
def evidence_form():
    doc, page = _form_page([
        (50, 100, "VISCOSITY:"), (150, 100, "cP"),
        (50, 130, "VAPOUR PRESSURE:"), (170, 130, "bar a (psia)"),
        (50, 160, "HYDRAULIC POWER:"), (170, 160, "* kW"),
        (50, 190, "BOWL:"), (150, 190, "By EPC Contractor"),
        (50, 220, "ELEVATION:"), (150, 220, "5 - 150 M"),
        (50, 250, "SOUND LEVEL:"), (170, 250, "<85 (dBA)"),
        (50, 280, "SPECIFIC GRAVITY:"), (170, 280, "0.974 @ 170 OF"),
        # Two-column form: the far-right run belongs to the RIGHT column; this
        # label's value is on the next line, inside its underscore field.
        (50, 320, "Mounting location"), (360, 320, "______________________"),
        (48, 334, "______BEARING HOUSING______"),
        (50, 370, "SUCTION:"), (140, 370, "_________ bar g"),
    ])
    yield gr.read_form(page)
    doc.close()


def test_a_unit_label_alone_is_neither_value_nor_blank(evidence_form):
    """THE MUTATION TARGET (M554): the printed unit column must not be
    reported as a value, and must not become a false blank."""
    for label in ("VISCOSITY", "VAPOUR PRESSURE"):
        assert not [p for p in evidence_form["pairs"] if p["label"] == label]
    reasons = {u["label"].rstrip(":"): u.get("reason") for u in evidence_form["unpaired_labels"]}
    assert reasons.get("VISCOSITY") == "unit label only"
    assert reasons.get("VAPOUR PRESSURE") == "unit label only"


def test_star_marker_is_a_blank_with_its_unit(evidence_form):
    """THE MUTATION TARGET (M555)."""
    p = _pair(evidence_form, "HYDRAULIC POWER")
    assert (p["is_blank"], p["blank_marker"], p["value"]) == (True, "*", None)
    assert p["expected_units"] == ["kW"]


def test_by_party_marker_is_a_blank(evidence_form):
    p = _pair(evidence_form, "BOWL")
    assert p["is_blank"] and p["blank_marker"] == "By EPC Contractor"


def test_range_bracketed_unit_and_condition(evidence_form):
    assert (_pair(evidence_form, "ELEVATION")["value"], _pair(evidence_form, "ELEVATION")["unit"]) == ("5 - 150", "M")
    # the base-14 test font cannot draw an en dash; the parser is checked directly
    assert gr._parse_form_value("5 – 150 M")["value"] == "5 - 150"
    sound = _pair(evidence_form, "SOUND LEVEL")
    assert (sound["value"], sound["unit"]) == ("<85", "dBA")
    sg = _pair(evidence_form, "SPECIFIC GRAVITY")
    assert (sg["value"], sg["unit"], sg["condition"]) == ("0.974", None, "@ 170 OF")


def test_a_far_empty_run_is_not_this_fields_blank(evidence_form):
    """THE MUTATION TARGET (M556): the real-layout false blank - a two-
    column form's other-column run must not make this field blank."""
    p = _pair(evidence_form, "Mounting location")
    assert p["is_blank"] is False and p["value"] == "BEARING HOUSING" and p["position"] == "below"


def test_an_adjacent_empty_run_is_still_a_blank(evidence_form):
    p = _pair(evidence_form, "SUCTION")
    assert p["is_blank"] is True and p["expected_units"] == ["barg"]


@pytest.mark.parametrize("text", ["C", "A", "in", "YES", "OH2", "10", "T3"])
def test_letters_and_words_are_not_unit_labels(text):
    assert not gr.is_unit_label(text)


def test_form_pairs_keep_both_boxes(synthetic_form):
    p = _pair(synthetic_form, "DESIGN PRESSURE")
    assert p["source"] == "form" and p["page"] == 1
    assert len(p["label_bbox"]) == 4 and len(p["value_bbox"]) == 4
    assert p["value_bbox"][0] >= p["label_bbox"][2] - 1


# --------------------------------------------------------------------------
# Unit splitting
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,value,unit", [
    ("10 barg", "10", "barg"),
    ("10 bar g", "10", "barg"),
    ("3.5 bar (ga)", "3.5", "barg"),
    ("5 bar", "5", "bar"),
    ("250 kPa", "250", "kPa"),
    ("1.2 MPa", "1.2", "MPa"),
    ("150 psig", "150", "psig"),
    ("120 degC", "120", "degC"),
    ("120 °C", "120", "degC"),
    ("-3 C", "-3", "degC"),
    ("3.2 mm", "3.2", "mm"),
    ("2 in", "2", "in"),
    ("4 NPS", "4", "NPS"),
    ("NPS 4", "4", "NPS"),
])
def test_unit_split_cases(text, value, unit):
    got = gr.split_value_unit(text)
    assert (got["value"], got["unit"]) == (value, unit)
    assert got["text"] == text


@pytest.mark.parametrize("text,value", [
    ("10", "10"),          # a number with no unit stays unit=None
    ("C", "C"),            # "C" with no number is not a unit
    ("in", "in"),
    ("CL-150", "CL-150"),
    ("3.2 mm on either side", "3.2 mm on either side"),  # whole-text rule
])
def test_unit_split_negative_cases(text, value):
    got = gr.split_value_unit(text)
    assert got["unit"] is None
    assert got["value"] == value


# --------------------------------------------------------------------------
# Real copies (outside git; skipped when absent)
# --------------------------------------------------------------------------

BENCH = Path(os.environ.get("GEOMETRY_BENCH_DIR", r"C:\project\docling-bench\input"))


def _real_page(name, page_no):
    path = BENCH / name
    if not path.is_file():
        pytest.skip(f"real submittal copy {name} not present at {BENCH} - client "
                    f"documents are kept outside git (set GEOMETRY_BENCH_DIR)")
    doc = pymupdf.open(path)
    return doc, doc[page_no - 1]


# REAL-COPY ASSERTIONS ARE STRUCTURAL COUNTS ONLY (owner addendum 2026-09-25,
# section 1.1). No document text is asserted on or printed: every failure
# message below carries integers only.


def test_real_vessel_nozzle_table_structure():
    doc, page = _real_page("vessel-full.pdf", 6)
    try:
        result = gr.read_tables(page)
    finally:
        doc.close()
    two_row = [t for t in result["tables"] if t["header_row_count"] == 2]
    assert len(two_row) == 1, len(two_row)
    table = two_row[0]
    assert len(table["labels"]) == 8, len(table["labels"])
    # Exactly three labels share one parent word (a parent spanning 3 children).
    firsts = [lab.split(" ")[0] for lab in table["labels"] if " " in lab]
    assert max((firsts.count(f) for f in firsts), default=0) == 3
    assert len(table["rows"]) == 20, len(table["rows"])
    for row in table["rows"]:
        assert len(row["cells"]) == 8, len(row["cells"])
        assert gr._TAG.match(row["cells"][0]["text"]) is not None
    # The column that is the first child of the parent holds one repeated value.
    parent = max(set(firsts), key=firsts.count)
    first_child = next(i for i, lab in enumerate(table["labels"])
                       if lab.startswith(parent + " "))
    values = {r["cells"][first_child]["text"] for r in table["rows"]}
    assert len(values) == 1 and "" not in values, len(values)
    assert len(table["title_rows"]) == 2, len(table["title_rows"])
    data_text = {c["text"] for r in table["rows"] for c in r["cells"] if c["text"]}
    leaks = sum(1 for title in table["title_rows"] for piece in title.split(" | ")
                if gr._has_letter(piece) and piece in data_text)
    assert leaks == 0, leaks


def _numeric_with(pairs, unit):
    return sum(1 for p in pairs if p["unit"] == unit and p["value"]
               and gr._NUMERIC.match(p["value"]))


def test_real_vessel_design_form_counts():
    doc, page = _real_page("vessel-full.pdf", 4)
    try:
        form = gr.read_form(page)
    finally:
        doc.close()
    pairs = form["pairs"]
    assert len(pairs) > 20, len(pairs)
    assert _numeric_with(pairs, "barg") >= 1
    assert _numeric_with(pairs, "degC") >= 1
    assert sum(1 for p in pairs if p["is_blank"]) >= 1


def test_real_pump_form_counts():
    doc, page = _real_page("pump-full.pdf", 3)
    try:
        form = gr.read_form(page)
    finally:
        doc.close()
    pairs = form["pairs"]
    assert len(pairs) > 20, len(pairs)
    blanks = [p for p in pairs if p["is_blank"]]
    assert len(blanks) > 10, len(blanks)
    assert sum(1 for p in blanks if p["value"] is not None) == 0
    assert _numeric_with(pairs, "degC") >= 1


# --------------------------------------------------------------------------
# B4 (#193 5.5): the remaining wrong-value shapes, each with its negative.
# Mutation proofs M580-M585, M592-M594 in scripts/mutation_check.py.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def b4_form():
    doc, page = _form_page([
        # 1a. a value cut after "&": the next line continues it, starting
        #     LEFT of the value (so only the open ending can join it).
        (50, 100, "ITEM NO.:"), (130, 100, "P-101 A/B, P-102 A/B &"), (70, 114, "P-103 A/B"),
        # 1b. a value continued on a line INDENTED wholly under it.
        (50, 150, "REMARK:"), (130, 150, "PROVIDE TWO EARTH BOSSES"), (140, 164, "DIAGONALLY"),
        # 1c. NEGATIVE: finished value, next line starts left of it -> separate.
        (50, 200, "SERVICE:"), (130, 200, "SEA WATER"), (70, 214, "COOLING DUTY"),
        # 1d. NEGATIVE: open ending, but the next line is its own label+value.
        (50, 250, "TAGS:"), (130, 250, "V-1 &"), (50, 264, "NOTE"), (130, 264, "SEE SHEET 2"),
        # 2. answer inside its drawn field, a note printed after the field.
        (50, 310, "HARDNESS REQD"), (200, 310, "_ YES_ <HRC 22"),
        (50, 340, "MIN METAL TEMP"), (200, 340, "_ -3__ OC"),
        # 3. a value that is only a condition, inside a run.
        (50, 370, "INSPECTION AT"), (200, 370, "___@ SHOP__"),
        # 4a. a far drawn run and PLAIN text below: the text is the next row's
        #     label or a heading, never this field's value.
        (50, 420, "N2 PURGE"), (230, 420, "____________"), (50, 434, "SPARE PARTS"),
        # 4b. text below that has its own drawn field under it is a label.
        (50, 490, "COUNT:"), (50, 504, "LOCATION"), (50, 518, "______ROOF______"),
    ])
    yield gr.read_form(page)
    doc.close()


def test_a_value_ending_open_continues_on_the_next_line(b4_form):
    """THE MUTATION TARGET (M580): the '&' ending joins the wrapped line."""
    p = _pair(b4_form, "ITEM NO.")
    assert p["value"] == "P-101 A/B, P-102 A/B & P-103 A/B"
    assert p["value_text"] == "P-101 A/B, P-102 A/B & P-103 A/B"
    assert p["value_bbox"][3] > 110  # the box grew to cover the second line


def test_a_line_indented_under_the_value_continues_it(b4_form):
    """THE MUTATION TARGET (M581)."""
    assert _pair(b4_form, "REMARK")["value"] == "PROVIDE TWO EARTH BOSSES DIAGONALLY"


def test_a_finished_value_does_not_swallow_the_next_line(b4_form):
    assert _pair(b4_form, "SERVICE")["value"] == "SEA WATER"


def test_a_next_line_with_its_own_label_is_not_a_continuation(b4_form):
    """THE MUTATION TARGET (M582): the band must be empty but for the
    continuation - a line holding a label and its value is another field."""
    assert _pair(b4_form, "TAGS")["value"] == "V-1 &"


def test_the_answer_is_what_the_drawn_field_encloses(b4_form):
    """THE MUTATION TARGET (M583): the note after the closing run is not the
    value; it is kept apart as a note."""
    p = _pair(b4_form, "HARDNESS REQD")
    assert (p["value"], p["note"], p["is_blank"]) == ("YES", "<HRC 22", False)


def test_a_unit_after_the_closing_run_is_still_the_unit(b4_form):
    p = _pair(b4_form, "MIN METAL TEMP")
    assert (p["value"], p["unit"], p["note"]) == ("-3", "degC", None)


def test_a_condition_only_value_loses_its_runs(b4_form, evidence_form):
    """THE MUTATION TARGET (M584)."""
    p = _pair(b4_form, "INSPECTION AT")
    assert (p["value"], p["is_blank"]) == ("@ SHOP", False)
    # negative: a number with a condition keeps the number as the value
    sg = _pair(evidence_form, "SPECIFIC GRAVITY")
    assert (sg["value"], sg["condition"]) == ("0.974", "@ 170 OF")


def test_plain_text_under_a_run_form_label_is_not_its_value(b4_form):
    """THE MUTATION TARGET (M585): the heading below is not taken; the field
    is the blank its drawn run says."""
    p = _pair(b4_form, "N2 PURGE")
    assert (p["is_blank"], p["value"], p["position"]) == (True, None, "right")
    assert not any(q["value_text"] == "SPARE PARTS" for q in b4_form["pairs"])


def test_a_label_heading_its_own_field_is_not_a_value(b4_form):
    """THE MUTATION TARGET (M592): LOCATION has its drawn field under it, so
    it is a label - COUNT is left unpaired rather than given it."""
    assert not [p for p in b4_form["pairs"] if p["label"] == "COUNT"]
    assert any(u["label"] == "COUNT:" for u in b4_form["unpaired_labels"])


def _cell_table_page():
    """Mark | Inspection | Rating, ruled; data rows N1 and N2."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    xs, ys = [50, 110, 250, 330], [60, 80, 100, 120]
    for y in ys:
        _hline(page, y, xs[0], xs[-1])
    for x in xs:
        _vline(page, x, ys[0], ys[-1])
    for j, text in enumerate(["Mark", "Inspection", "Rating"]):
        _text(page, xs[j], ys[0], text)
    for j, text in enumerate(["N1", "___@ SHOP__", "*"]):
        _text(page, xs[j], ys[1], text)
    for j, text in enumerate(["N2", "WITNESS", "150"]):
        _text(page, xs[j], ys[2], text)
    return doc, page


def test_table_cells_are_cleaned_like_form_values():
    """THE MUTATION TARGET (M593): runs and blank markers in a table cell
    get the form rules; plain cells are untouched (the negative)."""
    doc, page = _cell_table_page()
    try:
        table = gr.read_tables(page)["tables"][0]
    finally:
        doc.close()
    cells = {(r["cells"][0]["text"], c["label"]): c for r in table["rows"] for c in r["cells"]}
    shop = cells[("N1", "Inspection")]
    assert (shop["value"], shop["is_blank"]) == ("@ SHOP", False)
    star = cells[("N1", "Rating")]
    assert (star["value"], star["is_blank"], star["blank_marker"]) == (None, True, "*")
    assert cells[("N2", "Inspection")]["value"] == "WITNESS"
    assert (cells[("N2", "Rating")]["value"], cells[("N2", "Rating")]["is_blank"]) == ("150", False)


def test_page_rows_drop_a_reading_seen_twice_but_keep_different_answers():
    """THE MUTATION TARGET (M594): same page + label + answer twice is one
    row; the same label with a different answer is kept (the negative)."""
    first = {"page": 1, "label": "SPEED", "label_text": "SPEED:", "value_text": "2950",
             "value": "2950", "unit": None, "is_blank": False, "blank_marker": None,
             "condition": None, "value_bbox": [1, 2, 3, 4], "label_bbox": [0, 2, 1, 4],
             "position": "right"}
    twice = {**first, "label": "Speed", "value_bbox": [5, 6, 7, 8]}
    other = {**first, "value": "3000", "value_text": "3000"}
    rows = gr.read_page_rows(None, form={"pairs": [first, twice, other]},
                             tables={"tables": []})
    assert [(r["label"], r["value"]) for r in rows] == [("SPEED", "2950"), ("SPEED", "3000")]
    assert rows[0]["bbox"] == [1, 2, 3, 4]  # the first reading keeps its box


def test_page_rows_label_table_cells_by_row_key_and_skip_empty_cells(synthetic_table):
    _result, table = synthetic_table
    # one empty cell in a data row: it must not become a row (not found is not blank)
    table = {**table, "rows": [{**table["rows"][0], "cells": [
        {**c, "text": "", "value": None, "is_blank": True} if c["label"] == "Service" else c
        for c in table["rows"][0]["cells"]]}]}
    rows = gr.read_page_rows(None, form={"pairs": []}, tables={"tables": [table]})
    labels = [r["label"] for r in rows]
    assert "P1 Parent Alpha" in labels and "P1 Service" not in labels
    assert not any(r["label"] == "P1 Mark" for r in rows)  # the key cell itself
    cell = next(r for r in rows if r["label"] == "P1 Parent Alpha")
    assert (cell["source"], cell["column_label"], cell["table_id"]) == (
        "table", "Parent Alpha", table["table_id"])
