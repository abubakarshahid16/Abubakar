"""Document-reading defects from the 2026-09-30 audit (reading findings 1-6).

1. A ruled table on a page rotated 90/270 was discarded (the table box came
   back in display coordinates, the text lines in unrotated ones).
2. An UNRULED data sheet - label and value on alternate lines - was read as
   clause headings: "2" (a value) above "Impeller diameter (mm)" became
   clause 2, and the rows after it were dropped as a no_clause fragment.
3. Any page where 40% of lines end in a number was a contents page, so a
   tab-aligned data sheet ("Rated flow (m3/h) 250") was excluded.
4. A two-page standard's page header was never a running line, so a chunk
   swallowed it and two issues "conflicted" on "Issue 2 Page".
5. The quality gate knew no rpm, kW, kV, m3/h, Hz or psig, and dropped a line
   of equipment tags as debris.
6. OCR merge read a two-column page across the gutter, split a visual row at
   a 6-pixel bucket edge, and compared every line with every line.

Synthetic PDFs and text only. Mutations M1540-M1553
(scripts/mutations/audit_reading.py).
"""

from __future__ import annotations

import json

import pymupdf
import pytest

from app import chunker as ch
from app import ocr
from app.extract import extract_batch
from app.quality import assess

# ----------------------------------------------------------- 1. rotation


def _ruled_table_pdf(path, rotation: int) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Table 1 Design data", fontsize=10)
    for r in range(6):
        for c in range(4):
            rect = pymupdf.Rect(72 + c * 110, 80 + r * 20, 72 + (c + 1) * 110, 100 + r * 20)
            page.draw_rect(rect, color=(0, 0, 0), width=0.5)
            page.insert_text((rect.x0 + 3, rect.y1 - 6), f"R{r}C{c} 12.5", fontsize=8)
    if rotation:
        page.set_rotation(rotation)
    doc.save(str(path))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_page_keeps_its_ruled_table_in_text_order(tmp_path, rotation):
    """Before the fix: 1 table at rotation 0, 0 tables at 90 and 270. The rows
    must read as the TEXT reads them (row R0 first, cells C0..C3), not as the
    rotated display shows them (columns as rows)."""
    path = tmp_path / f"rot{rotation}.pdf"
    _ruled_table_pdf(path, rotation)
    (_pno, text, *_rest, tables_json) = extract_batch(str(path), 1, 1)[0]
    assert tables_json, f"table lost at rotation {rotation}"
    (table,) = json.loads(tables_json)["tables"]
    assert table["rows"][0] == ["R0C0 12.5", "R0C1 12.5", "R0C2 12.5", "R0C3 12.5"]
    assert table["rows"][5][3] == "R5C3 12.5"
    lines = text.split("\n")
    assert {lines[i] for i in table["lines"]} == {f"R{r}C{c} 12.5"
                                                  for r in range(6) for c in range(4)}


# ------------------------------------------------- 2. unruled data sheet

_PUMP_ROWS = [
    ("Rated flow (m3/h)", "250"), ("Differential head (m)", "85"),
    ("NPSH available (m)", "6"), ("Design pressure (barg)", "15"),
    ("Design temperature (C)", "120"), ("Speed (rpm)", "2980"),
    ("Number of stages", "2"), ("Impeller diameter (mm)", "310"),
    ("Motor rating (kW)", "75"), ("Casing material", "A216 WCB"),
]


