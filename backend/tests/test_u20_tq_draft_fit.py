# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""A query's automatic draft fits a query (builder C's walk of the measured copy, 26 Nov 2026: 21 of 32 drafts opened "No."; many cited
off-topic pages): the query-reply prompt (each numbered request answered, never a "Yes." / "No." opening), a relevance floor for passages
the system found, and the older system drafts written again at the next start. Chat's prompt is untouched. Invented values; no model."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import answer as A
from app import db
from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app.api import technical_queries as api
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import _run, query  # noqa: F401 - the ready-query fixture


def test_chat_keeps_its_prompt_byte_for_byte_and_a_query_reply_never_leads_with_yes_or_no():
    assert (
        A._fit(A.SYSTEM_PROMPT) == A.SYSTEM_PROMPT
        and A._fit(A.SYSTEM_PROMPT_VERIFIED) == A.SYSTEM_PROMPT_VERIFIED
    )
    with A.query_reply():
        for system in (A._fit(A.SYSTEM_PROMPT), A._fit(A.SYSTEM_PROMPT_VERIFIED)):
            assert (
                '"Yes.", "No.", "Partly."' not in system
                and 'never with a bare "Yes." or "No."' in system
                and "Write as COMPANY" in system
                and 'then "What I\'d do:"' not in system
            )
            assert (
                '"Not found in the documents searched."' in system
                and "INSUFFICIENT EVIDENCE" in system
            )  # the other rules stay
    assert A._fit(A.SYSTEM_PROMPT) == A.SYSTEM_PROMPT  # the block ends: Chat again


def test_the_automatic_draft_is_written_with_the_query_reply_prompt(query, monkeypatch):
    item, scope, _asked = query
    seen = []
    monkeypatch.setattr("app.answer.answer", lambda q, **k: seen.append(A._QUERY_REPLY.get()) or {
        "answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": "Invented clause 7.1: the flange rating shall be class 300."}]})  # fmt: skip
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    assert seen == [True]
    assert (
        tq.get(item["id"], "u1", False, False)["drafts"][-1]["prompt_version"]
        == auto.SYSTEM_DRAFT
    )


def test_a_system_found_passage_below_the_floor_is_no_source_but_an_engineers_kept_one_is(
    query, monkeypatch
):
    item, scope, asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    with (
        db.connect() as conn
    ):  # what the search will find scores in the answer lane's "plausible but wrong" band
        conn.execute("UPDATE query_evidence SET rank_score=-5.0")
    monkeypatch.setattr(tq, "prepare_evidence", _weak(tq.prepare_evidence))
    _run(item["id"])
    left = tq.get(item["id"], "u1", False, False)
    assert (
        left["drafts"] == []
        and left["ready"]["draft_note"] == auto.TOO_WEAK
        and asked == []
    )
    with pytest.raises(HTTPException) as refused:  # Generate draft says the same
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert "closely enough" in str(refused.value.detail)
    kept = left["evidence"][0]["id"]
    tq.update_evidence(
        item["id"],
        kept,
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    assert (
        auto.write_draft(item["id"], frozenset({"d1"}), "u1", False, False) is None
    )  # a kept passage always counts
    assert asked


def _weak(prepare):
    def run(*args, **kwargs):
        out = prepare(*args, **kwargs)
        with db.connect() as conn:
            conn.execute("UPDATE query_evidence SET rank_score=-5.0")
        return out

    return run


def test_an_older_system_draft_awaiting_review_is_written_again_at_the_next_start(
    query, monkeypatch
):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_drafts SET prompt_version='system-draft-1' WHERE query_id=?",
            (item["id"],),
        )
        assert auto.stale_system_drafts(conn) == [item["id"]]
    queued = []
    monkeypatch.setattr(J, "enqueue", lambda qid, *a, **k: queued.append(qid))
    assert auto.queue_backlog() == 1 and queued == [item["id"]]
    assert (
        tq.get(item["id"], "u1", False, False)["status"] == "drafting"
    )  # reopened, so the job may prepare and draft again
    with (
        db.connect() as conn
    ):  # never one with a decision on it, never the current version
        conn.execute(
            "UPDATE technical_queries SET status='awaiting_review' WHERE id=?",
            (item["id"],),
        )
        conn.execute(
            "UPDATE query_drafts SET prompt_version=? WHERE query_id=?",
            (auto.SYSTEM_DRAFT, item["id"]),
        )
        assert auto.stale_system_drafts(conn) == []
        conn.execute(
            "UPDATE query_drafts SET prompt_version='system-draft-1' WHERE query_id=?",
            (item["id"],),
        )
        conn.execute("INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) "
                     "VALUES ('x',?,NULL,'u1','request_changes',NULL,'x')", (item["id"],))  # fmt: skip
        assert auto.stale_system_drafts(conn) == []


def test_an_older_system_draft_still_drafting_is_written_again_too(query):
    """H's rescan of Install 1 (27 Nov 2026): the draft-version bump re-drafted only the queries awaiting review; 13 queries in
    "drafting" (sources already found by today's search) kept their system-draft-1/2 replies. A query in any preparable status
    whose latest draft is an older SYSTEM draft is drafted again; an engineer's own draft and a decided query never are."""
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET status='drafting' WHERE id=?", (item["id"],)
        )
        assert (
            auto.stale_system_drafts(conn) == []
        )  # today's draft version and search: nothing to redo
        conn.execute(
            "UPDATE query_drafts SET prompt_version='system-draft-2' WHERE query_id=?",
            (item["id"],),
        )
        assert auto.stale_system_drafts(conn) == [item["id"]]
        conn.execute(
            "UPDATE query_drafts SET model=NULL WHERE query_id=?", (item["id"],)
        )  # an engineer's own typed draft
        assert auto.stale_system_drafts(conn) == []
        conn.execute(
            "UPDATE query_drafts SET model='invented-model' WHERE query_id=?",
            (item["id"],),
        )
        conn.execute("INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) "
                     "VALUES ('y',?,NULL,'u1','request_changes',NULL,'x')", (item["id"],))  # fmt: skip
        assert auto.stale_system_drafts(conn) == []  # never one an engineer decided on


