# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""COMPANY's usual cost / schedule position in a system draft: a set sentence added by code, never by the model, and marked for the
engineer (lead-4's decision, 27 Nov 2026). Invented values; no model."""

from __future__ import annotations

from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app import technical_query_position as P
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import _run, query  # noqa: F401 - the ready-query fixture


def test_the_set_sentence_closes_a_plain_technical_reply():
    out = P.with_position(
        "1. Class 300 applies [S1].", "1. Which flange class applies?\n2. Which gasket?"
    )
    assert out == f"1. Class 300 applies [S1].\n\n{P.POSITION_LINE}"
    assert P.position_mark(out, "Which flange class applies?", True) == P.POSITION_MARK
    assert P.with_position(out, "Which flange class applies?") == out  # never twice


def test_nothing_is_added_when_the_request_raises_cost_or_schedule_and_the_page_says_it_is_the_engineers_call():
    for ask in (
        "Please confirm the cost impact of the revised routing.",
        "CONTRACTOR requests an extension of time for item 2.",
        "Will a variation order be issued for the added valves?",
        "CONTRACTOR seeks compensation for the re-work.",
    ):
        assert P.raises_cost(ask), ask
        assert (
            P.with_position("Class 300 applies [S1].", ask) == "Class 300 applies [S1]."
        )
        assert P.position_mark("Class 300 applies [S1].", ask, True) == P.RAISED_MARK


def test_nothing_is_added_when_the_draft_already_speaks_of_an_impact_and_a_typed_reply_gets_no_mark():
    deferring = "Class 300 applies [S1]. COMPANY to confirm any schedule impact."
    assert P.with_position(deferring, "Which class applies?") == deferring
    assert P.position_mark(deferring, "Which class applies?", True) is None
    assert (
        P.position_mark(f"Typed.\n\n{P.POSITION_LINE}", "Which class applies?", False)
        is None
    )
    # technical words that only look like money or time are not a cost request
    assert not P.raises_cost(
        "What is the time delay of the trip relay? Is the scheduled maintenance interval stated?"
    )


def test_the_system_draft_carries_the_sentence_and_the_page_marks_it(
    query, monkeypatch
):
    item, scope, _asked = query
    monkeypatch.setattr("app.answer.answer", lambda q, **k: {
        "answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": "Invented clause 7.1: the flange rating shall be class 300."}]})  # fmt: skip
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    draft = got["drafts"][-1]
    assert draft["answer"].endswith(P.POSITION_LINE)
    assert draft["prompt_version"] == auto.SYSTEM_DRAFT == "system-draft-3"
    assert P.POSITION_MARK in got["ready"]["marks"]