def _unruled_sheet_text(tmp_path) -> str:
    """The sheet as extraction really reads it: one cell per line."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "CENTRIFUGAL PUMP DATA SHEET", fontsize=11)
    for r, (label, value) in enumerate(_PUMP_ROWS):
        page.insert_text((75, 95 + r * 20), label, fontsize=9)
        page.insert_text((185, 95 + r * 20), value, fontsize=9)
    doc.save(str(tmp_path / "ds.pdf"))
    with pymupdf.open(str(tmp_path / "ds.pdf")) as d:
        return d[0].get_text("text")


def test_unruled_data_sheet_is_rows_not_clauses(tmp_path):
    text = _unruled_sheet_text(tmp_path)
    assert "Number of stages\n2\nImpeller diameter (mm)" in text   # the trap
    blocks, _ = ch.segment_document([(1, text)], running=set())
    # no value became a clause number
    assert all(b.section is None for b in blocks), [b.section for b in blocks]
    (table,) = [b for b in blocks if b.kind == "table"]
    assert table.lead == ["CENTRIFUGAL PUMP DATA SHEET"]
    assert table.rows == [f"| {label} | {value} |" for label, value in _PUMP_ROWS]
    # every row reaches search: the block passes the quality gate as a table
    assert assess(table.text, "table")["ok"]


def test_a_stack_of_split_line_headings_is_not_a_data_sheet():
    """Titles alternating with increasing clause numbers are headings with
    nothing under them, not label/value rows."""
    lines = ["1", "Scope", "2", "References", "3", "Definitions",
             "4", "General", "5", "Design"]
    assert ch._field_run(lines, 1) == ([], 0)


# -------------------------------------------------- 3. contents evidence

_TAB_SHEET = "\n".join(["CENTRIFUGAL PUMP DATA SHEET"]
                       + [f"{label} {value}" for label, value in _PUMP_ROWS])


@pytest.mark.parametrize("page_no,total", [(1, 3), (2, 3), (40, 120)])
def test_tab_aligned_data_sheet_is_not_a_contents_page(page_no, total):
    assert ch.classify_page(_TAB_SHEET, page_no, total) == "prose"


def test_dot_leaders_are_contents_evidence_even_for_an_excerpt():
    """An excerpt of a book: its contents page cites page numbers the PDF
    does not have, but the dot leaders still say what the page is."""
    toc = "\n".join(["Contents"] + [f"5.{i} Section title {i} ........ {240 + 5 * i}"
                                    for i in range(1, 8)])
    assert ch.classify_page(toc, page_no=2, total_pages=12) == "toc"


# ------------------------------------------ 4. short-document running lines

def _two_page_standard(issue: str) -> list[tuple[int, str]]:
    head = f"SAES-X-901   Process Piping Design   {issue}   Page {{}} of 2"
    return [
        (1, "\n".join([head.format(1), "SAES-X-901", "Process Piping Design",
                       "1 Scope",
                       "1.1 This standard specifies minimum requirements for carbon steel",
                       "process piping in hydrocarbon and utility services.",
                       "3.4 Corrosion allowance",
                       "The corrosion allowance for carbon steel piping in sour service",
                       "shall be 3 mm."])),
        (2, "\n".join([head.format(2), "4 Hydrostatic Testing",
                       "4.1 The test pressure shall be held for a minimum of 30 minutes",
                       "and the test medium shall be fresh water."])),
    ]


def test_two_page_standard_header_is_a_running_line():
    pages = _two_page_standard("Issue 2")
    running = ch.detect_running_lines(pages)
    blocks, removed = ch.segment_document(pages, running)
    assert removed == 2
    assert not any("Issue 2" in b.text for b in blocks)


def test_short_document_keeps_a_repeated_line_without_a_page_number():
    """A line repeated at the top of both pages whose numbers do not move
    with the page is content, not furniture."""
    pages = [(1, "Design pressure 15 barg\nbody one"),
             (2, "Design pressure 20 barg\nbody two")]
    assert ch.detect_running_lines(pages) == set()


# ------------------------------------------------------- 5. quality gate

def test_rotating_equipment_units_are_measured_values():
    verdict = assess("Speed 2980 rpm Power 75 kW Voltage 6.6 kV Frequency 60 Hz "
                     "Flow 250 m3/h")
    assert verdict["ok"] and verdict["kind"] == "data"


def test_a_line_of_equipment_tags_is_kept():
    """Decided: kept - a tag is what an engineer searches for (see
    quality.tag_list)."""
    verdict = assess("P-101A P-101B P-102A P-102B E-201 E-202 V-301 V-302 T-401 K-501")
    assert verdict["ok"] and verdict["kind"] == "tags"
    # symbol debris still fails
    assert not assess("~~ ## || ^^ %% @@ ~~ ## || ^^ %% @@")["ok"]


# ----------------------------------------------------------- 6. OCR merge

_LEFT = [f"Left column line {i} carries running text about coating" for i in range(4)]
_RIGHT = [f"Right column line {i} carries running text about welding" for i in range(4)]


def test_two_column_page_is_read_one_column_after_the_other():
    native = ([(100 + 20 * i, 50, t) for i, t in enumerate(_LEFT)]
              + [(100 + 20 * i, 400, t) for i, t in enumerate(_RIGHT)])
    merged, added = ocr.merge_page_text(native, [(20, 50, "APPROVED STAMP REV B")])
    assert added == 1
    assert merged.splitlines() == ["APPROVED STAMP REV B", *_LEFT, *_RIGHT]


def test_a_label_value_sheet_still_reads_row_by_row():
    rows = [("Design pressure", "15 barg"), ("Design temperature", "120 C"),
            ("Rated flow", "250 m3/h"), ("Speed", "2980 rpm")]
    native = ([(100 + 20 * i, 50, a) for i, (a, _) in enumerate(rows)]
              + [(100 + 20 * i, 300, b) for i, (_, b) in enumerate(rows)])
    merged, _ = ocr.merge_page_text(native, [(20, 50, "WITNESS STAMP")])
    assert merged.splitlines()[1:] == [cell for row in rows for cell in row]


def test_one_visual_row_is_not_split_at_a_bucket_edge():
    native = [(100.0, 50.0, "Design pressure"), (100.0, 300.0, "15 barg")]
    merged, _ = ocr.merge_page_text(native, [(99.0, 500.0, "WITNESS")])
    assert merged.splitlines() == ["Design pressure", "15 barg", "WITNESS"]


def test_merge_compares_a_recognised_line_only_with_lines_near_it(monkeypatch):
    """150 x 150 lines used to be 22,500 full ratio() calls (2.2 s)."""
    import random

    calls = [0]

    class Counting(ocr.SequenceMatcher):
        def ratio(self):
            calls[0] += 1
            return super().ratio()

    monkeypatch.setattr(ocr, "SequenceMatcher", Counting)
    rng = random.Random(1)
    words = "pressure temperature flange gasket bolt nozzle vessel shell head design test".split()

    def line():
        return " ".join(rng.choice(words) for _ in range(8)) + f" {rng.randint(1, 999)}"

    native = [(i * 40.0, 50.0, line()) for i in range(150)]
    recognised = [(i * 40.0 + 3, 52.0, line()) for i in range(150)]
    ocr.merge_page_text(native, recognised)
    assert calls[0] <= 2 * len(recognised)
    # ...and a misreading next to its line is still recognised as one
    merged, added = ocr.merge_page_text(
        [(100.0, 50.0, "DCC RECEIVED 2026-09-01 Code A - Approved")],
        [(101.0, 52.0, "DCC RECEIVED 2O26-09-01 Code A - Approved")])
    assert added == 0
