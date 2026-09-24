"""Issue #179, second pass: the regression documents' layouts, rebuilt as PDFs.

EVERY FIXTURE HERE IS A REAL PDF PAGE, drawn with PyMuPDF to the geometry
measured on the three regression documents - ruled cells, merged cells,
wrapped cells, double spaces inside a cell, a page title in the table's first
row, a title block at the foot of every page - and every test runs
`extract_facts` end to end, so both readers (the ruled-table path and the
text-block path) see the same page, exactly as they do on the real files.

No client content: every label, value, tag and title is invented or generic
(CLAUDE.md rule 3; the pre-commit hook blocks client identifiers).

WHAT WAS MEASURED ON THE REAL DOCUMENTS (disposable DB copy, commit 49b093f):

  * pressure-safety-valve sheet (dual sub-form rows, one valve per page):
    15 "exact duplicate" facts. Checked pair by pair against the PDF, all 15
    are the SAME value printed for a DIFFERENT valve tag on a different page -
    legitimate, and they must stay. The real duplicates were ones the
    (name, value) count could not see: 8 facts that were ONE printed cell read
    twice on the same page, once by each reader, differing only in inner
    whitespace ("0.01cP  By Contractor" vs "0.01cP By Contractor") or cut at a
    line wrap by the text-block reader.
    And "Over pressure % | 21" was lost on every page: 21 is exactly what a
    line number looks like, and the row was compacted before pairing, which
    threw away the column that says it is a value.
  * pressure-vessel sheet (one numbered form with a clause column, a title
    block on every page): the page's own title, carried rightward across
    every column by the spanning-header rule, was appended to field labels
    and to the equipment tag - so the one title-block row the furniture rule
    should have caught had a different label on every page and survived.

Mutations: M404-M409, `python scripts/mutation_check.py --phase 52`.
"""

from __future__ import annotations

import re

import pymupdf
import pytest

from app import datasheets, db, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ds.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _ingest(path, doc_id):
    doc = pymupdf.open(path); pages = len(doc)
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), pages,
             "2026-09-24T00:00:00Z"))
        for page in range(1, pages + 1):
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c{page}", doc_id, f"{doc_id}.pdf", page, page, page,
                 doc[page - 1].get_text(), f"h{doc_id}{page}"))
    doc.close()
    return doc_id


def _ruled_pdf(path, pages, cols, *, row_h=12, top=60, left=30, fontsize=7,
               centre=False):
    """Ruled rows. A cell of None is MERGED into the cell on its left - no
    dividing line - which is how the real sheets draw a value cell that
    spans two grid columns. A cell with a newline wraps onto a second line
    inside the same cell."""
    doc = pymupdf.open()
    for rows in pages:
        page = doc.new_page(width=612, height=792)
        y = top
        for row in rows:
            lines = max(len((c or "").split("\n")) for c in row)
            h = row_h * lines + 4
            x, i = left, 0
            while i < len(row):
                width, j = cols[i], i + 1
                while j < len(row) and row[j] is None:
                    width += cols[j]; j += 1
                page.draw_rect(pymupdf.Rect(x, y, x + width, y + h),
                               color=(0, 0, 0), width=0.5)
                cell_lines = (row[i] or "").split("\n")
                # `centre`: vertically centred, as the vessel sheet draws a
                # one-line cell beside a wrapped one. The valve sheet
                # top-aligns them, which is what puts a wrapped value's
                # first line in the same text block as its label.
                shift = (lines - len(cell_lines)) * row_h / 2 if centre else 0
                for k, line in enumerate(cell_lines):
                    if line:
                        page.insert_text((x + 2, y + 10 + shift + k * row_h), line,
                                         fontsize=fontsize)
                x += width
                i = j
            y += h
    doc.save(str(path)); doc.close()
    return str(path)


def _facts(doc_id):
    datasheets.extract_facts(doc_id, allowed_document_ids=frozenset([doc_id]))
    return datasheets.list_facts(doc_id, allowed_document_ids=frozenset([doc_id]))


# ============================================ the dual sub-form valve sheet
#
# Column widths as measured on the real sheet: row number | label | spacer |
# value | value overflow | row number | label | value. Most values sit in a
# cell merged across the two value columns; a few sit in the second one.
PSV_COLS = [24, 140, 8, 60, 80, 24, 120, 100]


