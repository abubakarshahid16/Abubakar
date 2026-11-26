"""The technical-query path END TO END on the realistic invented mailbox (`fixtures/tq_realistic`; owner's standing rule T1, 26 Nov 2026):
import -> the question shown -> evidence listed -> a draft opened, with a fake model and a fake contract search. Every TQ change runs this.
Invented content only; no Gmail, no network, no model."""

from __future__ import annotations

import pytest

from app import (
    db,
    extract,
    gmail_import_jobs,
    technical_query_jobs,
    technical_query_replies,
)
from app.access import AccessScope
from app.api.technical_queries import (
    generate_query_draft,
    technical_query_status_counts,
)
from app.technical_queries import (
    REVIEWER_CAPABILITY,
    confirm_question,
    get,
    prepare_evidence,
    update_evidence,
)

from .fixtures import tq_realistic as T
from .test_technical_queries import (  # noqa: F401 - the fixture is used by name
    hold_contract,
    temp_storage,
)

CONTRACT = "contract-invented"


@pytest.fixture
def imported(monkeypatch):
    monkeypatch.setattr(
        technical_query_jobs, "start", lambda: None
    )  # the evidence thread is the app's; here jobs stay queued
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    monkeypatch.setattr(
        gmail_import_jobs, "AUTO_START", False
    )  # the job is run here by hand, never by the background thread
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at)"
            " VALUES ('mb','u1',?,'1',?,'active','2026-11-26T00:00:00Z','2026-11-26T00:00:00Z')",
            (T.MAILBOX, T.LABEL),
        )
    job = gmail_import_jobs.enqueue("mb", "import", T.LABEL)
    box = {"id": "mb", "email": T.MAILBOX, "owner_user_id": "u1"}
    gmail_import_jobs._import(job, T.FakeGmail(T.messages()), box, T.LABEL, None)
    with (
        db.connect() as conn
    ):  # the ingest worker's part, done here at once: each taken-in paper is read, then ready
        docs = [
            r[0]
            for r in conn.execute(
                "SELECT document_id FROM query_attachments WHERE document_id IS NOT NULL"
            )
        ]
    for doc in docs:
        extract.extract_document(doc)
        with db.connect() as conn:
            conn.execute("UPDATE documents SET status='ready' WHERE id=?", (doc,))
    hold_contract(CONTRACT)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            (CONTRACT, 1, T.CONTRACT_CLAUSE, len(T.CONTRACT_CLAUSE), 0, 1),
        )
    return job


def _query(ref_number: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM technical_queries WHERE ref_number=?", (ref_number,)
        ).fetchone()
    return get(row[0], "u1", True, True)


def test_the_import_reads_the_real_shapes(imported):
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
        kinds = {
            r[0]: r[1]
            for r in conn.execute("SELECT filename, scan_status FROM query_attachments")
        }
        inline = conn.execute(
            "SELECT COUNT(*) FROM query_attachments WHERE inline_picture=1 AND document_id IS NULL"
        ).fetchone()[0]
        queries = conn.execute(
            "SELECT ref_type, ref_number, needs_person FROM technical_queries ORDER BY ref_number"
        ).fetchall()
    assert (
        job["total"] == 11
        and job["failed"] == 0
        and job["skipped"] == {technical_query_replies.ATTACHED: 1}
    )
    assert (
        job["queries"] == 9 and job["imported"] == 10
    )  # 6 messages in 5 queries: the forward of a forward joins TQ-11; ours too
    assert {tuple(q) for q in queries} == {
        (None, None, 1),
        ("CFC", "4", 0),
        ("TQ", "11", 0),
        ("TQ", "12", 0),
        ("TQ", "14", 0),
        ("TQ", "15", 0),
        ("TQ", "16", 0),
        ("TQ", "17", 0),
        ("TQ", "13", 0),
    }
    tq = _query("11")
    assert [m["is_inbound"] for m in tq["messages"]] == [
        1,
        1,
        0,
    ]  # the question, the forward of a forward, then ours ("sent by us")
    assert inline == 7  # 5 + 2 signature pictures, none uploaded
    assert (
        kinds["tq-form-11.docx"] == "static_check_clean"
        and kinds["tq-form-11.pdf"] == "static_check_clean"
    ), (kinds["tq-form-11.docx"], kinds["tq-form-11.pdf"])
    assert (
        kinds["drawing-list-12.pdf"] == "static_check_unreadable"
    )  # the broken file never enters the library
    assert (
        kinds["query-form-13.docm.docx"] == "static_check_flagged"
    )  # the macro Word file is never opened
    first = tq["messages"][0]
    assert (
        "HAFTUNGSAUSSCHLUSS" in first["body_folded"]
        and "DISCLAIMER" not in first["body_main"]
    )  # both notices folded


