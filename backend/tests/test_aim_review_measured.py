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
        # H3 (reason: the page now says which row it used when the type has none of its own)
        " Row used: the datasheet row for every type; this paper's equipment type is valve, which has no number of its own."
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


# ---------------------------------------------------------------------------------- wired into the page JSON (G-1)
from tests.test_aim_sheet_rule import BOOK, PAPER, client, world  # noqa: E402, F401 - fixture
from tests.test_crs_endpoint import temp_db  # noqa: E402, F401 - fixture


def test_the_page_json_carries_the_measured_sentence_of_the_runs_kind(
    world, monkeypatch
):
    got = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert got["identity"]["kind"]
    assert set(got["measured"]) >= {
        "kind_label",
        "found",
        "target",
        "verdict",
        "sentence",
    }
    assert got["measured"]["verdict"] in M.VERDICTS and got["measured"]["sentence"]


def test_a_score_is_never_rounded_up_and_a_missing_denominator_or_target_is_not_measured(
    monkeypatch,
):
    """Final light check, S2: 6.96 is "6.9 of 10 ... below target", never "7.0"; out_of or target missing or 0: not measured."""
    table = {
        "out_of": 10,
        "target": 7.0,
        "kinds": {"datasheet": {"label": "datasheet", "found_mean": 6.96}},
    }
    monkeypatch.setattr(M, "_table", lambda: table)
    got = M.for_run({"kind": "datasheet"})
    assert (
        got["verdict"] == "below target"
        and "6.9 of 10 mistakes found" in got["sentence"]
        and "7.0" not in got["sentence"]
    )
    for bad in ({"out_of": 0}, {"target": 0}, {"out_of": None}, {"target": None}):
        monkeypatch.setattr(M, "_table", lambda bad=bad: {**table, **bad})
        got = M.for_run({"kind": "datasheet"})
        assert got["verdict"] == "not measured" and got["found"] is None, bad


# ---------------------------------------------------------------------------------- the wrong-comment share (piece H)
WRONG_TABLE = {
    "out_of": 10,
    "target": 7.0,
    "kinds": {
        "study": {"label": "study", "found_mean": 5.0, "false_alarm_wrong": 23, "false_alarm_of": 124},
        "datasheet": {"label": "datasheet", "found_mean": 8.5, "false_alarm_wrong": 4, "false_alarm_of": 71},
        "contract": {"label": "contract document", "found_mean": 5.0, "false_alarm_wrong": None, "false_alarm_of": None},
        "procedure": {"label": "procedure", "found_mean": 5.0, "false_alarm_wrong": 3, "false_alarm_of": None},
        "drawing": {"label": "drawing", "found_mean": 5.0, "false_alarm_wrong": 9, "false_alarm_of": 4},
        "calculation": {"label": "calculation", "found_mean": 5.0, "false_alarm_wrong": 0, "false_alarm_of": 0},
        "specification": {"label": "specification", "found_mean": 5.0, "false_alarm_wrong": True, "false_alarm_of": 10},
    },
}  # fmt: skip


@pytest.fixture
def wrong_table(monkeypatch):
    monkeypatch.setattr(M, "_table", lambda: WRONG_TABLE)


def test_the_wrong_share_is_said_with_its_n_of_m_and_the_target(wrong_table):
    got = M.for_run({"kind": "study"})
    assert got["sentence"].endswith(
        " A strict reader judged 23 of 124 comments wrong across those test copies (19%; target 10% or less)."
    )
    assert got["false_alarm"] == {
        "wrong": 23, "of": 124, "percent": 19, "target_percent": 10, "within_target": False,
        "sentence": "A strict reader judged 23 of 124 comments wrong across those test copies (19%; target 10% or less).",
    }  # fmt: skip


def test_a_share_within_the_target_says_so_in_the_data_and_is_rounded_up(wrong_table):
    got = M.for_run({"kind": "datasheet"})
    assert (
        "4 of 71 comments wrong across those test copies (6%; target 10% or less)"
        in got["sentence"]
    )  # 5.63 shown as 6, never 5
    assert got["false_alarm"]["within_target"] is True


@pytest.mark.parametrize(
    "kind", ["contract", "procedure", "drawing", "calculation", "specification"]
)
def test_no_percentage_without_both_counts(wrong_table, kind):
    """Missing, one-sided, impossible (more wrong than comments), zero comments, or a bool count: no wrong-share words at all."""
    got = M.for_run({"kind": kind})
    assert got["false_alarm"] is None
    assert "strict reader" not in got["sentence"] and "%" not in got["sentence"]


def test_the_exact_ten_percent_is_within_the_target(monkeypatch):
    table = {
        "out_of": 10,
        "target": 7.0,
        "kinds": {
            "study": {"found_mean": 5.0, "false_alarm_wrong": 10, "false_alarm_of": 100}
        },
    }
    monkeypatch.setattr(M, "_table", lambda: table)
    got = M.for_run({"kind": "study"})["false_alarm"]
    assert got["percent"] == 10 and got["within_target"] is True


