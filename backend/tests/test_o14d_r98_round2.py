"""Order 14 lane D, review R98 round 2. Invented lines only.
(a) the second reader asked whether the paper states the item quotes a starred blank or a phrase deferral: the line stays a
    Query (deferred), never "AI thinks: not met";
(b) a note line whose star stands before a word that is also a unit, and an underscore part number, are no deferral;
(c) each guard of `star_fills_value` is needed by a line of its own, and a cut-off second opinion stops a two-reader candidate."""

from __future__ import annotations

import pytest

from app import agent_review_two_reader as two_reader
from app import agent_review_wording as wording
from app import blank_markers

# ---------------------------------------------------------------- (a) the absence second reader's quote defers the value


@pytest.mark.parametrize(
    "quote",
    ["SEAL CHAMBER PRESSURE:  ____*____  barg", "SEAL CHAMBER PRESSURE: By Contractor"],
)
def test_an_absence_second_reader_quoting_a_deferral_keeps_the_line_a_query(quote):
    rec = two_reader.absence_answer(
        found=True, quote=quote, page=2, clause_quote="c", paper_ok=True, clause_ok=True, strong=True,
        open_=False, model="m", usd=0.0, code_search={}, pages_total=7,
    )  # fmt: skip
    line = {
        "source": "rule", "item_id": "R-INVENTED-9", "ai_verdict": "Fail", "verdict": "Query", "decided_by": "engineer",
        "reason_code": "absent", "paper_quote": None, "quotes_checked": {"paper": False, "clause": True},
        "rule_tier": "approved", two_reader.ABSENCE_FIELD: rec,
    }  # fmt: skip
    got = wording.classify(line)
    assert got["verdict_class"] == wording.CLASS_QUERY
    assert got["verdict_label"] == wording.WORD_QUERY
    assert got["not_proven_reason"] == wording.DEFERRED_WHY


def test_an_unverified_absence_quote_is_not_read_as_a_deferral():
    rec = {
        "verdict": "cannot tell",
        "paper_quote": "X ___*___ m",
        "quotes_checked": {"paper": False},
    }
    line = {
        "ai_verdict": "Fail",
        "verdict": "Query",
        "reason_code": "not_met",
        two_reader.ABSENCE_FIELD: rec,
    }
    assert wording.not_met_deferred_why(line) is None


# ---------------------------------------------------------------- (b) not a deferral


@pytest.mark.parametrize(
    "line",
    [
        "Fields marked * in this sheet are by the vendor",
        "Item marked * a minimum of two",
        "values marked * m shall be confirmed",
        "Data marked * % are indicative",
        "ABC_*_DEF",
        "SK_*",
        "PART NO. XY_*_12",
        "ABC__*__DEF",
        "P/N AB__*__CD",
        "Load * kW is shared",
        "CASING SPLIT * s",
        "TEMPERATURE CLASS * C",
        "Material grade * K",
    ],
)
def test_a_note_star_before_a_word_and_an_underscore_part_number_are_no_deferral(line):
    assert blank_markers.star_fills_value(line) is False


@pytest.mark.parametrize(
    "line", ["* kW", "* (%)", "MOTOR OUTPUT  *  kW      SERVICE FACTOR  *  (%)"]
)
def test_a_star_and_unit_cell_still_defers(line):
    assert blank_markers.star_fills_value(line) is True


# ---------------------------------------------------------------- (c) each guard has a line only it stops


def test_the_legend_guard():
    assert (
        blank_markers.star_fills_value("* Values marked ___*___ are by the vendor")
        is False
    )


def test_the_pointer_guard():
    assert blank_markers.star_fills_value("___* see note 3") is False


def test_the_marked_guard():
    assert (
        blank_markers.star_fills_value("Values marked *  kW  are provisional") is False
    )


def test_the_figure_wins_guard():
    assert (
        blank_markers.star_fills_value("RATED FLOW 24.8 m3/h  NPSHR ___*___ m") is False
    )


CUT = {"agree": None, "model": "unknown", "reason": "stop_max_tokens"}


def _candidate(second):
    return {
        "item_id": "S-INVENTED-3", "ai_verdict": "Fail", "verdict": "Query", "decided_by": "engineer",
        "reason_code": "not_met", "reason_code_ai": "not_met", "checklist": True,
        "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "paper_page": 1,
        "paper_quote": "Coupling guard Not required", "clause_quote": "Coupling guards shall be provided.",
        "comment": "The guard is stated as not required.", "second_opinion": second,
    }  # fmt: skip


def test_a_cut_off_second_opinion_stops_a_line_that_is_otherwise_a_candidate():
    assert two_reader.is_candidate(_candidate(None)) is True
    assert two_reader.is_candidate(_candidate(CUT)) is False


def test_the_unit_must_end_the_cell():
    """R102: a lone star before a unit that running words follow is a sentence, not a blank."""
    assert blank_markers.star_fills_value("Load * kW is shared") is False
    assert blank_markers.star_fills_value("Load * kW") is True


def test_a_double_underscore_part_number_is_no_deferral():
    """R102: the drawn blank may not touch an underscore that belongs to a part number either."""
    assert blank_markers.star_fills_value("ABC__*__DEF") is False
    assert blank_markers.star_fills_value("P/N AB__*__CD") is False
    assert blank_markers.star_fills_value("FRAME  __*__") is True