def test_a_query_already_tried_since_its_latest_draft_is_not_queued_again_at_every_start(
    query,
):
    """F after Install 2c (27 Nov 2026): 6 drafting queries on an older system draft whose sources are too weak were re-queued at EVERY
    start; each run stored "no source answers ... closely enough" and wrote no draft, so the next start picked them again. Once a
    preparation ran after the latest draft and stored why no draft was written, it is not queued again (a person keeps a source)."""
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET status='drafting', draft_note=NULL WHERE id=?",
            (item["id"],),
        )
        conn.execute(
            "UPDATE query_drafts SET prompt_version='system-draft-1', created_at='2026-11-27T01:00:00Z' WHERE query_id=?",
            (item["id"],),
        )
        conn.execute(
            "UPDATE query_evidence_jobs SET created_at='2026-11-27T00:00:00Z' WHERE query_id=?",
            (item["id"],),
        )
        assert auto.stale_system_drafts(conn) == [
            item["id"]
        ]  # an older system draft, never tried since: drafted again
        conn.execute(
            "UPDATE technical_queries SET draft_note=? WHERE id=?",
            (auto.TOO_WEAK, item["id"]),
        )
        assert auto.stale_system_drafts(conn) == [
            item["id"]
        ]  # a note, but no preparation ran after the draft yet
        conn.execute(
            "UPDATE query_evidence_jobs SET created_at='2026-11-27T02:00:00Z' WHERE query_id=?",
            (item["id"],),
        )
        assert (
            auto.stale_system_drafts(conn) == []
        )  # tried after the draft, nothing written: not queued at every start


def test_keeping_one_source_never_narrows_the_draft_to_it_alone(query):
    """F's walk (26 Nov 2026): with 1 of 5 good sources kept, the draft rested on that 1 only. Now: the kept ones first, then the system's
    close-enough finds for this wording that nobody rejected, up to MAX_DRAFT_PASSAGES; a weak or a rejected find is never one."""
    item, _scope, _asked = query
    wording = "1. What flange rating applies?"
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET proposed_question=? WHERE id=?",
            (wording, item["id"]),
        )
        rows = [("kept", "verified", "current", -3.0), ("f1", "proposed", "unknown", 2.0), ("f2", "proposed", "unknown", 0.5),
                ("weak", "proposed", "unknown", -4.0), ("nope", "rejected", "unknown", 3.0)]  # fmt: skip
        for eid, state, standing, score in rows:
            conn.execute(
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,evidence_state,"
                "supersession_state,created_at,found_for,rank_score) VALUES (?,?,'d1',3,3,'q',?,?,?,'x',?,?)",
                (
                    eid,
                    item["id"],
                    f"h-{eid}",
                    state,
                    standing,
                    auto.key(wording),
                    score,
                ),
            )
        conn.execute(
            "UPDATE document_classification SET confirmed_by='u1' WHERE document_id='d1'"
        )
    got = tq.get(item["id"], "u1", False, False)
    with db.connect() as conn:
        attachments = tq.query_attachment_document_ids(conn)
    assert [
        e["id"] for e in auto.draft_passages(got, frozenset({"d1"}), attachments)
    ] == ["kept", "f1", "f2"]
    # the engineer rejects the others ("keep the sources the draft cites, reject the others"): exactly the kept set
    for eid in ("f1", "f2"):
        tq.update_evidence(
            item["id"],
            eid,
            "rejected",
            "unknown",
            None,
            "u1",
            "u1",
            False,
            False,
            reviewer=True,
        )
    got = tq.get(item["id"], "u1", False, False)
    assert [
        e["id"] for e in auto.draft_passages(got, frozenset({"d1"}), attachments)
    ] == ["kept"]


def test_a_query_whose_evidence_an_older_search_found_joins_the_backlog_unless_an_engineer_acted(
    query,
):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        assert (
            auto.stale_system_drafts(conn) == []
        )  # today's search, today's draft: nothing to redo
        conn.execute(
            "UPDATE technical_queries SET evidence_search_version='2' WHERE id=?",
            (item["id"],),
        )
        assert auto.stale_system_drafts(conn) == [
            item["id"]
        ]  # an older search: searched and drafted again at the next start
        conn.execute("INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) "
                     "VALUES ('d',?,NULL,'u1','request_changes',NULL,'x')", (item["id"],))  # fmt: skip
        assert auto.stale_system_drafts(conn) == []  # never one an engineer decided on


def test_a_reply_written_again_by_hand_is_redone_too_when_its_sources_are_out_of_date(
    query,
):
    """The owner's regression query (27 Nov 2026): its latest draft came from "Write the reply again" (a model draft with no version label), so the redo
    skipped it and its sources stayed those of the old single search. Any model-written draft counts; an engineer's typed one never."""
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_drafts SET prompt_version=NULL WHERE query_id=?",
            (item["id"],),
        )  # as Write the reply again stores it
        conn.execute(
            "UPDATE technical_queries SET evidence_search_version=NULL WHERE id=?",
            (item["id"],),
        )  # the old search
        assert auto.stale_system_drafts(conn) == [item["id"]]
        conn.execute(
            "UPDATE query_drafts SET model=NULL WHERE query_id=?", (item["id"],)
        )  # an engineer's own typed draft: never
        assert auto.stale_system_drafts(conn) == []
