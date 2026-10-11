"""R27 (#504): a "Label : value" line is read wherever it stands.

A self-contained line was read only inside a text block of several lines; a
one-line block was left to the geometry reader, which is off by default. A
sheet printed one field per line, each line its own block, read nothing: 0 of
10 fields on the invented unruled sheet. Invented data only.
"""
from __future__ import annotations

from pathlib import Path

from app import datasheets
from tools import datasheet_offline

DATA = Path(__file__).parent / "fixtures" / "synthetic" / "datasheets"


def _blocks(*lines):
    """One text block per line, top to bottom (y, x, text)."""
    return [(100.0 + 16 * i, 50.0, line + "\n") for i, line in enumerate(lines)]


def test_a_line_that_is_its_own_pair_is_read_in_a_block_of_its_own():
    pairs = datasheets.pairs_from_blocks(_blocks("Set pressure : 12.5 barg", "Valve type : Conventional"))
    assert pairs == [("Set pressure", "12.5 barg"), ("Valve type", "Conventional")]


def test_a_sentence_with_a_colon_is_not_a_field_and_a_lone_label_pairs_with_nothing():
    long = "Note that the vendor shall confirm every one of the following items before shipment : yes"
    assert datasheets.pairs_from_blocks(_blocks(long)) == []
    assert datasheets.pairs_from_blocks(_blocks("PRESSURE SAFETY VALVE DATASHEET")) == []


def test_the_unruled_sheet_is_read_field_by_field():
    out = datasheet_offline.read_pdf_rules(DATA / "ds02_psv_unruled.pdf")
    facts = {f["field_label"]: f for f in out["facts"]}
    assert (facts["Set pressure"]["raw_value"], facts["Set pressure"]["raw_unit"]) == ("12.5", "barg")
    assert (facts["Required capacity"]["raw_value"], facts["Required capacity"]["raw_unit"]) == ("5400", "kg/h")
    assert len([f for f in out["facts"] if f["raw_value"] and not f["is_blank"]]) >= 7      # the numeric fields
    # the title block is still not a field, and an empty answer is not a value
    assert not {"Project", "Doc No.", "Tag No."} & set(facts)
    bellows = facts.get("Bellows material")
    assert bellows is None or bellows["is_blank"] or not bellows["raw_value"]