def _psv_page(tag, density="23.55 Kg/m3"):
    return [
        ["P&ID Reference", None, "00-00-001", None, None, "Tag No. " + tag, None, None],
        ["Sl. No", "PROCESS DATA", "", "", "", "Sl. No", "SPRING AND BONNET", ""],
        ["1", "Fluid", "", "Crude Oil/Gas", None, "42", "Bonnet type/ style", "Bolted/ closed"],
        ["3", "Required relieving capacity", "",
         "5 m3/hr By Contractor (based on\nblocked discharge)", None,
         "44", "Inlet center to face", "150 mm"],
        ["10", "Density at relieving temper.", "", "", density, "51", "Cap material", ""],
        ["11", "Viscosity at relieving temper.", "", "", "0.01cP  By Contractor",
         "52", "Gasket material", ""],
        ["15", "Over pressure %", "", "21", None, "56", "Weather hood", ""],
    ]


def _by_name(facts):
    out: dict[str, list[dict]] = {}
    for f in facts:
        out.setdefault(f["field_name"], []).append(f)
    return out


def test_one_printed_cell_read_by_both_readers_is_one_fact(tmp_path):
    """THE DEFECT. The ruled-table reader collapses the cell's whitespace and
    joins its wrapped line; the text-block reader keeps the double space and
    stops at the wrap. Two strings, one printed cell - it was stored twice."""
    doc = _ingest(_ruled_pdf(tmp_path / "psv.pdf", [_psv_page("PSV-0001 A/B")],
                             PSV_COLS), "doc_psv1")
    by_name = _by_name(_facts(doc))

    viscosity = by_name.get("viscosity at relieving temper", [])
    assert len(viscosity) == 1, (
        f"one printed cell became {len(viscosity)} facts: "
        f"{[f['field_value'] for f in viscosity]}")
    capacity = by_name.get("required relieving capacity", [])
    assert len(capacity) == 1, [f["field_value"] for f in capacity]
    # The COMPLETE reading survives, not the one cut at the line wrap.
    assert "blocked discharge" in capacity[0]["field_value"], capacity[0]["field_value"]


def test_the_same_value_for_a_different_valve_on_another_page_is_kept(tmp_path):
    """The 15 "exact duplicates" measured on the real sheet. Two valves with
    the same density are two facts about two valves - deduplicating them
    would delete the second valve's data."""
    doc = _ingest(_ruled_pdf(tmp_path / "psv2.pdf",
                             [_psv_page("PSV-0001 A/B"), _psv_page("PSV-0002 A/B")],
                             PSV_COLS), "doc_psv2")
    density = _by_name(_facts(doc)).get("density at relieving temper", [])
    assert sorted(f["page"] for f in density) == [1, 2], density
    assert {f["equipment_tag"] for f in density} == {"PSV-0001 A/B", "PSV-0002 A/B"}
    assert all(f["raw_value"] == "23.55" for f in density)


def test_a_small_integer_in_the_value_column_is_a_value_not_a_line_number(tmp_path):
    """THE DEFECT. `15 | Over pressure % | 21 | 56 | Weather hood` - the row
    was compacted to its non-empty cells before pairing, so the 21 in the
    VALUE column looked exactly like the next sub-form's line number and was
    discarded. The column it sits in says what it is."""
    doc = _ingest(_ruled_pdf(tmp_path / "psv3.pdf", [_psv_page("PSV-0001 A/B")],
                             PSV_COLS), "doc_psv3")
    over = _by_name(_facts(doc)).get("over pressure", [])
    assert [f["raw_value"] for f in over] == ["21"], over


