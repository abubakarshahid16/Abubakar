"""#669 leftover: the "table values not compared" line counts distinct values.

The unchecked share already counts distinct requirements (#678), but the
grouped line and the CRS sentence "N standards-table value(s) were not
compared" summed stored rows, repeats included, and did not say so. Now they
count distinct values and name the stored-row count when repeats exist. A run
stored before this says its number is stored rows. Invented rows only.

Mutations: M6501-M6505 (scripts/mutations/w2b_669_distinct_table_values.py).
"""
from __future__ import annotations

from app import absence, table_gate


def _cell(text, row, page=1, std="std-a"):
    return {"requirement_type": "table_value", "standard_document_id": std, "chunk_id": "c1",
            "page": page, "requirement_text": text, "condition": row, "field": "Max hardness (HRC)"}


REPEATED = [_cell("Grade X - Max hardness (HRC): 22", "Grade X"),
            _cell("Grade X - Max hardness (HRC): 22", "Grade X"),
            _cell("Grade X - Max hardness (HRC): 22", "Grade X"),
            _cell("Grade Y - Max hardness (HRC): 28", "Grade Y")]


def test_the_grouped_line_counts_distinct_values_and_names_the_repeats():
    """THE MUTATION TARGET: 4 stored rows are 2 values."""
    [line] = table_gate.gate(REPEATED, [], standard_names={"std-a": "std-a.pdf"})["not_compared"]
    assert line["count"] == 4 and line["distinct"] == 2
    assert line["line"].startswith("2 table values in 1 table of std-a.pdf not compared")
    assert "4 stored rows, repeats of the same value included" in line["line"]


def test_without_repeats_the_line_is_unchanged():
    [line] = table_gate.gate(REPEATED[2:], [], standard_names={"std-a": "std-a.pdf"})["not_compared"]
    assert line["distinct"] == line["count"] == 2
    assert line["line"] == ("2 table values in 1 table of std-a.pdf not compared: "
                            "no matching field on this submittal")


def test_case_and_spacing_do_not_make_a_new_value():
    rows = [_cell("Grade X - Max hardness (HRC): 22", "Grade X"),
            _cell("grade x -  max hardness (hrc): 22", "Grade X")]
    [line] = table_gate.gate(rows, [])["not_compared"]
    assert line["distinct"] == 1


def _sentence(lines):
    parts = absence.unchecked_parts(run_status="completed",
                                    outcome={"table_values_not_compared": lines})
    return next(p["line"] for p in parts if p["part"] == "table_values_not_compared")


def test_the_crs_sentence_counts_distinct_values():
    text = _sentence([{"count": 4, "distinct": 2}, {"count": 3, "distinct": 3}])
    assert text.startswith("5 standards-table value(s) were not compared")
    assert "7 stored rows, repeats of the same value included" in text


def test_the_crs_sentence_without_repeats_says_nothing_extra():
    text = _sentence([{"count": 3, "distinct": 3}])
    assert text == "3 standards-table value(s) were not compared: no matching field on this submittal."


def test_an_older_run_says_its_number_is_stored_rows():
    text = _sentence([{"count": 42}])
    assert text.startswith("42 standards-table value(s) were not compared")
    assert "stored rows; repeats of the same value not removed" in text