def test_question_shown_evidence_listed_and_a_draft_opened(imported, monkeypatch):
    monkeypatch.setattr(
        "app.technical_query_questions._ask",
        lambda page_text: [T.FORM_QUESTION] if T.FORM_QUESTION in page_text else [],
    )
    monkeypatch.setattr(
        "app.search.search",
        lambda question, **k: {
            "hits": [
                {
                    "document_id": CONTRACT,
                    "page_start": 1,
                    "page_end": 1,
                    "text": T.CONTRACT_CLAUSE,
                }
            ]
        },
    )
    tq = _query("11")
    allowed = frozenset(
        {
            CONTRACT,
            *(
                a["document_id"]
                for m in tq["messages"]
                for a in m["attachments"]
                if a["document_id"]
            ),
        }
    )
    prepared = prepare_evidence(tq["id"], allowed, "u1", True, True, "u1")
    # the question is SHOWN: proposed from the Word form (and its PDF twin), never from the signature or the notices
    assert any(p["question"] == T.FORM_QUESTION for p in prepared["proposed_questions"])
    assert {p["filename"] for p in prepared["proposed_questions"]} <= {
        "tq-form-11.docx",
        "tq-form-11.pdf",
    }
    assert (
        "DISCLAIMER" not in (prepared["extracted_question"] or "")
        and "regards" not in (prepared["extracted_question"] or "").lower()
    )
    # evidence LISTED: the held contract's clause
    assert [e["document_id"] for e in prepared["evidence"]] == [CONTRACT]
    confirm_question(tq["id"], T.FORM_QUESTION, "u1", True, True, "u1", reviewer=True)
    update_evidence(
        tq["id"],
        prepared["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        True,
        True,
        reviewer=True,
    )
    monkeypatch.setattr(
        "app.answer._call_model",
        lambda prompt, timeout=180.0: {
            "response": "The header is designed for 12 bar(g) [S1].",
            "model": "invented-local",
        },
    )
    drafted = generate_query_draft(
        tq["id"],
        AccessScope(
            "u1", allowed, capabilities=frozenset({"admin", REVIEWER_CAPABILITY})
        ),
    )
    assert drafted["drafts"][-1]["answer"].startswith(
        "The header is designed for 12 bar(g)"
    )  # a draft OPENED


def test_the_count_only_view_of_the_same_mailbox(imported):
    got = technical_query_status_counts(
        AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    )
    box = next(b for b in got["mailboxes"] if b["mailbox"] == "mb")
    assert (box["messages"], box["messages_sent_by_us"], box["queries"]) == (11, 1, 9)
    assert (
        box["tq"],
        box["cfc"],
        box["needs_a_person"],
        box["signature_pictures"],
    ) == (7, 1, 1, 7)
    assert box["attachments_read"] == 2 and box["attachments_not_read"] == {
        "PDF": 1,
        "active content found": 2,
    }
    with (
        db.connect() as conn
    ):  # each new query from the mailbox was queued for evidence once
        assert (
            conn.execute(
                "SELECT COUNT(DISTINCT query_id) FROM query_evidence_jobs"
            ).fetchone()[0]
            == 9
        )


@pytest.mark.parametrize(
    "ref, question",
    [
        ("14", T.FORWARDED_QUESTION),
        ("15", T.RULED_QUESTION),
        ("16", T.IMPORTANT_QUESTION),
    ],
)
def test_a_forwarded_query_and_a_ruled_query_still_give_their_question(
    imported, monkeypatch, ref, question
):
    # review of update 12, N5: the question sits below a forwarded-message header, or below a rule line
    monkeypatch.setattr("app.technical_query_questions._ask", lambda page_text: [])
    monkeypatch.setattr("app.search.search", lambda q, **k: {"hits": []})
    tq = _query(ref)
    prepared = prepare_evidence(tq["id"], frozenset({CONTRACT}), "u1", True, True, "u1")
    assert question in (prepared["extracted_question"] or "") and question in (
        prepared["proposed_question"] or ""
    )
    assert (
        "DISCLAIMER" not in prepared["extracted_question"]
        and "Original Message" not in prepared["extracted_question"]
    )