def test_each_sub_form_keeps_its_own_label_on_a_genuine_dual_column_page(tmp_path):
    """Issue #179 criterion 1, on real page geometry rather than a hand-built
    shape: the right-hand sub-form's value belongs to the right-hand label,
    and no row number survives as a field name."""
    doc = _ingest(_ruled_pdf(tmp_path / "psv4.pdf", [_psv_page("PSV-0001 A/B")],
                             PSV_COLS), "doc_psv4")
    facts = _facts(doc)
    by_name = _by_name(facts)
    inlet = by_name.get("inlet center to face", [])
    assert [(f["raw_value"], f["raw_unit"]) for f in inlet] == [("150", "mm")], inlet
    density = by_name.get("density at relieving temper", [])
    assert [(f["raw_value"], f["raw_unit"]) for f in density] == [("23.55", "Kg/m3")]
    assert not any(re.fullmatch(r"\d{1,3}", f["field_name"]) for f in facts), (
        [f["field_name"] for f in facts])


# ============================================== the numbered vessel form
#
# Row number | clause | description | requirement | unit | notes | - | - | issue
PV_COLS = [22, 50, 150, 70, 40, 60, 60, 40, 40]
TITLE = "GENERIC OPERATOR COMPANY"


def _title_block(sheet, of, rev="00"):
    return [
        ["DATASHEET GENERIC DRUMS", None, None, "DWG TYPE", "PLANT NO", "INDEX",
         "DRAWING NO", "SHT NO", "REV NO"],
        ["TAG No. : V-0001A/B", None, None, "SP", "2003", "D", "DOC-0001",
         str(sheet), ""],
        ["GENERIC ONSHORE FACILITY", None, None, "", "", "", "", "OF", ""],
        [TITLE + "\nCOUNTRY", None, None, "", "", "", "", str(of), rev],
    ]


def _pv_data_page(sheet, rows):
    return ([["Row", TITLE, None, None, None, None, None, None, "Issue"],
             ["2", "GENERAL AND MECHANICAL DATA", None, None, None, None, None, None, ""],
             ["3", "Ref. Clause", "Description", "Purchaser requirement", "Unit",
              "Additional notes", "", "", "00"]]
            + rows + _title_block(sheet, 4))


def _pv_contents_page():
    # A different table shape on the contents page, as measured: the title
    # with only the issue number in the last column beside it, then the
    # title block (whose revision the real page prints elsewhere).
    return ([[TITLE, None, None, None, None, None, None, None, "00"],
             ["Contents", None, None, None, None, None, None, None, ""]]
            + _title_block(1, 4, rev=""))


PV_ROWS_A = [
    ["4", "4.2.1", "Fabricated weight (L1) :", "4410", "kg", "", "", "", ""],
    ["5", "Table 2", "Hydrotest weight (L4) :", "21720", "kg",
     "Field test weight", "", "", ""],
    ["6", "5.7", "Design life :", "25", "years", "", "", "", ""],
]
PV_ROWS_B = [
    ["4", "", "Internal design pressure :", "3.5", "bar", "", "", "", ""],
    ["5", "D.6.1",
     "Supplier qualification for pressure components of austenitic\n"
     "stainless steel duplex vessels :", "not applicable", "", "", "", "", ""],
    ["6", "", "Concrete bearing stress :", "8300", "kPa", "", "", "", ""],
]


def _pv_doc(tmp_path, doc_id):
    pages = [_pv_contents_page(), _pv_data_page(2, PV_ROWS_A),
             _pv_data_page(3, PV_ROWS_B), _pv_data_page(4, PV_ROWS_A[:1])]
    # 6.5 pt text on 8 pt lines, as measured on the real sheet: at that
    # spacing a wrapped label and its value fall into ONE text block.
    return _ingest(_ruled_pdf(tmp_path / f"{doc_id}.pdf", pages, PV_COLS,
                              row_h=8, fontsize=6.5, centre=True), doc_id)


def test_the_page_title_is_never_part_of_a_field_label(tmp_path):
    """THE DEFECT (criterion 2). Row 0 of the data table is the page title
    spanning every column. Carried rightward as a 'spanning header', it was
    appended to every field in the title block - a different label from the
    contents page's, so the title-block row escaped the furniture rule and
    became a fact."""
    doc = _pv_doc(tmp_path, "doc_pv1")
    facts = _facts(doc)
    # Positive first: the form's real fields are read.
    by_name = _by_name(facts)
    assert [(f["raw_value"], f["raw_unit"]) for f in by_name.get("concrete bearing stress", [])] \
        == [("8300", "kPa")], sorted(by_name)
    polluted = [f["field_label"] for f in facts if TITLE.lower() in f["field_label"].lower()]
    assert not polluted, f"the page title leaked into field labels: {polluted}"


