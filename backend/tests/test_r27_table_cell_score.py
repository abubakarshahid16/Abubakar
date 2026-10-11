"""R27 step 1 (#504): a cell-level score for the layout reader, on the invented
datasheets (`scripts/table_cell_score.py`; key cells written by
`scripts/make_datasheet_bench.py`).

Before this, nothing measured whether the layout tool finds a table's cells
with the right text in the right box - only whether a field came out the far
end. The two-tool reader hands each cell to a second reader, so this number
is its starting line. Invented data only.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pymupdf
import pytest

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "backend" / "tests" / "fixtures" / "synthetic" / "datasheets"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "table_cell_score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load("table_cell_score_under_test")
KEY = json.loads((DATA / "answer_key.json").read_text(encoding="utf-8"))["files"]


def _cell(text, box, page=1):
    return {"page": page, "text": text, "box": list(box)}


# ---------------------------------------------------------------- the key is honest

def test_every_keyed_cell_prints_its_text_inside_its_box():
    """A key that does not match the pages would score the reader against
    nothing. Every keyed cell's words are on its page, inside its box."""
    checked = 0
    for name, entry in KEY.items():
        for cell in entry.get("cells") or []:
            with pymupdf.open(str(DATA / name)) as doc:
                inside = doc[cell["page"] - 1].get_text("text", clip=pymupdf.Rect(*cell["box"]))
            assert score._fold(cell["text"]) in score._fold(inside), (name, cell["text"])
            checked += 1
    assert checked == sum(len(e.get("cells") or []) for e in KEY.values()) and checked > 100


def test_a_file_whose_boxes_are_not_the_pages_has_no_cell_key_and_a_reason():
    for name in ("ds09_rotated_page.pdf", "ds11_flowmeter_scanned.pdf"):
        assert KEY[name]["cells"] is None and KEY[name]["cells_not_keyed"]
    out = score.score_all()
    assert "ds09_rotated_page.pdf" in out["not_scored"] and "ds09_rotated_page.pdf" not in out["files"]
    # every file of the key is either scored or named with why it is not
    assert set(out["files"]) | set(out["not_scored"]) == set(KEY)


# ---------------------------------------------------------------- the four outcomes

def test_right_wrong_header_missed_and_extra_are_told_apart():
    truth = [_cell("Design pressure", (0, 0, 100, 20)), _cell("19 barg", (100, 0, 200, 20)),
             _cell("Design temperature", (0, 20, 100, 40)), _cell("120 C", (100, 20, 200, 40)),
             _cell("Parameter", (0, 40, 100, 60))]
    read = [_cell("design  PRESSURE", (1, 1, 99, 19)),        # right: case and spacing are not a difference
            _cell("91 barg", (101, 1, 199, 19)),               # wrong: in the box, another text
            _cell("stray", (300, 300, 340, 320))]              # extra: in no drawn box
    out = score.score_cells(truth, read, {1: ["Parameter"]})
    assert (out["right"], out["wrong"], out["header"], out["missed"], out["extra"]) == (1, 1, 1, 2, 1)
    assert out["cells"] == 5
    assert [d["outcome"] for d in out["detail"]] == ["right", "wrong", "missed", "missed", "header"]


def test_a_cell_read_on_another_page_or_with_no_box_counts_for_nothing():
    truth = [_cell("19 barg", (100, 0, 200, 20), page=1)]
    assert score.score_cells(truth, [_cell("19 barg", (100, 0, 200, 20), page=2)])["missed"] == 1
    assert score.score_cells(truth, [{"page": 1, "text": "19 barg", "box": None}])["missed"] == 1


def test_a_reader_that_reads_nothing_scores_nothing_right():
    """The score is not vacuous: delete the reader and every cell is missed."""
    out = score.score_all(reader=lambda path: ([], {}))
    assert out["total"]["right"] == 0 and out["total"]["missed"] == out["total"]["cells"] > 100


# ---------------------------------------------------------------- the layout reader today

def test_the_layout_readers_cell_score_does_not_fall():
    """#504's acceptance line: the cell-level score is recorded and does not
    fall below the current one. Measured 2026-10-11 on main: 135 of 162 keyed
    cells right in 7 invented files, 0 read wrong, 16 taken as column headers
    (several were first DATA rows of a two-column table), 11 missed. With
    label/value tables read as headerless (`test_r27_label_value_tables.py`):
    150 right, 6 real header cells, 6 missed. With the header stopping at the
    first row that already answers: 153 right, 9 header cells (the three
    real header rows of three files, three cells each) and NOTHING missed -
    every keyed cell is either read right or is a genuine header. Raise the
    floor when the reader improves; never lower it without saying why."""
    total = score.score_all()["total"]
    assert total["cells"] == 162
    assert total["wrong"] == 0, "a cell was read with the wrong text"
    assert total["right"] >= 153, f"the layout reader's cell score fell: {total}"
    assert total["header"] <= 9, f"a data row was taken as a header again: {total}"
    assert total["missed"] == 0, f"a cell is no longer found: {total}"
    assert total["extra"] == 0


@pytest.mark.parametrize("name", [n for n, e in KEY.items() if e.get("cells")])
def test_each_keyed_file_accounts_for_every_cell(name):
    out = score.score_all()["files"][name]
    assert out["right"] + out["wrong"] + out["header"] + out["missed"] == out["cells"] == len(KEY[name]["cells"])