def test_the_summary_sheet_carries_the_wrong_share_too(world, monkeypatch):
    from tests.test_aim_sheet_rule import _sheet, make_run

    monkeypatch.setattr(
        M,
        "_table",
        lambda: {
            "out_of": 10,
            "target": 7.0,
            "kinds": {
                "datasheet": {
                    "label": "datasheet",
                    "found_mean": 5.0,
                    "false_alarm_wrong": 23,
                    "false_alarm_of": 124,
                }
            },
        },
    )
    make_run("gen_run_wrong", created="2026-11-18T16:00:00Z")
    c = client(PAPER, BOOK)
    wb = _sheet(
        c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_run_wrong")
    )
    cells = [
        r[1]
        for r in wb["Summary"].iter_rows(values_only=True)
        if r and r[0] == "Measured score of this kind"
    ]
    assert (
        cells
        and "A strict reader judged 23 of 124 comments wrong across those test copies (19%; target 10% or less)."
        in cells[0]
    )


# ---------------------------------------------------------------------------------- the row a type is measured on (piece H)
FAMILY_TABLE = {
    "out_of": 10,
    "target": 7.0,
    "kinds": {
        "datasheet": {
            "label": "datasheet",
            "found_mean": None,
            "equipment_types": {
                "pump": {"label": "pump datasheet", "found_mean": 6.5},
                "centrifugal pump": {"label": "centrifugal pump datasheet", "found_mean": 8.0},
                "pressure vessel": {"label": "pressure vessel datasheet", "found_mean": 6.67},
            },
        }
    },
}  # fmt: skip


def test_a_taxonomy_type_is_measured_on_its_family_row_and_says_so(monkeypatch):
    """The identify step names a type from the taxonomy ("dosing_pump"); the table row is the family ("pump"). Not "not measured"."""
    monkeypatch.setattr(M, "_table", lambda: FAMILY_TABLE)
    got = M.for_run({"kind": "datasheet", "equipment_type": "dosing_pump"})
    assert got["found"] == 6.5 and got["verdict"] == "below target"
    assert got["sentence"].endswith(
        " Row used: pump datasheet; this paper's equipment type is dosing pump."
    )


def test_an_exact_type_row_wins_over_the_family_row_and_needs_no_note(monkeypatch):
    monkeypatch.setattr(M, "_table", lambda: FAMILY_TABLE)
    got = M.for_run({"kind": "datasheet", "equipment_type": "centrifugal_pump"})
    assert got["found"] == 8.0 and "Row used" not in got["sentence"]
    got = M.for_run({"kind": "datasheet", "equipment_type": "pressure_vessel"})
    assert got["found"] == 6.67 and "Row used" not in got["sentence"]


def test_a_type_with_no_row_and_a_kind_with_no_number_is_not_measured(monkeypatch):
    monkeypatch.setattr(M, "_table", lambda: FAMILY_TABLE)
    got = M.for_run({"kind": "datasheet", "equipment_type": "gate_valve"})
    assert got["verdict"] == "not measured" and got["found"] is None


def test_a_row_with_its_copies_date_and_version_says_them(monkeypatch):
    """Planner 19 Nov, item 5: an old number says it is old and of how many test copies."""
    table = {
        "out_of": 10,
        "target": 7.0,
        "kinds": {
            "contract": {
                "label": "contract document",
                "found_mean": 6.0,
                "copies": 3,
                "measured_on": "2026-11-18",
                "code_head": "abc1234",
            }
        },
    }
    monkeypatch.setattr(M, "_table", lambda: table)
    got = M.for_run({"kind": "contract"})
    assert got["sentence"].startswith(
        "Measured on 3 planted test copies of this kind (measured 2026-11-18, version abc1234): 6.0 of 10 mistakes found (target 7)"
    )


# ---- the shipped table after the update-6 quick score (the lead's numbers, 26 Nov 2026) --------------------------------------------


@pytest.fixture
def shipped(monkeypatch):
    """The table as the app ships it (the autouse fixture above swaps in a small invented one)."""
    real = json.loads(M.TABLE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(M, "_table", lambda: real)


def _shipped(kind, equipment_type=None):
    return M.for_run({"kind": kind, "equipment_type": equipment_type})


def test_valve_pump_and_vessel_show_their_own_latest_round_with_date_version_and_denominators(shipped):
    for equipment, found, wrong, of in (("relief valve", "8.0", 1, 49), ("pump", "6.0", 3, 54), ("pressure vessel", "5.0", 2, 29)):
        got = _shipped("datasheet", equipment)
        text = got["sentence"]
        assert f"{found} of 10 mistakes found" in text, text
        assert "measured 2026-11-25" in text and "version 99f73a76" in text and "1 planted test copy" in text
        assert f"{wrong} of {of} comments wrong" in text
        assert got["false_alarm"]["wrong"] == wrong and got["false_alarm"]["of"] == of


def test_hazop_and_contract_keep_their_18_nov_numbers_dated_18_nov(shipped):
    for kind in ("study", "contract"):
        text = _shipped(kind)["sentence"]
        assert "measured 2026-11-18" in text and "version 2026" not in text


def test_every_kind_says_the_newest_round_was_cut_short(shipped):
    for kind, equipment in (("datasheet", "relief valve"), ("study", None), ("contract", None)):
        assert _shipped(kind, equipment)["sentence"].endswith("Update 6 round cut short: 3 of 5 kinds measured.")
    assert _shipped("procedure")["sentence"] == "This kind has not been measured on test copies yet."  # a kind with no number says no number
