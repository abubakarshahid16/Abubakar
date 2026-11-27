"""The marks a reply was drafted WITH reach the page (builder H, 27 Nov 2026, on live: 11 of 33 replies held "The AI could not show where
[Sn] says this" in their stored list, and no screen read it; the advice and cost words taken out of a reply were "beside" nothing).
Invented query and wording; no model, no network."""

from __future__ import annotations

from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_reply_checks as RC
from app.technical_query_source_fit import MARK, NOT_CHECKED
from tests.test_technical_queries import envelope
from tests.test_tq_g_feature_off import (  # noqa: F401 - storage is the autouse database fixture
    on,
    storage,
)

FIT = MARK.format(tags="[S2]")
ADVICE = RC.ADVICE_MARK + "Invented advice for the engineer."
QUESTION_MARK = "The AI suggested this question. Nobody has confirmed it yet."


def _draft(monkeypatch, unresolved, model):
    on(monkeypatch)
    item, _ = tq.import_message(envelope("marks-1"), "u1", False, False)
    tq.add_draft(item["id"], "COMPANY confirms the invented flange rating [S2].", [], unresolved, None, "u1", False, False,
                 model=model, prompt_version=auto.SYSTEM_DRAFT, question="1. What flange rating applies?")  # fmt: skip
    return auto.ready(tq.get(item["id"], "u1", False, False))["marks"]


def test_an_ai_replys_stored_marks_are_shown_once(monkeypatch):
    stored = [QUESTION_MARK, ADVICE, RC.COST_MARK + "Invented cost words.", RC.UNSOURCED_MARK, FIT, NOT_CHECKED, FIT]
    marks = _draft(monkeypatch, stored, "invented-local-model")
    for mark in (ADVICE, RC.COST_MARK + "Invented cost words.", RC.UNSOURCED_MARK, FIT, NOT_CHECKED):
        assert marks.count(mark) == 1
    # the question's own marks are worked out fresh, never read back from an old draft
    assert marks.count(QUESTION_MARK) <= 1


def test_an_engineers_own_reply_carries_no_stored_ai_marks(monkeypatch):
    marks = _draft(monkeypatch, [FIT, ADVICE], None)
    assert FIT not in marks and ADVICE not in marks


def test_a_stored_list_that_cannot_be_read_shows_nothing_from_it():
    assert auto.stored_reply_marks({"model": "m", "unresolved_json": "not json"}) == []
    assert auto.stored_reply_marks(None) == []
