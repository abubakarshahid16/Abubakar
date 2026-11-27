# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""An engineer's own typed reply may replace a reply that awaits approval (lead-4, 27 Nov 2026): it becomes the new version awaiting
approval, the old one stays in the history, the event names it, and the reply keeps the sources its [S..] labels still cite. A model may
not. Invented values; no model."""

from __future__ import annotations

import json

import pytest

from app import technical_queries as tq
from app import technical_query_jobs as J
from app import technical_query_position as P
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import _run, query  # noqa: F401 - the ready-query fixture


def _drafted(query, monkeypatch):
    item, scope, _asked = query
    monkeypatch.setattr("app.answer.answer", lambda q, **k: {
        "answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": "Invented clause 7.1: the flange rating shall be class 300."}]})  # fmt: skip
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    assert got["status"] == "awaiting_review" and json.loads(
        got["drafts"][-1]["citations_json"]
    )
    return got


def test_an_engineers_reply_replaces_one_awaiting_approval_keeping_its_cited_sources(
    query, monkeypatch
):
    got = _drafted(query, monkeypatch)
    old = got["drafts"][-1]
    typed = f"1. Class 300 applies [S1].\n\n{P.POSITION_LINE}"
    after = tq.add_draft(got["id"], typed, [], [], "u1", "u1", False, False)
    new = after["drafts"][-1]
    assert (
        after["status"] == "awaiting_review"
        and new["answer"] == typed
        and new["model"] is None
    )
    assert [d["id"] for d in after["drafts"]][:-1] == [
        d["id"] for d in got["drafts"]
    ]  # the old version stays in the history
    assert json.loads(new["citations_json"]) == json.loads(
        old["citations_json"]
    )  # [S1] still cited: its source is kept
    with tq.connect() as conn:
        detail = conn.execute(
            "SELECT detail FROM query_events WHERE query_id=? AND event='draft_created' ORDER BY rowid DESC LIMIT 1",
            (got["id"],),
        ).fetchone()[0]
    assert detail.endswith(";replaces_reply_awaiting_approval")


def test_a_label_the_engineer_took_out_is_not_carried(query, monkeypatch):
    got = _drafted(query, monkeypatch)
    after = tq.add_draft(
        got["id"], "Class 300 applies.", [], [], "u1", "u1", False, False
    )
    assert json.loads(after["drafts"][-1]["citations_json"]) == []


def test_a_model_may_not_replace_a_reply_awaiting_approval(query, monkeypatch):
    got = _drafted(query, monkeypatch)
    with pytest.raises(ValueError):
        tq.add_draft(
            got["id"],
            "Another model reply [S1].",
            [],
            [],
            None,
            "u1",
            False,
            False,
            model="synthetic-local",
        )