def test_the_equipment_tag_is_not_polluted_by_the_page_title(tmp_path):
    """The same carried title was appended to the TAG row's label, so the tag
    read `V-0001A/B - <title>` on some pages and `V-0001A/B` on others: two
    tags for a one-vessel sheet, and the page that stated both got none."""
    doc = _pv_doc(tmp_path, "doc_pv2")
    facts = _facts(doc)
    assert facts
    assert {f["equipment_tag"] for f in facts} == {"V-0001A/B"}, (
        {f["equipment_tag"] for f in facts})


def test_a_clause_number_column_is_not_the_label_and_its_unit_column_is_kept(tmp_path):
    """`6 | 5.7 | Design life : | 25 | years` - the clause reference sits
    where a label would, and the unit has its own column. Compacted and paired
    left to right, '5.7' was the label and the real label its value."""
    doc = _pv_doc(tmp_path, "doc_pv3")
    by_name = _by_name(_facts(doc))
    life = by_name.get("design life", [])
    assert [(f["raw_value"], f["raw_unit"]) for f in life] == [("25", "years")], (
        sorted(by_name))
    weights = by_name.get("hydrotest weight l4", [])
    assert [(f["raw_value"], f["raw_unit"]) for f in weights] == [("21720", "kg")], (
        sorted(by_name))
    pressure = by_name.get("internal design pressure", [])
    assert [(f["raw_value"], f["raw_unit"]) for f in pressure] == [("3.5", "bar")]


def test_an_empty_hold_list_of_dashes_is_not_a_blank_field(tmp_path):
    """NEGATIVE. The vessel sheet's hold list is a ruled grid whose every
    cell is `--`. The row label `--` names nothing; it was stored as a field
    called `--`, blank-marked by its own dashes."""
    pages = [[["HOLD LIST", None, None],
              ["Section", "Description", "Remarks"],
              ["--", "--", "--"],
              ["--", "--", "--"]] + [["Design pressure", "3.5 bar", ""]]]
    doc = _ingest(_ruled_pdf(tmp_path / "hold.pdf", pages, [120, 200, 120]), "doc_hold")
    facts = _facts(doc)
    assert any(f["field_name"] == "design pressure" for f in facts), facts
    dashes = [f for f in facts if not re.search(r"[^\W_]", f["field_label"])]
    assert not dashes, f"a label made of dashes became a field: {dashes}"


# ============================================ the underscore-slot pump sheet
#
# An API-style pump datasheet: no usable grid, a line number at the margin,
# and each printed line carrying SEVERAL fields, each answered on a drawn
# rule of underscores. Positions and the 6.5 pt / 12 pt spacing are the
# real sheet's. The label vocabulary is the public API datasheet form's.

SLOT_LINES = [
    ("42", "PROPOSAL CURVE NO.        _____________*_________"
           "                      RPM          _______*_________",
     "Driver Type                  ___MOTOR___"),
    ("45", "RATED POWER  _______*_______      kW"
           "                                       NPSHR AT RATED FLOW:  ________*_________  m",
     "GEAR          _____NO______"),
    ("8", "Number of Accelerometers                     __________2____________",
     "COOLING WATER PIPING PLAN          __________________"),
    ("7", "PROVISION FOR MTG ONLY                 (6.10.2.10)             __________YES_________",
     ""),
    ("32", "RANGE OF AMBIENT TEMPS :     MIN/MAX"
           "                               __-03__        /       _ 55__  OC", ""),
]


def _slot_form_pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 100
    for serial, left, right in lines:
        page.insert_text((29.2, y), serial, fontsize=6.5)
        page.insert_text((68.3, y), left, fontsize=6.5)
        if right:
            page.insert_text((361.4, y), right, fontsize=6.5)
        y += 12
    doc.save(str(path)); doc.close()
    return str(path)


