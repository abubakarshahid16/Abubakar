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
