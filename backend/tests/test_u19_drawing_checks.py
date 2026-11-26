"""Drawings (builder H, 26 Nov 2026: a planted drawing scored 1 of 10; its checklist asked only what the subject's standards ask,
0 of 190 values were compared by code, and the run cap cut the judge before the paper's own checks). With update 13 ON:
  1. a paper named a drawing gets G2 consistency pairs and G3 required entries of its own (`reference/drawing_checks.json`);
  2. a test pressure below the clause's factor times the DESIGN pressure is Not met by code where the page states no MAWP;
  3. the always-on checks are judged first, so a run cap cannot cut them.
With update 13 OFF, nothing changes (the updates-off sha256 guard covers the prompts; this file covers each piece).
Invented rows, figures and book text; no model, no database."""

from __future__ import annotations

import pytest

from app.aim_review import always, updates
from app.aim_review import formulas as F
from app.config import settings

CLAUSE = (
    "a hydrostatic test pressure that at every point in the vessel is at least equal to 1.3 times the maximum allowable "
    "working pressure"
)


class _Paper:
    def __init__(self, text: str):
        self.pages = {1: text}


def _lines(monkeypatch, text: str):
    monkeypatch.setattr(F, "_carried", lambda conn, ids: {"bk-invented": ("INVENTED-BOOK", {7: "Invented intro. " + CLAUSE + "."})})
    return [(ln["item_id"], ln["label"]) for ln in F.lines(None, _Paper(text), ["bk-invented"])]


@pytest.fixture
def u13(monkeypatch):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)


def test_off_the_new_check_and_the_drawing_context_do_not_exist(monkeypatch):
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert "hydrotest_design" not in [c.id for c in F.checks()]
    assert always.form_context({"kind": "drawing"}) == ("", "")
    assert updates.with_always(["c1", "c2"], ["G1"]) == ["c1", "c2", "G1"]  # as main: the checklist first


def test_a_test_pressure_below_the_factor_times_the_design_pressure_is_not_met_by_code(monkeypatch, u13):
    rows = "Hydrostatic test pressure   10 barg\nDesign pressure   9 barg"
    got = _lines(monkeypatch, rows)  # 10 < 1.3 x 9 = 11.7
    assert got == [("F-hydrotest_design", "Not met")]


def test_never_met_and_left_to_the_stronger_check_when_the_page_states_an_mawp(monkeypatch, u13):
    assert _lines(monkeypatch, "Hydrostatic test pressure   12 barg\nDesign pressure   9 barg") == []  # 12 >= 11.7: nothing proven
    both = "Hydrostatic test pressure   10 barg\nDesign pressure   9 barg\nMAWP   9 barg"
    assert _lines(monkeypatch, both) == [("F-hydrotest", "Not met")]  # the MAWP check decides; no second line on the design pressure


def test_a_drawing_gets_its_own_pairs_and_entries_and_judges_them_first(u13):
    pairs, entries = always.form_context({"kind": "Drawing"})
    assert "PAIRS THAT MUST AGREE on a drawing set" in pairs and "the date and the revision of the same sheet" in pairs.lower()
    assert "drawing number" in entries and "revision and its date" in entries
    datasheet_pairs, _ = always.form_context({"kind": "datasheet"})
    assert "on a drawing set" not in datasheet_pairs  # another kind keeps the datasheet pairs
    assert updates.with_always(["c1", "c2"], ["G1", "G2"]) == ["G1", "G2", "c1", "c2"]
