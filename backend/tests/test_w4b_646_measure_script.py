"""#646: the AI datasheet measuring tool counts honestly and never runs on the
live database. Invented requirements and fields only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import measure_ai_datasheet as m  # noqa: E402

LIMIT = {"id": "r1", "requirement_type": "numeric_limit", "subject": "noise level",
         "raw_value": "90", "raw_unit": "dB(A)"}
OTHER = {"id": "r2", "requirement_type": "numeric_limit", "subject": "flow rate",
         "raw_value": "40", "raw_unit": "m3/h"}
PROSE = {"id": "r3", "requirement_type": "statement", "subject": "documentation",
         "raw_value": None}


def test_an_ai_read_figure_can_pair_and_text_cannot():
    """The number of an AI reading is read by code from its value text; only
    then can the pairing give the requirement a field with a value."""
    figure = m._fact("Noise level", "85 dB(A)", 1, "locate", 0)
    assert figure["raw_value"] == "85"
    words = m._fact("Noise level", "By Contractor", 1, "locate", 1)
    assert words["raw_value"] is None
    assert m._paired([LIMIT], [figure]) == {"paired_with_value:locate": 1}
    assert m._paired([LIMIT], [words]) == {"no_field_paired": 1}


def test_each_requirement_counts_once_in_one_bucket():
    rule = {"id": "f1", "field_name": "noise level", "field_label": "Noise level",
            "raw_value": "95", "raw_unit": "dB(A)", "is_blank": 0}
    blank = {"id": "f2", "field_name": "flow rate", "field_label": "Flow rate",
             "raw_value": None, "is_blank": 1}
    out = m._paired([LIMIT, OTHER, PROSE], [rule, blank])
    assert out == {"paired_with_value:rules": 1, "paired_blank_field": 1,
                   "not_a_value_requirement": 1}
    assert m._paired([LIMIT, OTHER], []) == {"no_field_paired": 2}


def test_it_refuses_a_live_shaped_database_path(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    with pytest.raises(SystemExit, match="refusing"):
        m.main(["--db", str(live), "--model", "any", "--run", "x"])
    assert not live.exists()
