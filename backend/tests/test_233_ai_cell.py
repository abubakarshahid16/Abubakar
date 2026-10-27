"""Order 233: the internal CRS copy's "AI Review Comments" cell is never blank.

What must hold: a confirmed AI/web item says it was written by the AI; a machine
row the lock refused says why in plain words; a row never tried, or a run whose
wording step was off or stopped, says that; an accepted wording and an AI draft
are left as they are; the issue copy never carries any of it; and the note never
touches `ai_review_comment`, which the issue and carry-forward rules test for
emptiness. Invented rows only.
"""
from __future__ import annotations

import pytest

from app import crs_ai_cell, crs_export, crs_wording
from app.config import settings
from tests.test_763_crs_ai_wording import GOOD, ROW, _Fake, _review, _views
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

MACHINE = dict(ROW, crs_row_key="m1")
AI_ROW = {"row_kind": "ai_engineering_check", "crs_row_key": "a1", "engineer_confirmed": True,
          "comment": "Check the relief valve set pressure.", "ai_review_comment": ""}


@pytest.fixture
def wording_on(monkeypatch):
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)


def _note(row):
    return row.get("ai_cell_note")


def test_a_confirmed_ai_item_says_the_ai_wrote_it():
    rows = [dict(AI_ROW)]
    crs_ai_cell.apply(rows, "run-1")
    assert _note(rows[0]) == "Written by the AI (see the comment)"
    assert rows[0]["ai_review_comment"] == ""


def test_a_web_item_too_but_not_one_the_engineer_reworded_or_left_waiting():
    web = dict(AI_ROW, row_kind="web_standard_check", crs_row_key="w1")
    reworded = dict(AI_ROW, crs_row_key="a2", engineer_worded=True)
    edited = dict(AI_ROW, crs_row_key="a3", edited=True)
    waiting = dict(AI_ROW, crs_row_key="a4", engineer_confirmed=False,
                   comment=next(iter(crs_ai_cell.crs_mapping.WAITING_COMMENTS)))
    rows = [web, reworded, edited, waiting]
    crs_ai_cell.apply(rows, "run-1")
    assert _note(web) == crs_ai_cell.AI_DRAFT_NOTE
    assert [_note(r) for r in (reworded, edited, waiting)] == [None, None, None]


def test_a_refused_row_says_why_in_plain_words(wording_on):
    refused = dict(ROW, crs_row_key="k2")
    crs_wording.word_run("run-2", [MACHINE, refused],
                         provider=_Fake([GOOD, GOOD.replace("92", "93")]))
    rows = [dict(MACHINE), dict(refused)]
    crs_ai_cell.apply(rows, "run-2")
    assert rows[0]["ai_review_comment"] == GOOD and _note(rows[0]) is None
    assert _note(rows[1]) == "Plain wording kept: the AI's wording changed a number"


@pytest.mark.parametrize("reason", sorted(crs_wording_reasons := {
    crs_wording.NO_COMMENT, crs_wording.TOO_LONG, crs_wording.MALFORMED,
    crs_wording.TRUNCATED, crs_wording.UNKNOWN, crs_wording.NUMBER_CHANGED,
    crs_wording.UNIT_CHANGED, crs_wording.CLAUSE_DROPPED, crs_wording.STANDARD_CHANGED,
    crs_wording.CLAIM_ADDED, crs_wording.STATUS_REVERSED}))
def test_every_refusal_reason_has_its_own_plain_sentence(reason, wording_on):
    crs_wording._store_summary("run-3", {"enabled": True, "refused_rows": {"m1": reason}})
    rows = [dict(MACHINE)]
    crs_ai_cell.apply(rows, "run-3")
    sentence = _note(rows[0])
    assert sentence.startswith("Plain wording kept: ") and sentence != (
        crs_ai_cell.KEPT + crs_ai_cell._GENERIC)
    assert reason not in sentence                    # plain words, not the code word


def test_a_run_that_never_worded_says_so(monkeypatch):
    rows = [dict(MACHINE)]
    crs_ai_cell.apply(rows, "run-never")
    assert _note(rows[0]) == "Plain wording kept: the AI wording step did not run for this review"
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", False)
    crs_wording.word_run("run-off", rows, provider=_Fake([]))
    crs_ai_cell.apply(rows, "run-off")
    assert _note(rows[0]) == "Plain wording kept: the AI wording step is switched off"


def test_a_stopped_step_and_rows_past_the_cap_say_so(wording_on):
    crs_wording.word_run("run-s", [MACHINE], provider=_Fake([TimeoutError("slow")]))
    rows = [dict(MACHINE)]
    crs_ai_cell.apply(rows, "run-s")
    assert _note(rows[0]) == "Plain wording kept: the AI wording step stopped before this row"
    crs_wording._store_summary("run-cap", {"enabled": True, "not_tried": 5, "stopped": None})
    crs_ai_cell.apply(rows, "run-cap")
    assert _note(rows[0]) == (
        f"Plain wording kept: only the first {crs_wording.MAX_ROWS} rows are worded")


def test_an_engineers_row_gets_no_note():
    rows = [dict(MACHINE, comment_by="Edited by Eng One"), dict(MACHINE, engineer_confirmed=True),
            dict(MACHINE, row_kind="engineer_comment")]
    crs_ai_cell.apply(rows, "run-1")
    assert [_note(r) for r in rows] == [None, None, None]


def _cell(finding, copy):
    return crs_export._ai_column(finding, copy)


def test_the_cell_prints_the_note_on_the_internal_copy_only():
    row = {"ai_cell_note": crs_ai_cell.AI_DRAFT_NOTE, "ai_review_comment": ""}
    assert _cell(row, crs_export.COPY_INTERNAL) == crs_ai_cell.AI_DRAFT_NOTE
    assert _cell(row, crs_export.COPY_ISSUE) == ""


def test_a_draft_or_the_edited_label_wins_over_the_note():
    note = {"ai_cell_note": "note"}
    assert _cell(dict(note, ai_review_comment="draft"), crs_export.COPY_INTERNAL) == "draft"
    edited = dict(note, edited=True, ai_comment="machine words", ai_review_comment="")
    assert _cell(edited, crs_export.COPY_INTERNAL) == "AI wording: machine words"


def test_a_finished_review_leaves_no_machine_row_blank_on_the_internal_copy(
        world, monkeypatch, wording_on):
    run_id = _review(world, monkeypatch, _Fake([]))      # the model fails: nothing is worded
    views = _views(world, run_id)
    machine = [r for r in views["internal"] if r.get("row_kind") in crs_wording.WORDED_KINDS]
    assert machine
    assert all(r["ai_review_comment"].startswith("Plain wording kept: ") for r in machine)
    assert all(not r["ai_review_comment"] for r in views["issue"])
