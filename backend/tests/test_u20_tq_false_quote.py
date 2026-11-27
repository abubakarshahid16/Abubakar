# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""A quote in a query's draft must be in the passage it is credited to (the owner on a live draft, 26 Nov 2026: two bullets put the
contractor's OWN words in quotation marks and credited them to [S1], a passage about another subject: "it must check a quoted phrase
against the cited SOURCE passage, not against anything on the page. Until fixed, a draft with an unsupported quote must not be shown as a
proposed response"). Invented values; no model."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import db
from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app.api import technical_queries as api
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import (  # noqa: F401 - the ready-query fixture
    QUOTE,
    _run,
    query,
)

ASKED = "Confirm the minimum invented coating thickness for the tank"


def test_a_quote_is_checked_against_the_passage_it_is_credited_to_and_nothing_else():
    sources = {
        1: QUOTE,
        2: "Invented clause 9.2: invoices are paid within thirty days.",
    }
    # the owner's case: the contractor's own words, in quotation marks, credited to [S1]
    assert (
        auto.unsupported_quotes(
            f'- The contract requires "{ASKED.lower()}" [S1].', sources, ASKED
        )
        == 1
    )
    assert (
        auto.unsupported_quotes(
            '- The rating is "the flange rating shall be class 300" [S1].', sources
        )
        == 0
    )
    assert (
        auto.unsupported_quotes('- Invoices: "paid within thirty days" [S1].', sources)
        == 1
    )  # in S2, credited to S1
    assert (
        auto.unsupported_quotes("- Invoices: “paid within thirty days” [S2].", sources)
        == 0
    )  # curly quotes, the right source
    assert (
        auto.unsupported_quotes(f'You ask us to "{ASKED.lower()}".', sources, ASKED)
        == 0
    )  # no citation: quoting the contractor
    assert (
        auto.unsupported_quotes("- Class 300 applies [S1].", sources) == 0
    )  # no quote, nothing to check


def _answer_quoting_the_question(monkeypatch):
    monkeypatch.setattr("app.answer.answer", lambda q, **k: {
        "answer_type": "generated", "answer": f'1. The contract requires "{ASKED.lower()}" [S1].', "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": QUOTE}]})  # fmt: skip


def test_a_draft_with_a_false_quote_is_never_kept_neither_automatic_nor_generated(
    query, monkeypatch
):
    item, scope, _asked = query
    _answer_quoting_the_question(monkeypatch)
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    left = tq.get(item["id"], "u1", False, False)
    assert left["drafts"] == [] and left["ready"]["draft_note"] == auto.FALSE_QUOTE
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert "quotation marks" in str(refused.value.detail)
    assert tq.get(item["id"], "u1", False, False)["drafts"] == []


def test_an_older_draft_with_a_false_quote_is_marked_and_never_approved(query):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(
        item["id"]
    )  # a draft written before this check: its answer quotes the contractor and credits [S1]
    ready = tq.get(item["id"], "u1", False, False)
    evidence = ready["evidence"][0]
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_drafts SET answer=?, citations_json=? WHERE query_id=?",
            (f'1. The contract requires "{ASKED.lower()}" [S1].',
             json.dumps([{"label": "S1", "evidence_id": evidence["id"], "document_id": "d1", "page": 3, "exact_quote": QUOTE}]),
             item["id"]),
        )  # fmt: skip
    tq.update_evidence(
        item["id"],
        evidence["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET confirmed_by='u1' WHERE document_id='d1'"
        )
    got = tq.get(item["id"], "u1", False, False)
    assert auto.FALSE_QUOTE_MARK in got["ready"]["marks"]
    with pytest.raises(ValueError, match="not in its source"):
        tq.decide(
            item["id"],
            "approve",
            "u1",
            None,
            got["drafts"][-1]["id"],
            "u1",
            False,
            False,
            reviewer=True,
        )


def test_what_the_contractors_form_cites_is_said_held_or_not_held():
    item = {"evidence_coverage": {"cited_first": ["Schedule B, 4.2: found", "ZQ-STD-9: not held among the standards you may read",
                                                  "the form's citations could not be looked up"]}}  # fmt: skip
    assert [c["held"] for c in auto.cited_by_contractor(item)] == [True, False, False]
    assert auto.cited_by_contractor({}) == []


def test_one_retry_when_the_only_fault_is_a_false_quote_and_the_check_still_stops_a_second(
    query, monkeypatch
):
    """Measured on a live snapshot (27 Nov 2026): the model varies from run to run; 8 of 9 redrafts of the stopped queries passed."""
    item, scope, _asked = query
    good = {"answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
            "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": QUOTE}]}  # fmt: skip
    bad = {**good, "answer": f'1. The contract requires "{ASKED.lower()}" [S1].'}
    answers = [bad, good]
    monkeypatch.setattr("app.answer.answer", lambda q, **k: answers.pop(0))
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    kept = tq.get(item["id"], "u1", False, False)
    assert answers == [] and [d["answer"] for d in kept["drafts"]] == [
        "1. Class 300 applies [S1]."
    ]  # the retry's draft, checked (the cost / schedule sentence is never put in by code)
    calls = []
    monkeypatch.setattr(
        "app.answer.answer", lambda q, **k: calls.append(1) or bad
    )  # false twice: still never shown
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET status='drafting' WHERE id=?", (item["id"],)
        )
    assert (
        auto.write_draft(item["id"], frozenset({"d1"}), "u1", False, False)
        == auto.FALSE_QUOTE
        and len(calls) == 2
    )


def test_the_reply_rule_forbids_quoting_the_contractor_as_a_source():
    from app import answer as A

    with A.query_reply():
        assert "Never put the contractor's own words in quotation marks" in A._fit(
            A.SYSTEM_PROMPT
        )
    assert A._fit(A.SYSTEM_PROMPT) == A.SYSTEM_PROMPT  # Chat unchanged