def test_each_drawn_slot_on_a_line_is_its_own_field(tmp_path):
    """THE DEFECT, the largest single cause of the pump sheet's 2/196: a
    line holding several label + drawn-slot pairs was ONE cell to the
    text-block reader, so its labels never became labels at all."""
    doc = _ingest(_slot_form_pdf(tmp_path / "pump.pdf", SLOT_LINES), "doc_pump1")
    facts = _facts(doc)
    by_name = _by_name(facts)

    # Empty slots are BLANKS - recorded as blank, never as 0.
    for name in ("proposal curve no", "rpm", "rated power", "npshr at rated flow",
                 "cooling water piping plan"):
        found = by_name.get(name, [])
        assert len(found) == 1 and found[0]["is_blank"] == 1, (name, sorted(by_name))
    # Written ON the rule, the answer is the slot's value.
    assert [f["raw_value"] for f in by_name.get("number of accelerometers", [])] == ["2"]
    assert [f["field_value"] for f in by_name.get("gear", [])] == ["NO"]
    provision = [f for f in facts if f["field_label"].startswith("PROVISION FOR MTG ONLY")]
    assert [f["field_value"] for f in provision] == ["YES"], provision


def test_a_slot_whose_field_is_not_named_stays_unknown(tmp_path):
    """NEGATIVE. `RANGE OF AMBIENT TEMPS : MIN/MAX __-03__ / _ 55__ OC`
    names neither slot on its own - which one is MIN is a reading of the
    layout, not of the text. No fact may carry -03 or 55 under ANY label."""
    doc = _ingest(_slot_form_pdf(tmp_path / "pump2.pdf", SLOT_LINES), "doc_pump2")
    facts = _facts(doc)
    assert facts, "the fixture produced no facts at all - this test would be vacuous"
    guessed = [f for f in facts if re.search(r"(?<![\d.])(?:-03|55)(?![\d.])",
                                             f["field_value"] or "")]
    assert not guessed, f"an unnamed slot was filed under a label: {guessed}"
    # An answer written on a rule with no label before it is not itself a
    # label - `YES` must not become a field whose value is the next label.
    line = "__________YES_________      Rated flow   _____5_____"
    assert datasheets.split_label_value(datasheets.split_drawn_slots(line)) == [
        ("Rated flow", "5")]


def test_a_value_with_wide_spacing_but_no_drawn_rule_is_untouched(tmp_path):
    """The slot reader only touches a line that HAS a drawn rule. The valve
    sheet writes `220ÂºC    By Contractor /Vendor` - wide gaps, no rule - and
    that is one cell, a blank-marked value, not two."""
    assert datasheets.split_drawn_slots("220ÂºC    By Contractor /Vendor") == [
        "220ÂºC    By Contractor /Vendor"]
    # And `rpm` is a unit, but `RPM ___*___` is a field: a unit never has
    # a drawn slot of its own.
    line = "RATED POWER  ___*___   kW      RPM  ___*___"
    assert datasheets.split_label_value(datasheets.split_drawn_slots(line)) == [
        ("RATED POWER", "___*___"), ("RPM", "___*___")]


def test_a_merged_strip_of_line_numbers_is_not_a_label():
    """NEGATIVE. The pump sheet's table finder merged a whole column of line
    numbers into one cell, beside a cell of free text that happens to say
    "by the manufacturer" - which reads as a blank marker. A strip of
    numbers names no field."""
    shape = [["SECTION", "NOTE", "REMARK"],
             ["1 2 3 4 5 6 7 8", "REFERENCES MUST BE LISTED BY THE MANUFACTURER", ""]]
    pairs = datasheets.pairs_from_table_shape(shape)
    assert not any(label.startswith("1 2 3") for label, _ in pairs), pairs


def test_a_wrapped_label_behind_a_clause_number_stays_unknown(tmp_path):
    """NEGATIVE. The label wraps onto a second line and a lettered clause
    reference precedes it. The honest answer is no fact - never the value
    filed under the label's second line, which names nothing."""
    doc = _pv_doc(tmp_path, "doc_pv4")
    facts = _facts(doc)
    assert facts, "the fixture produced no facts at all - this test would be vacuous"
    wrong = [f for f in facts if f["field_label"].lower().startswith("stainless steel")]
    assert not wrong, f"a value was filed under a label fragment: {wrong}"
