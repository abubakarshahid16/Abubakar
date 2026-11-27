# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""Question rules 5 (lead-5, 27 Nov 2026): #2009 reads a lead-in line as a lead and a back-pointing request as the statement it points
to, but only when a question is PROPOSED. The queries already prepared under rules 4 are proposed again at the next start (the start-up
backlog takes `unprepared`), unless an engineer confirmed the question. Invented queries only."""

from __future__ import annotations

from app import db
from app import technical_query_auto as auto
from app import technical_query_jobs as J

from .test_g_gmail_skipped_count import (  # noqa: F401 - fixtures used by name (temp_storage is autouse there)
    temp_storage,
    tq,
)
from .test_u16_tq_rules4_reprepare import _query


def test_queries_prepared_under_rules_4_are_proposed_again_at_the_next_start_unless_confirmed(
    monkeypatch, temp_storage, tq
):
    monkeypatch.setattr(
        J, "start", lambda: None
    )  # no thread in a test: the jobs stay queued
    old, confirmed, current = _query(11), _query(12), _query(13)
    with db.connect() as conn:
        for qid, rules in ((old, 4), (confirmed, 4), (current, J.QUESTION_RULES)):
            job = J.enqueue(qid, frozenset(), "u1", True, False)
            conn.execute(
                "UPDATE query_evidence_jobs SET state='done', question_rules=? WHERE id=?",
                (rules, job),
            )
        conn.execute(
            "UPDATE technical_queries SET confirmed_question='Invented confirmed question?' WHERE id=?",
            (confirmed,),
        )
        assert J.QUESTION_RULES == 5
        assert J.unprepared(conn) == [old]
        assert (
            old in auto.backlog(conn)
        )  # the start-up backlog takes it (the others are there only because they have no draft yet)


def test_a_reply_awaiting_review_is_proposed_again_only_when_a_model_wrote_it_and_nobody_decided(
    monkeypatch, temp_storage, tq
):
    """20 of the 34 live queries await review: their question is proposed again too (the start-up backlog sends them back to drafting),
    but never an engineer's own typed reply, never a decided query, never a confirmed question."""
    monkeypatch.setattr(J, "start", lambda: None)
    model, typed, decided = _query(21), _query(22), _query(23)
    with db.connect() as conn:
        for qid in (model, typed, decided):
            job = J.enqueue(qid, frozenset(), "u1", True, False)
            conn.execute(
                "UPDATE query_evidence_jobs SET state='done', question_rules=4 WHERE id=?",
                (job,),
            )
            conn.execute(
                "UPDATE technical_queries SET status='awaiting_review' WHERE id=?",
                (qid,),
            )
            conn.execute("INSERT INTO query_drafts(id,query_id,version,answer,model,prompt_version,created_by,created_at) "
                         "VALUES (?,?,1,'Invented reply.',?,'system-draft-3','u1','x')", (f"d-{qid}", qid, None if qid == typed else "invented-model"))  # fmt: skip
        conn.execute("INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) "
                     "VALUES ('x',?,NULL,'u1','request_changes',NULL,'x')", (decided,))  # fmt: skip
        assert J.unprepared(conn) == [model]
        conn.execute(
            "UPDATE technical_queries SET confirmed_question='Invented confirmed?' WHERE id=?",
            (model,),
        )
        assert J.unprepared(conn) == []
