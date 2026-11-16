"""Order 14 lane D: the enquiry sheet's lone "*" (vendor to fill) is a deferral mark where a value is expected, never where
it is a footnote or a note mark (`blank_markers.star_fills_value`, `blank_markers.defers_value`). Invented lines only; the
planted pump base (eval/planted/centrifugal_pump.json, invented) gives the field labels and units."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import blank_markers

BASE = (
    Path(__file__).resolve().parents[2] / "eval" / "planted" / "centrifugal_pump.json"
)


# ---------------------------------------------------------------- where a value is expected: a deferral


@pytest.mark.parametrize(
    "line",
    [
        "COOLING WATER SUPPLY ______*______ m3/h      RETURN  ____*____ m3/h",
        "FLUSH * m3/h",
        "MOTOR OUTPUT  *  kW      SERVICE FACTOR  *  (%)",
        "SEAL CHAMBER PRESSURE:                ________*_________  barg",
        "COUPLING MAKE:        ______*________",
        "*____________",
        "ALLOWED RANGE (9.4.2)   ___*___   to   ___*___  m3/h",  # a clause number in brackets is no value
        "FLANGE RATING  Class 300   ___*___",  # a pointer number is no value
        "*",
    ],
)
def test_a_vendor_to_fill_star_where_a_value_is_expected_defers(line):
    assert blank_markers.star_fills_value(line) is True
    assert blank_markers.defers_value(line) is True


# ---------------------------------------------------------------- a footnote or a note mark: never a deferral


@pytest.mark.parametrize(
    "line",
    [
        "RATED FLOW * 24.8 m3/h",  # the line states its figure
        "RATED FLOW 24.8 m3/h *",  # a footnote on a stated value
        "Head 78 m *",
        "COUPLING SPACER *",  # a lone star at the end of a line is read as a footnote: no blank ink, no unit after it
        "CASING MATERIAL  A216 WCB  *",  # a footnote on a stated text value
        "* ALL DIMENSIONS IN MM",  # a legend line opening with a star
        "*Values are indicative only",
        "(*) see below",
        "Rated flow * see note 3",  # a star leading into a pointer
        "* Note 2",
        "COUPLING MAKE*",  # glued to a word
        "24.8*",  # glued to a figure
        "IMPELLER 2*4 VANES",
        "MOTOR OUTPUT 250 kW",
        "",
        None,
    ],
)
def test_a_footnote_or_note_star_is_not_a_deferral(line):
    assert blank_markers.star_fills_value(line) is False
    assert blank_markers.defers_value(line) is False


def test_the_phrase_markers_still_defer_and_names_a_marker_is_unchanged():
    """`defers_value` adds the star; it takes nothing away, and the readers' `names_a_marker` (single cells) is not widened."""
    assert blank_markers.defers_value("340 psig By Contractor") is True
    assert (
        blank_markers.defers_value("* VENDOR TO ADVISE / CONFIRM") is True
    )  # the phrase, not the star
    assert blank_markers.names_a_marker("FLUSH ___*___ m3/h") is False
    assert blank_markers.defers_value("BY PASS VALVE") is False


# ---------------------------------------------------------------- the planted pump base (invented sheet)


@pytest.fixture(scope="module")
def pump() -> dict:
    return json.loads(BASE.read_text(encoding="utf-8"))


def _rows(base: dict) -> list[dict]:
    return [r for page in base["pages"] for r in page["rows"]]


def test_every_blank_plant_printed_with_the_star_is_seen_and_every_clean_row_is_not(
    pump,
):
    rows = {r["role"]: r for r in _rows(pump)}
    blanks = [p["field"] for p in pump["plants"] if p["defect"] == "blank_required"]
    assert blanks, "the planted pump base has blank plants"
    for role in blanks:
        row = rows[role]
        unit = row.get("unit") or ""
        forms = [
            f"{row['field']}  ______*______ {unit}"
        ]  # the drawn blank with the star
        if unit:  # a lone star counts only before a unit; a trailing lone star is read as a footnote
            forms.append(f"{row['field']} * {unit}")
        for printed in forms:
            assert blank_markers.defers_value(printed), (role, "star blank not seen")
    for row in _rows(pump):
        clean = f"{row['field']}  {row['value']} {row.get('unit') or ''}"
        assert not blank_markers.defers_value(clean), (
            row["role"],
            "clean row read as deferred",
        )
        footnoted = f"{clean} *"
        if any(ch.isdigit() for ch in str(row["value"])):
            assert not blank_markers.defers_value(footnoted), (
                row["role"],
                "footnote star read as deferred",
            )
