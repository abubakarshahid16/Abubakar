"""Piece G: the measured score of a paper kind (invented numbers only; the real file holds placeholders until the lead fills it)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import aim_review_measured as M

TABLE = {
    "out_of": 10,
    "target": 7.0,
    "kinds": {
        "datasheet": {
            "label": "datasheet",
            "found_mean": 5.7,
            "old_engine_mean": 1.5,
            "equipment_types": {
                "pump": {"label": "pump datasheet", "found_mean": 8.0},
                "vessel": {"label": "vessel datasheet", "found_mean": None},
            },
        },
        "contract": {"label": "contract document", "found_mean": 7.0},
        "study": {"label": "study", "found_mean": None},
        "procedure": {"label": "procedure", "found_mean": 11},  # not a score out of 10
    },
}


@pytest.fixture(autouse=True)
def table(monkeypatch):
    M._table.cache_clear()
    monkeypatch.setattr(M, "_table", lambda: TABLE)
    yield


def test_below_target_says_so_with_the_denominator_and_the_old_engine():
    got = M.for_run({"kind": "datasheet", "equipment_type": "valve"})
    assert (
        got["verdict"] == "below target"
        and got["found"] == 5.7
        and got["target"] == 7.0
    )
    assert got["sentence"] == (
        "Measured on planted test copies of this kind: 5.7 of 10 mistakes found (target 7): below target."
        " The earlier version found 1.5 of 10."
    )


def test_at_target_is_at_or_above_and_the_equal_value_counts():
    assert M.for_run({"kind": "contract"})["verdict"] == "at or above target"


def test_an_equipment_type_with_its_own_number_wins_over_the_kind():
    got = M.for_run({"kind": "datasheet", "equipment_type": "Pump"})
    assert (
        got["kind_label"] == "pump datasheet"
        and got["found"] == 8.0
        and got["verdict"] == "at or above target"
    )


def test_an_equipment_type_without_a_number_falls_back_to_the_kind_row():
    assert M.for_run({"kind": "datasheet", "equipment_type": "vessel"})["found"] == 5.7


def test_a_placeholder_is_not_measured_and_shows_no_score():
    got = M.for_run({"kind": "study"})
    assert got == {
        "kind_label": "study",
        "found": None,
        "target": 7.0,
        "verdict": "not measured",
        "sentence": "This kind has not been measured on test copies yet.",
    }


def test_an_unknown_kind_is_not_measured_and_an_absent_kind_is_nothing():
    assert M.for_run({"kind": "drawing"})["verdict"] == "not measured"
    assert M.for_run({"kind": ""}) is None
    assert M.for_run({"kind": None}) is None
    assert M.for_run(None) is None


def test_a_number_outside_zero_to_ten_is_not_a_score():
    assert M.for_run({"kind": "procedure"})["verdict"] == "not measured"
    assert (
        M._number(True, 10) is None
        and M._number("7", 10) is None
        and M._number(-1, 10) is None
    )


def test_kind_words_match_with_underscores_and_case():
    assert M.for_run({"kind": "DATA_SHEET"})["verdict"] == "not measured"
    assert M.for_run({"kind": "Contract"})["found"] == 7.0


def test_an_unreadable_table_says_not_measured_never_a_score(monkeypatch):
    monkeypatch.setattr(M, "_table", lambda: {})
    got = M.for_run({"kind": "datasheet"})
    assert got["verdict"] == "not measured" and got["found"] is None


def test_the_shipped_file_is_valid_and_every_row_is_a_placeholder_or_a_real_score():
    data = json.loads(Path(M.TABLE_PATH).read_text(encoding="utf-8"))
    rows = list(data["kinds"].values())
    rows += [
        r
        for k in data["kinds"].values()
        for r in (k.get("equipment_types") or {}).values()
    ]
    assert rows and data["target"] == 7.0 and data["out_of"] == 10
    for row in rows:
        mean = row["found_mean"]
        assert mean is None or 0 <= mean <= 10
        if mean is not None:  # a real number needs its evidence fields
            assert row["copies"] and row["measured_on"] and row["code_head"]


def test_the_real_loader_reads_the_shipped_file(monkeypatch):
    monkeypatch.undo()
    M._table.cache_clear()
    got = M.for_run({"kind": "datasheet", "equipment_type": "pump"})
    assert got["verdict"] in M.VERDICTS and got["target"] == 7.0
    M._table.cache_clear()
