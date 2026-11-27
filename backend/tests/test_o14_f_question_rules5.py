# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""Question rules 5 (lead-5, 27 Nov 2026; narrowed on A's read): #2009 reads a lead-in line as an unnumbered lead and a back-pointing
request as the statement it points to, but only when a question is PROPOSED. A query last prepared under rules 4 is prepared again at the
next start ONLY when tidying its STORED proposals against their own page text (no model call) changes the question the page shows;
awaiting review too (on a model's reply, nobody decided, nothing confirmed). The others keep their replies. Invented queries only."""

from __future__ import annotations

import json

from app import db
from app import technical_query_auto as auto
from app import technical_query_jobs as J

from .test_g_gmail_skipped_count import (  # noqa: F401 - fixtures used by name (temp_storage is autouse there)
    temp_storage,
    tq,
)
from .test_u16_tq_rules4_reprepare import _query

PAGE = "Invented form\n\nInvented request lead: the following two points:\n1. Invented point one?\n2. Invented point two?"
LEAD = "Invented request lead: the following two points:"
POINTS = ["Invented point one?", "Invented point two?"]


def _prepared(
    conn, qid: str, items: list[str], status: str = "drafting", rules: int = 4
) -> None:
    """A query prepared under `rules` whose stored proposals are `items` (as the model listed them, before #2009's tidy) and whose
    stored proposed question is what the page showed then (every item numbered, under the made-up lead)."""
    job = J.enqueue(qid, frozenset(), "u1", True, False)
    conn.execute(
        "UPDATE query_evidence_jobs SET state='done', question_rules=? WHERE id=?",
        (rules, job),
    )
    proposals = [{"question": q, "filename": "inv.pdf", "page": 1} for q in items]
    shown_then = "\n".join(
        [
            "About Invented, the contractor asks for the following:",
            *[f"{n}. {q}" for n, q in enumerate(items, 1)],
        ]
    )
    conn.execute(
        "UPDATE technical_queries SET status=?, extracted_question=NULL, attachment_context=?, proposed_questions=?, "
        "proposed_question=?, title_short='Invented', subject='Invented' WHERE id=?",
        (
            status,
            json.dumps([{"filename": "inv.pdf", "page": 1, "text": PAGE}]),
            json.dumps(proposals),
            shown_then,
            qid,
        ),
    )


def test_only_a_query_whose_shown_question_changes_is_prepared_again(
    monkeypatch, temp_storage, tq
):
    monkeypatch.setattr(
        J, "start", lambda: None
    )  # no thread in a test: the jobs stay queued
    changed, same = _query(31), _query(32)
    with db.connect() as conn:
        _prepared(
            conn, changed, [LEAD, *POINTS]
        )  # the lead-in was numbered as item 1: rules 5 shows it as a lead
        _prepared(
            conn, same, POINTS
        )  # nothing for rules 5 to tidy: the same question, the good reply kept
        assert J.QUESTION_RULES == 5
        assert J.question_would_change(conn, changed) and not J.question_would_change(
            conn, same
        )
        assert J.unprepared(conn) == [changed]
        assert changed in auto.backlog(conn)


def test_an_awaiting_review_query_whose_question_changes_goes_back_to_drafting_at_the_start(
    monkeypatch, temp_storage, tq
):
    """A's ask: not only `unprepared`, the start-up path itself - in the backlog, back to drafting, queued."""
    monkeypatch.setattr(J, "start", lambda: None)
    model, typed, decided = _query(41), _query(42), _query(43)
    with db.connect() as conn:
        for qid in (model, typed, decided):
            _prepared(conn, qid, [LEAD, *POINTS], status="awaiting_review")
            conn.execute(
                "INSERT INTO query_drafts(id,query_id,version,answer,model,prompt_version,created_by,created_at) "
                "VALUES (?,?,1,'Invented reply.',?,'system-draft-3','u1','x')",
                (f"d-{qid}", qid, None if qid == typed else "invented-model"),
            )
        conn.execute(
            "INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) "
            "VALUES ('x',?,NULL,'u1','request_changes',NULL,'x')",
            (decided,),
        )
        assert J.unprepared(conn) == [
            model
        ]  # never an engineer's typed reply, never a decided query
        conn.execute(
            "UPDATE technical_queries SET owner_user_id='u1' WHERE id=?", (model,)
        )
    queued: list[str] = []
    monkeypatch.setattr(J, "enqueue", lambda qid, *a, **k: queued.append(qid))
    scope = type(
        "S",
        (),
        {
            "readable_with_attachments": frozenset(),
            "user_id": "u1",
            "is_admin": True,
            "unrestricted": False,
        },
    )()
    monkeypatch.setattr("app.access.scope_for_user", lambda uid: scope)
    auto.queue_backlog()
    assert model in queued
    with db.connect() as conn:
        status = dict(
            conn.execute(
                "SELECT id, status FROM technical_queries WHERE id IN (?,?)",
                (model, typed),
            ).fetchall()
        )
    assert status[model] == "drafting" and status[typed] == "awaiting_review"


def test_a_confirmed_or_edited_question_is_never_prepared_again(
    monkeypatch, temp_storage, tq
):
    monkeypatch.setattr(J, "start", lambda: None)
    confirmed, edited = _query(51), _query(52)
    with db.connect() as conn:
        _prepared(conn, confirmed, [LEAD, *POINTS])
        _prepared(conn, edited, [LEAD, *POINTS])
        conn.execute(
            "UPDATE technical_queries SET confirmed_question='Invented confirmed?' WHERE id=?",
            (confirmed,),
        )
        conn.execute(
            "UPDATE technical_queries SET edited_question='Invented own wording?' WHERE id=?",
            (edited,),
        )
        assert J.unprepared(conn) == []


def test_prepare_all_sends_an_awaiting_query_back_to_drafting_too(
    monkeypatch, temp_storage, tq
):
    """H's note on #2016: "Prepare all" flipped only the older-system-draft queries back to drafting, not the rules-5 awaiting ones from
    `unprepared`, so it would have queued them while still awaiting review. Now every queued query goes back to drafting first."""
    monkeypatch.setattr(J, "start", lambda: None)
    model = _query(61)
    with db.connect() as conn:
        _prepared(conn, model, [LEAD, *POINTS], status="awaiting_review")
        conn.execute(
            "INSERT INTO query_drafts(id,query_id,version,answer,model,prompt_version,created_by,created_at) "
            "VALUES ('d-61',?,1,'Invented reply.','invented-model','system-draft-3','u1','x')",
            (model,),
        )
        assert model in J.unprepared(conn)
    monkeypatch.setattr(J, "enqueue", lambda *a, **k: None)
    J.queue_all(frozenset(), "u1", True, False)
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM technical_queries WHERE id=?", (model,)
            ).fetchone()[0]
            == "drafting"
        )
