from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import HTTPException, UploadFile

from app import db, gmail_auth, gmail_sync
from app.access import AccessScope
from app.api.technical_queries import (
    ImportIn,
    SendIn,
    TriageIn,
    _safe_item,
    download_original_query_email,
    generate_query_draft,
    import_technical_query,
    prepare_query_send,
    technical_query_assignees,
    triage_technical_query,
    upload_query_attachment,
)
from app.config import settings
from app.gmail_client import GmailApiClient, GmailMessage, normalize_message
from app.gmail_worker import (
    activate_label,
    poll_mailbox,
    process_history,
    send_approved,
)
from app.technical_queries import (
    add_draft,
    add_evidence,
    assign_query,
    decide,
    ensure_schema,
    get,
    import_message,
    link_attachment,
    list_queries,
    metrics,
    prepare_evidence,
    reconcile_send,
    update_evidence,
)
from app.technical_query_docx import render as render_query_docx


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "queries.sqlite")
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES (?,?,?,?,?)",
            ("u1", "u1@example.test", "User One", "test", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES (?,?,?,?,?)",
            ("owner", "owner@example.test", "Owner", "test", "2026-01-01T00:00:00Z"),
        )
    ensure_schema()
    yield
    db.reset_connection()


def envelope(message_id: str = "message-1") -> dict:
    return {
        "provider": "synthetic",
        "mailbox_id": "test-mailbox",
        "provider_message_id": message_id,
        "provider_thread_id": "thread-1",
        "from_address": "contractor@example.test",
        "to_addresses": ["engineering@example.test"],
        "cc_addresses": [],
        "subject": "Technical query",
        "body": "Please confirm the applicable coating schedule.",
        "question": "Please confirm the applicable coating schedule.",
        "attachments": [
            {
                "filename": "query.pdf",
                "media_type": "application/pdf",
                "size_bytes": 1234,
            }
        ],
    }


def test_import_preserves_message_and_attachment_and_is_idempotent():
    first, duplicate = import_message(envelope(), "u1", False, False)
    assert duplicate is False
    assert first["status"] == "received"
    assert first["messages"][0]["subject"] == "Technical query"
    assert first["messages"][0]["attachments"][0]["filename"] == "query.pdf"

    second, duplicate = import_message(envelope(), "u1", False, False)
    assert duplicate is True
    assert second["id"] == first["id"]
    assert len(second["messages"]) == 1


def test_triage_requires_admin_and_updates_filtered_metrics():
    item, _ = import_message(envelope("triage"), "u1", False, False)
    body = TriageIn(
        contractor_name="Synthetic Contractor",
        department="Mechanical",
        priority="high",
        due_at="2026-02-01",
    )
    with pytest.raises(HTTPException) as denied:
        triage_technical_query(item["id"], body, AccessScope("u1", frozenset()))
    assert denied.value.status_code == 403
    result = triage_technical_query(
        item["id"],
        body,
        AccessScope("u1", frozenset(), capabilities=frozenset({"admin"})),
    )
    assert result["status"] == "triage"
    assert result["contractor_name"] == "Synthetic Contractor"
    assert result["due_at"] == "2026-02-01"
    assert metrics("u1", True, False, contractor="Synthetic Contractor")["triage"] == 1
    assert any(event["event"] == "triaged" for event in result["events"])


def test_question_in_pdf_attachment_is_extracted_but_not_used_as_answer_evidence(
    monkeypatch,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "query-pdf",
                "query.pdf",
                "c" * 64,
                1,
                "query.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("query-pdf", 1, "", 0, 1, 1),
        )
        conn.execute(
            "INSERT INTO page_ocr(document_id,page_no,text,char_count,engine,model,dpi,box_count,seconds,recognised_at,batch_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "query-pdf",
                1,
                "What is the permitted coating thickness?",
                40,
                "synthetic",
                "synthetic",
                150,
                1,
                0.1,
                "2026-01-01T00:00:00Z",
                1,
            ),
        )
    payload = envelope("question-in-attachment")
    payload["body"] = "Please see attached."
    payload["question"] = None
    item, _ = import_message(payload, "u1", False, False)
    link_attachment(
        item["id"],
        item["messages"][0]["attachments"][0]["id"],
        "query-pdf",
        "u1",
        "u1",
        True,
        False,
    )
    captured = {}

    def fake_search(question, **_kwargs):
        captured["question"] = question
        return {
            "hits": [
                {
                    "document_id": "query-pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "What is the permitted coating thickness?",
                }
            ]
        }

    monkeypatch.setattr("app.search.search", fake_search)
    result = prepare_evidence(
        item["id"], frozenset({"query-pdf"}), "u1", True, False, "u1"
    )
    assert "What is the permitted coating thickness?" in captured["question"]
    assert "What is the permitted coating thickness?" in result["extracted_question"]
    assert result["evidence"] == []
    repeated = prepare_evidence(
        item["id"], frozenset({"query-pdf"}), "u1", True, False, "u1"
    )
    assert repeated["extracted_question"] == result["extracted_question"]


def test_real_search_returns_results_under_hits_not_passages():
    """prepare_evidence reads this shape. A fake that returned "passages" hid a
    live bug: every real search looked empty and no evidence was ever attached."""
    from app import fts_index, search

    fts_index.ensure_schema()
    result = search.search(
        "coating thickness",
        limit=5,
        rerank=False,
        dense=False,
        allowed_document_ids=frozenset(),
    )
    assert "hits" in result
    assert "passages" not in result


def test_preparing_evidence_twice_does_not_duplicate_a_passage(monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("lib-doc", "standard.pdf", "a1" * 32, 1, "standard.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("lib-doc", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    item, _ = import_message(envelope("twice"), "u1", False, False)
    monkeypatch.setattr(
        "app.search.search",
        lambda question, **_k: {
            "hits": [{"document_id": "lib-doc", "page_start": 1, "page_end": 1, "text": "The limit is 12 bar."}]
        },
    )
    for _ in range(3):
        result = prepare_evidence(item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1")
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["supersession_state"] == "unknown"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification(document_id,suggested_by,confirmed_by) VALUES (?,?,?)",
            ("lib-doc", "rules", "u1"),
        )
    result = prepare_evidence(item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1")
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["supersession_state"] == "current"
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET superseded_by='newer' WHERE document_id='lib-doc'")
    result = prepare_evidence(item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1")
    assert result["evidence"][0]["supersession_state"] == "superseded"


def test_prepare_evidence_does_not_search_the_querys_own_attachment(monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("own-attachment", "query.pdf", "e" * 64, 1, "query.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
    item, _ = import_message(envelope("scope-check"), "u1", False, False)
    link_attachment(
        item["id"], item["messages"][0]["attachments"][0]["id"],
        "own-attachment", "u1", "u1", True, False,
    )
    seen = {}

    def fake_search(question, **kwargs):
        seen["scope"] = kwargs["allowed_document_ids"]
        return {"hits": []}

    monkeypatch.setattr("app.search.search", fake_search)
    prepare_evidence(
        item["id"], frozenset({"own-attachment", "library-doc"}), "u1", True, False, "u1"
    )
    assert seen["scope"] == frozenset({"library-doc"})


def test_quote_matches_a_clause_the_pdf_wrapped_across_lines_but_not_a_changed_number():
    from app.technical_queries import _quote_on_pages

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("wrapped-source", "standard.pdf", "f" * 64, 1, "standard.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("wrapped-source", 1, "4.2 Carbon steel shall receive a total dry film\nthickness of not less than 280 micrometres.\n", 90, 0, 1),
        )
        same = "4.2 Carbon steel shall receive a total dry film thickness of not less than 280 micrometres."
        changed = same.replace("280", "250")
        assert _quote_on_pages(conn, "wrapped-source", 1, 1, same) is True
        assert _quote_on_pages(conn, "wrapped-source", 1, 1, changed) is False
        assert _quote_on_pages(conn, "wrapped-source", 1, 1, "   ") is False


def test_exact_quote_can_be_verified_on_a_recognised_source_page():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "scanned-source",
                "standard.pdf",
                "d" * 64,
                1,
                "standard.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("scanned-source", 2, "", 0, 1, 1),
        )
        conn.execute(
            "INSERT INTO page_ocr(document_id,page_no,text,char_count,engine,model,dpi,box_count,seconds,recognised_at,batch_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "scanned-source",
                2,
                "The limit is 12 bar.",
                20,
                "synthetic",
                "synthetic",
                150,
                1,
                0.1,
                "2026-01-01T00:00:00Z",
                1,
            ),
        )
    item, _ = import_message(envelope("scanned-evidence"), "u1", False, False)
    result = add_evidence(
        item["id"],
        "scanned-source",
        "The limit is 12 bar.",
        2,
        2,
        None,
        frozenset({"scanned-source"}),
        "u1",
        True,
        False,
        "u1",
    )
    assert result["evidence"][0]["page_start"] == 2


def test_missing_mailbox_id_still_deduplicates():
    message = envelope("without-mailbox")
    message["mailbox_id"] = None
    first, duplicate = import_message(message, "u1", False, False)
    assert duplicate is False
    second, duplicate = import_message(message, "u1", False, False)
    assert duplicate is True
    assert second["id"] == first["id"]


def test_approval_requires_latest_draft_id():
    item, _ = import_message(envelope("approval-binding"), "u1", False, False)
    item = add_draft(item["id"], "Answer for review", [], [], "u1", "u1", False, False)
    latest_id = item["drafts"][-1]["id"]
    with pytest.raises(ValueError, match="latest draft"):
        decide(
            item["id"],
            "approve",
            "owner",
            None,
            "different-draft",
            "owner",
            True,
            False,
        )
    with pytest.raises(ValueError, match="latest draft"):
        decide(item["id"], "approve", "owner", None, None, "owner", True, False)
    approved = decide(
        item["id"], "approve", "owner", None, latest_id, "owner", True, False
    )
    assert approved["status"] == "approved"


def test_unverified_provider_claim_and_unconnected_send_are_refused():
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    claimed_gmail = envelope("claimed-gmail")
    claimed_gmail["provider"] = "gmail"
    with pytest.raises(HTTPException) as blocked_import:
        import_technical_query(ImportIn(**claimed_gmail), scope)
    assert blocked_import.value.status_code == 422
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM query_messages").fetchone()[0] == 0

    item, _ = import_message(envelope("send-unconfigured"), "u1", False, False)
    with pytest.raises(HTTPException) as blocked_send:
        prepare_query_send(
            item["id"],
            SendIn(
                draft_id="synthetic-draft",
                mailbox_id="missing-mailbox",
                idempotency_key="send-key-1",
            ),
            scope,
        )
    assert blocked_send.value.status_code == 409
    assert get(item["id"], "u1", False, False)["status"] == "received"
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM query_sends").fetchone()[0] == 0


def test_invalid_attachment_id_is_rejected_before_document_ingestion(monkeypatch):
    item, _ = import_message(envelope("bad-attachment"), "u1", False, False)
    called = False

    def ingest_never_called(*_args):
        nonlocal called
        called = True
        raise AssertionError("ingestion must not run")

    monkeypatch.setattr(
        "app.api.technical_queries.upload_mod.ingest", ingest_never_called
    )
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            upload_query_attachment(
                item["id"],
                "missing-attachment",
                UploadFile(filename="query.pdf", file=BytesIO(b"PDF")),
                scope,
            )
        )
    assert rejected.value.status_code == 404
    assert called is False


def test_attachment_status_reflects_document_processing():
    item, _ = import_message(envelope("attachment-status"), "u1", False, False)
    attachment_id = item["messages"][0]["attachments"][0]["id"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (
                "attached-doc",
                "query.pdf",
                "c" * 64,
                10,
                "/tmp/query.pdf",
                "2026-01-01T00:00:00Z",
            ),
        )
    linked = link_attachment(
        item["id"], attachment_id, "attached-doc", "u1", "u1", False, False
    )
    attachment = linked["messages"][0]["attachments"][0]
    assert attachment["scan_status"] == "not_scanned"
    assert attachment["parse_status"] == "ready"


def test_generated_draft_refuses_citations_outside_verified_quote(monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (
                "doc-2",
                "source.pdf",
                "b" * 64,
                10,
                "/tmp/source.pdf",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,?)",
            ("doc-2", 1, "Approved limit is 12 bar. Separate note is 20 bar.", 48, 1),
        )
    item, _ = import_message(envelope("draft-evidence"), "u1", False, False)
    item = add_evidence(
        item["id"],
        "doc-2",
        "Approved limit is 12 bar.",
        1,
        1,
        None,
        frozenset({"doc-2"}),
        "u1",
        False,
        False,
        "u1",
    )
    assert item["evidence"][0]["supersession_state"] == "unknown"
    update_evidence(
        item["id"],
        item["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
    )
    scope = AccessScope("u1", frozenset({"doc-2"}))
    monkeypatch.setattr(
        "app.api.technical_queries.answer.answer",
        lambda *_args, **_kwargs: {
            "answer_type": "generated",
            "answer": "The limit is 20 bar [S1].",
            "cited": [1],
            "passages": [
                {
                    "document_id": "doc-2",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "Separate note is 20 bar.",
                }
            ],
        },
    )
    with pytest.raises(HTTPException) as blocked:
        generate_query_draft(item["id"], scope)
    assert blocked.value.status_code == 409
    assert get(item["id"], "u1", False, False)["drafts"] == []
    monkeypatch.setattr(
        "app.api.technical_queries.answer.answer",
        lambda *_args, **_kwargs: {
            "answer_type": "generated",
            "answer": "The approved limit is 12 bar [S1].",
            "cited": [1],
            "passages": [
                {
                    "document_id": "doc-2",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "Approved limit is 12 bar.",
                }
            ],
        },
    )
    drafted = generate_query_draft(item["id"], scope)
    assert drafted["status"] == "awaiting_review"
    assert drafted["drafts"][-1]["answer"] == "The approved limit is 12 bar [S1]."
    citations = __import__("json").loads(drafted["drafts"][-1]["citations_json"])
    assert citations[0]["document_id"] == "doc-2"
    assert citations[0]["page"] == 1


def test_word_preview_marks_unapproved_response_and_missing_evidence(tmp_path):
    item, _ = import_message(envelope("word-preview"), "u1", False, False)
    item = add_draft(item["id"], "Proposed answer", [], [], "u1", "u1", False, False)
    path = render_query_docx(item, tmp_path / "preview.docx")
    with ZipFile(path) as package:
        document = package.read("word/document.xml").decode()
    assert "DRAFT Technical Query Response" in document
    assert "No verified source evidence" in document


def test_word_response_keeps_line_breaks_and_names_documents_not_ids(tmp_path):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("doc-internal-id", "SYN-STD-001.pdf", "b2" * 32, 1, "x.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("doc-internal-id", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    item, _ = import_message(envelope("word-names"), "u1", False, False)
    add_evidence(
        item["id"], "doc-internal-id", "The limit is 12 bar.", 1, 1, None,
        frozenset({"doc-internal-id"}), "u1", True, False, "u1",
    )
    item = add_draft(item["id"], "First line.\nSecond line.", [], [], "u1", "u1", True, False)
    path = render_query_docx(item, tmp_path / "names.docx")
    with ZipFile(path) as package:
        document = package.read("word/document.xml").decode()
    assert "SYN-STD-001.pdf" in document
    assert "doc-internal-id" not in document
    assert "Status:" not in document
    assert "First line.</w:t></w:r><w:r><w:br/></w:r><w:r><w:t" in document


def test_new_message_in_same_provider_thread_is_follow_up():
    first, _ = import_message(envelope("thread-message-1"), "u1", False, False)
    follow = envelope("thread-message-2")
    follow["body"] = "Additional information for the same question."
    second, duplicate = import_message(follow, "u1", False, False)
    assert duplicate is False
    assert second["id"] == first["id"]
    assert len(second["messages"]) == 2
    assert second["messages"][1]["attachments"][0]["filename"] == "query.pdf"
    assert any(event["event"] == "follow_up_received" for event in second["events"])


def test_resolved_thread_follow_up_reopens_and_other_sender_gets_new_query():
    first, _ = import_message(envelope("resolved-first"), "u1", False, False)
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET status='resolved',resolved_at='2026-01-02T00:00:00Z' WHERE id=?",
            (first["id"],),
        )
    follow, duplicate = import_message(envelope("resolved-follow"), "u1", False, False)
    assert not duplicate
    assert follow["id"] == first["id"]
    assert follow["status"] == "triage"
    assert follow["resolved_at"] is None
    stranger = envelope("different-contractor")
    stranger["from_address"] = "other-contractor@example.test"
    separate, _ = import_message(stranger, "u1", False, False)
    assert separate["id"] != first["id"]


def test_query_visibility_is_owner_scoped():
    item, _ = import_message(envelope("message-2"), "owner", False, False)
    assert get(item["id"], "owner", False, False) is not None
    assert get(item["id"], "other", False, False) is None
    assert get(item["id"], None, False, True) is not None


def test_admin_assignment_grants_assignee_visibility():
    item, _ = import_message(envelope("assignment"), "owner", False, False)
    assert get(item["id"], "u1", False, False) is None
    with pytest.raises(PermissionError):
        assign_query(item["id"], "u1", "owner", False, False)
    assigned = assign_query(item["id"], "u1", "owner", True, False)
    assert assigned["assignee_user_id"] == "u1"
    assert get(item["id"], "u1", False, False) is not None
    assert any(event["event"] == "assigned" for event in assigned["events"])
    with pytest.raises(HTTPException) as denied:
        technical_query_assignees(AccessScope("u1", frozenset()))
    assert denied.value.status_code == 403
    assert {
        person["id"]
        for person in technical_query_assignees(
            AccessScope("owner", frozenset(), capabilities=frozenset({"admin"}))
        )["items"]
    } == {"u1", "owner"}
    with db.connect() as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE id='u1'")
    with pytest.raises(ValueError, match="inactive"):
        assign_query(item["id"], "u1", "owner", True, False)


def test_filtered_dashboard_totals_match_visible_records():
    first_data = envelope("metrics-one")
    first_data["contractor_name"] = "Contractor A"
    first_data["department"] = "Mechanical"
    first, _ = import_message(first_data, "owner", False, False)
    second_data = envelope("metrics-two")
    second_data["provider_thread_id"] = "different-thread"
    second_data["contractor_name"] = "Contractor B"
    second_data["department"] = "Civil"
    import_message(second_data, "owner", False, False)
    assign_query(first["id"], "u1", "owner", True, False)
    items = list_queries(
        "u1", False, False, contractor="Contractor A", department="Mechanical"
    )
    totals = metrics(
        "u1", False, False, contractor="Contractor A", department="Mechanical"
    )
    assert [item["id"] for item in items] == [first["id"]]
    assert totals["total"] == len(items) == 1
    assert totals["received"] == 1


def test_evidence_requires_exact_quote_and_can_be_classified():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (
                "doc-1",
                "source.pdf",
                "a" * 64,
                10,
                "/tmp/source.pdf",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,?)",
            ("doc-1", 1, "The coating schedule is APCS-11A.", 34, 1),
        )
        conn.execute(
            "INSERT INTO document_classification(document_id,suggested_by,superseded_by) VALUES (?,?,?)",
            ("doc-1", "synthetic-test", "newer-doc"),
        )
    item, _ = import_message(envelope("evidence-1"), "u1", False, False)
    with pytest.raises(ValueError):
        add_evidence(
            item["id"],
            "doc-1",
            "not on the page",
            1,
            1,
            None,
            frozenset({"doc-1"}),
            "u1",
            False,
            False,
            "u1",
        )
    with pytest.raises(ValueError, match="page range"):
        add_evidence(
            item["id"],
            "doc-1",
            "APCS-11A",
            None,
            None,
            None,
            frozenset({"doc-1"}),
            "u1",
            False,
            False,
            "u1",
        )
    item = add_evidence(
        item["id"],
        "doc-1",
        "APCS-11A",
        1,
        1,
        None,
        frozenset({"doc-1"}),
        "u1",
        False,
        False,
        "u1",
    )
    evidence_id = item["evidence"][0]["id"]
    assert item["evidence"][0]["supersession_state"] == "superseded"
    item = update_evidence(
        item["id"],
        evidence_id,
        "conflicting",
        "unknown",
        "g1",
        "u1",
        "u1",
        False,
        False,
    )
    assert item["evidence"][0]["evidence_state"] == "conflicting"
    safe = _safe_item(item, AccessScope("u1", frozenset()))
    assert safe["evidence"] == []
    assert safe["source_access_revoked"] is True


def test_gmail_oauth_state_is_one_time_and_never_stores_a_secret(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:8792/oauth/callback")
    url = gmail_auth.start("u1")
    assert "gmail.readonly" in url
    assert "gmail.send" in url
    state = url.split("state=", 1)[1].split("&", 1)[0]
    assert gmail_auth.validate_state(state) == "u1"
    assert gmail_auth.consume_state(state) == "u1"
    assert gmail_auth.consume_state(state) is None


def test_gmail_oauth_completion_stores_refresh_token_outside_database(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:8792/oauth/callback")
    url = gmail_auth.start("u1")
    state = url.split("state=", 1)[1].split("&", 1)[0]

    class FakeStore:
        def __init__(self):
            self.saved = {}

        def save_refresh_token(self, mailbox_id, token):
            self.saved[mailbox_id] = token

        def delete_refresh_token(self, mailbox_id):
            self.saved.pop(mailbox_id, None)

    store = FakeStore()
    result = gmail_auth.complete(
        "synthetic-code",
        state,
        exchange=lambda _data: {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
        },
        profile=lambda _token: {
            "emailAddress": "engineering@example.test",
            "historyId": "h100",
        },
        store=store,
    )
    assert result["email"] == "engineering@example.test"
    assert store.saved[result["mailbox_id"]] == "synthetic-refresh"
    assert b"synthetic-refresh" not in settings.db_path.read_bytes()
    with pytest.raises(ValueError):
        gmail_auth.complete(
            "synthetic-code", state, exchange=lambda _data: {}, store=store
        )


def test_gmail_message_normalization_and_worker_are_retry_safe():
    message = {
        "id": "gmail-message-1",
        "threadId": "gmail-thread-1",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "contractor@example.test"},
                {"name": "To", "value": "engineering@example.test"},
                {"name": "Subject", "value": "Technical question"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "VGVjaG5pY2FsIHF1ZXN0aW9u"},
                },
                {
                    "filename": "query.pdf",
                    "mimeType": "application/pdf",
                    "body": {"size": 12},
                },
            ],
        },
    }
    normalized = normalize_message(message)
    assert normalized.body == "Technical question"
    assert normalized.attachments[0]["filename"] == "query.pdf"

    def transport(method, url, **_kwargs):
        if url.endswith("/history"):
            payload = {
                "history": [{"messagesAdded": [{"message": {"id": "gmail-message-1"}}]}]
            }
        elif _kwargs.get("params", {}).get("format") == "raw":
            payload = {
                "raw": base64.urlsafe_b64encode(
                    b"From: contractor@example.test\n\nTechnical question"
                )
                .decode()
                .rstrip("=")
            }
        else:
            payload = message
        return __import__("httpx").Response(
            200, json=payload, request=__import__("httpx").Request(method, url)
        )

    client = GmailApiClient("synthetic-token", transport=transport)
    first = process_history(client, "history-1", "u1", mailbox_id="test-mailbox")
    second = process_history(client, "history-1", "u1", mailbox_id="test-mailbox")
    assert first[0]["duplicate"] is False
    assert second[0]["duplicate"] is True
    stored = get(first[0]["query_id"], "u1", False, False)
    original = stored["messages"][0]["raw_storage_ref"]
    assert original and __import__("pathlib").Path(original).is_file()
    assert __import__("pathlib").Path(original).stat().st_mode & 0o077 == 0
    assert (
        "raw_storage_ref"
        not in _safe_item(stored, AccessScope("u1", frozenset()))["messages"][0]
    )
    response = download_original_query_email(
        first[0]["query_id"],
        stored["messages"][0]["id"],
        AccessScope("u1", frozenset()),
    )
    assert str(response.path) == original
    with pytest.raises(HTTPException) as blocked:
        download_original_query_email(
            first[0]["query_id"],
            stored["messages"][0]["id"],
            AccessScope("owner", frozenset()),
        )
    assert blocked.value.status_code == 404


def test_gmail_history_reads_all_pages_and_normalizes_received_time():
    calls = []

    def transport(method, url, **kwargs):
        calls.append(kwargs.get("params", {}))
        token = kwargs.get("params", {}).get("pageToken")
        payload = (
            {
                "history": [{"messagesAdded": [{"message": {"id": "m1"}}]}],
                "nextPageToken": "next",
            }
            if token is None
            else {"history": [{"messagesAdded": [{"message": {"id": "m2"}}]}]}
        )
        httpx = __import__("httpx")
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    client = GmailApiClient("synthetic-token", transport=transport)
    assert client.history("start") == ["m1", "m2"]
    assert calls[1]["pageToken"] == "next"
    message = normalize_message(
        {
            "id": "m3",
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "Date", "value": "Tue, 14 Nov 2023 22:13:20 +0000"}
                ]
            },
        }
    )
    assert message.received_at == "2023-11-14T22:13:20Z"


def test_gmail_history_includes_messages_given_the_query_label_later():
    def transport(method, url, **_kwargs):
        httpx = __import__("httpx")
        return httpx.Response(
            200,
            json={
                "historyId": "h2",
                "history": [{"labelsAdded": [{"message": {"id": "newly-labelled"}}]}],
            },
            request=httpx.Request(method, url),
        )

    client = GmailApiClient("synthetic-token", transport=transport)
    assert client.history_delta("h1", "Label_TQ") == (["newly-labelled"], "h2")


def test_gmail_worker_imports_pdf_attachment_through_document_pipeline():
    import fitz

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Synthetic technical question")
    content = pdf.tobytes()
    pdf.close()
    message = {
        "id": "gmail-with-pdf",
        "threadId": "gmail-thread-pdf",
        "internalDate": "1700000000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "contractor@example.test"},
                {"name": "To", "value": "engineering@example.test"},
                {"name": "Subject", "value": "Synthetic technical question"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "UXVlc3Rpb24="}},
                {
                    "filename": "query.pdf",
                    "mimeType": "application/pdf",
                    "body": {"size": len(content), "attachmentId": "attachment-1"},
                },
            ],
        },
    }

    def transport(method, url, **_kwargs):
        if url.endswith("/history"):
            payload = {
                "history": [{"messagesAdded": [{"message": {"id": "gmail-with-pdf"}}]}]
            }
        elif url.endswith("/attachments/attachment-1"):
            payload = {
                "size": len(content),
                "data": base64.urlsafe_b64encode(content).decode().rstrip("="),
            }
        elif _kwargs.get("params", {}).get("format") == "raw":
            payload = {
                "raw": base64.urlsafe_b64encode(
                    b"From: contractor@example.test\n\nSynthetic question"
                )
                .decode()
                .rstrip("=")
            }
        else:
            payload = message
        httpx = __import__("httpx")
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    client = GmailApiClient("synthetic-token", transport=transport)
    first = process_history(client, "history-1", "u1", mailbox_id="synthetic-mailbox")
    second = process_history(client, "history-1", "u1", mailbox_id="synthetic-mailbox")
    assert first[0]["duplicate"] is False
    assert second[0]["duplicate"] is True
    item = get(first[0]["query_id"], "u1", False, False)
    attachment = item["messages"][0]["attachments"][0]
    assert attachment["document_id"]
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM documents WHERE id=?",
                (attachment["document_id"],),
            ).fetchone()[0]
            == 1
        )


def test_mailbox_cursor_advances_only_after_message_is_saved():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "mailbox-1",
                "u1",
                "engineering@example.test",
                "h1",
                "Label_TQ",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    class FakeClient:
        fail = True

        def history_delta(self, cursor, label_id):
            assert cursor == "h1"
            assert label_id == "Label_TQ"
            return ["m1"], "h2"

        def message(self, _message_id):
            return GmailMessage(
                "m1",
                "t1",
                "contractor@example.test",
                ["engineering@example.test"],
                [],
                "Question",
                "Please advise",
                None,
                [],
                ("Label_TQ",),
            )

        def raw_message(self, _message_id):
            if self.fail:
                raise TimeoutError("synthetic provider failure")
            return b"From: contractor@example.test\n\nPlease advise"

    client = FakeClient()
    with pytest.raises(TimeoutError):
        poll_mailbox(client, "mailbox-1", "u1")
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT last_history_id FROM gmail_mailboxes WHERE id='mailbox-1'"
            ).fetchone()[0]
            == "h1"
        )
    client.fail = False
    result = poll_mailbox(client, "mailbox-1", "u1")
    assert len(result) == 1
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT last_history_id FROM gmail_mailboxes WHERE id='mailbox-1'"
            ).fetchone()[0]
            == "h2"
        )


@pytest.mark.parametrize("status,expected", [(403, "active"), (401, "revoked")])
def test_mailbox_sync_does_not_call_transient_forbidden_a_revocation(
    monkeypatch, status, expected
):
    import httpx

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "mailbox-status",
                "u1",
                "engineering@example.test",
                "h1",
                "Label_TQ",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
    monkeypatch.setattr(
        gmail_sync.gmail_auth, "access_token", lambda _id: "synthetic-token"
    )

    def fail_poll(_client, _mailbox_id, _owner_id):
        response = httpx.Response(
            status,
            request=httpx.Request(
                "GET", "https://gmail.googleapis.com/gmail/v1/users/me/history"
            ),
        )
        raise httpx.HTTPStatusError(
            "synthetic", request=response.request, response=response
        )

    monkeypatch.setattr(gmail_sync, "poll_mailbox", fail_poll)
    assert gmail_sync.run_once() == 0
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT connection_state FROM gmail_mailboxes WHERE id='mailbox-status'"
            ).fetchone()[0]
            == expected
        )


def test_expired_gmail_cursor_recovers_with_labelled_full_sync():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "mailbox-expired",
                "u1",
                "engineering@example.test",
                "old",
                "Label_TQ",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    class FakeClient:
        def history_delta(self, _cursor, _label):
            httpx = __import__("httpx")
            response = httpx.Response(
                404, request=httpx.Request("GET", "https://example.test/history")
            )
            raise httpx.HTTPStatusError(
                "expired", request=response.request, response=response
            )

        def profile(self):
            return {"historyId": "fresh"}

        def list_message_ids(self, label_id):
            assert label_id == "Label_TQ"
            return ["m1"]

        def message(self, _id):
            return GmailMessage(
                "m1",
                "thread-1",
                "contractor@example.test",
                ["engineering@example.test"],
                [],
                "Question",
                "Please advise",
                None,
                [],
                ("Label_TQ",),
            )

        def raw_message(self, _id):
            return b"From: contractor@example.test\n\nPlease advise"

    result = poll_mailbox(FakeClient(), "mailbox-expired", "u1")
    assert len(result) == 1
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT last_history_id FROM gmail_mailboxes WHERE id='mailbox-expired'"
            ).fetchone()[0]
            == "fresh"
        )


def test_mailbox_imports_only_selected_user_label_before_activation():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                "mailbox-label",
                "u1",
                "engineering@example.test",
                "h1",
                "needs_label",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    class FakeClient:
        def labels(self):
            return [{"id": "Label_TQ", "name": "Technical Queries", "type": "user"}]

        def list_message_ids(self, label_id):
            assert label_id == "Label_TQ"
            return ["labelled", "not-labelled", "from-self"]

        def message(self, message_id):
            labels = ("INBOX",) if message_id == "not-labelled" else ("Label_TQ",)
            sender = (
                "engineering@example.test"
                if message_id == "from-self"
                else "contractor@example.test"
            )
            return GmailMessage(
                message_id,
                "thread-" + message_id,
                sender,
                ["engineering@example.test"],
                [],
                "Question",
                "Please advise",
                None,
                [],
                labels,
            )

        def raw_message(self, _message_id):
            return b"From: contractor@example.test\n\nPlease advise"

    client = FakeClient()
    with pytest.raises(ValueError, match="user-created"):
        activate_label(client, "mailbox-label", "u1", "INBOX")
    imported = activate_label(client, "mailbox-label", "u1", "Label_TQ")
    assert len(imported) == 1
    with db.connect() as conn:
        mailbox = conn.execute(
            "SELECT connection_state,label_id FROM gmail_mailboxes WHERE id='mailbox-label'"
        ).fetchone()
        assert (mailbox["connection_state"], mailbox["label_id"]) == (
            "active",
            "Label_TQ",
        )
        assert conn.execute("SELECT COUNT(*) FROM query_messages").fetchone()[0] == 1


def test_gmail_send_client_preserves_thread_id_in_request():
    captured = {}

    def transport(method, url, **kwargs):
        captured.update(kwargs["json"])
        httpx = __import__("httpx")
        return httpx.Response(
            200, json={"id": "sent-1"}, request=httpx.Request(method, url)
        )

    client = GmailApiClient("synthetic-token", transport=transport)
    assert (
        client.send("From: example@example.test\n\nBody", thread_id="thread-1")
        == "sent-1"
    )
    assert captured["threadId"] == "thread-1"
    assert captured["raw"]


def test_gmail_network_calls_use_fixed_hosts_without_redirects_or_ambient_proxy(
    monkeypatch,
):
    import httpx

    seen = []

    def fake_request(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return httpx.Response(
            200,
            json={"emailAddress": "engineering@example.test"},
            request=httpx.Request(method, url),
        )

    def fake_post(url, **kwargs):
        seen.append(("POST", url, kwargs))
        return httpx.Response(
            200,
            json={"access_token": "synthetic-token"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(httpx, "post", fake_post)
    GmailApiClient("synthetic-token").profile()
    gmail_auth._exchange({"grant_type": "refresh_token"})
    assert [call[1] for call in seen] == [
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        "https://oauth2.googleapis.com/token",
    ]
    assert all(call[2]["follow_redirects"] is False for call in seen)
    assert all(call[2]["trust_env"] is False for call in seen)


def test_html_only_gmail_message_keeps_visible_question():
    html = "<html><head><title>Hidden</title></head><body><p>Please confirm the test pressure.</p><script>ignore me</script></body></html>"
    payload = {
        "id": "html-only",
        "payload": {
            "headers": [
                {"name": "From", "value": "contractor@example.test"},
                {"name": "To", "value": "engineering@example.test"},
                {"name": "Subject", "value": "Technical question"},
            ],
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()},
        },
    }
    message = normalize_message(payload)
    assert message.body == "Please confirm the test pressure."


def test_send_worker_uses_approved_content_and_original_recipient_only():
    item, _ = import_message(envelope("send-1"), "u1", False, False)

    class FakeClient:
        calls = 0
        raw = ""

        def send(self, raw, *, thread_id=None):
            self.calls += 1
            self.raw = raw
            assert thread_id == "thread-1"
            return "provider-send-1"

    client = FakeClient()
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    drafted = add_draft(
        item["id"], "Approved technical answer", [], [], "u1", "u1", True, False
    )
    draft_id = drafted["drafts"][0]["id"]
    decide(item["id"], "approve", "u1", None, draft_id, "u1", True, False)
    with pytest.raises(ValueError, match="not been approved"):
        send_approved(
            client,
            item["id"],
            "wrong-draft",
            scope,
            "send-key-wrong",
            "engineering@example.test",
        )
    assert client.calls == 0
    sent_id = send_approved(
        client, item["id"], draft_id, scope, "send-key-1", "engineering@example.test"
    )
    assert sent_id == "provider-send-1"
    assert client.calls == 1
    assert "To: contractor@example.test" in client.raw
    assert "Approved technical answer" in client.raw
    assert (
        send_approved(
            client,
            item["id"],
            draft_id,
            scope,
            "send-key-1",
            "engineering@example.test",
        )
        == sent_id
    )
    assert client.calls == 1
    assert get(item["id"], "u1", True, False)["status"] == "sent"
    with pytest.raises(ValueError, match="current query state"):
        prepare_evidence(item["id"], frozenset(), "u1", True, False, "u1")
    with pytest.raises(ValueError, match="locked"):
        link_attachment(
            item["id"],
            item["messages"][0]["attachments"][0]["id"],
            "other-document",
            "u1",
            "u1",
            True,
            False,
        )


def test_second_send_key_cannot_send_while_first_request_is_in_flight():
    item, _ = import_message(envelope("send-race"), "u1", False, False)
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    drafted = add_draft(item["id"], "Reviewed answer", [], [], "u1", "u1", True, False)
    draft_id = drafted["drafts"][-1]["id"]
    decide(item["id"], "approve", "u1", None, draft_id, "u1", True, False)

    class ReentrantClient:
        calls = 0

        def send(self, _raw, *, thread_id=None):
            self.calls += 1
            with pytest.raises(ValueError, match="approved"):
                send_approved(
                    self,
                    item["id"],
                    draft_id,
                    scope,
                    "different-send-key",
                    "engineering@example.test",
                )
            return "provider-one"

    client = ReentrantClient()
    assert (
        send_approved(
            client,
            item["id"],
            draft_id,
            scope,
            "original-send-key",
            "engineering@example.test",
        )
        == "provider-one"
    )
    assert client.calls == 1
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM query_sends").fetchone()[0] == 1


def test_send_stops_if_approved_source_is_later_superseded():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "source-old",
                "source.pdf",
                "b" * 64,
                1,
                "source.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,?)",
            ("source-old", 1, "The limit is 12 bar.", 20, 1),
        )
    item, _ = import_message(envelope("source-changed"), "u1", False, False)
    add_evidence(
        item["id"],
        "source-old",
        "The limit is 12 bar.",
        1,
        1,
        None,
        frozenset({"source-old"}),
        "u1",
        True,
        False,
        "u1",
    )
    drafted = add_draft(item["id"], "Reviewed answer", [], [], "u1", "u1", True, False)
    draft_id = drafted["drafts"][-1]["id"]
    decide(item["id"], "approve", "u1", None, draft_id, "u1", True, False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification(document_id,suggested_by,superseded_by) VALUES (?,?,?)",
            ("source-old", "synthetic-test", "source-new"),
        )

    class FakeClient:
        calls = 0

        def send(self, _raw, *, thread_id=None):
            self.calls += 1
            return "unexpected"

    client = FakeClient()
    scope = AccessScope(
        "u1", frozenset({"source-old"}), capabilities=frozenset({"admin"})
    )
    with pytest.raises(ValueError, match="superseded"):
        send_approved(
            client,
            item["id"],
            draft_id,
            scope,
            "superseded-send",
            "engineering@example.test",
        )
    assert client.calls == 0


def test_explicit_send_endpoint_uses_connected_mailbox_and_fake_provider(monkeypatch):
    item, _ = import_message(envelope("endpoint-send"), "u1", False, False)
    drafted = add_draft(item["id"], "Reviewed answer", [], [], "u1", "u1", True, False)
    draft_id = drafted["drafts"][-1]["id"]
    decide(item["id"], "approve", "u1", None, draft_id, "u1", True, False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "mailbox-send",
                "u1",
                "engineering@example.test",
                "h1",
                "Label_TQ",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    class FakeClient:
        calls = 0

        def send(self, _raw, *, thread_id=None):
            self.calls += 1
            return "fake-provider-id"

    client = FakeClient()
    monkeypatch.setattr(
        "app.api.technical_queries.gmail_auth.access_token",
        lambda _id: "synthetic-token",
    )
    monkeypatch.setattr(
        "app.api.technical_queries.GmailApiClient", lambda _token: client
    )
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    result = prepare_query_send(
        item["id"],
        SendIn(
            draft_id=draft_id,
            mailbox_id="mailbox-send",
            idempotency_key="endpoint-key-1",
        ),
        scope,
    )
    assert result["sent"] is True
    assert result["item"]["status"] == "sent"
    assert client.calls == 1


def test_uncertain_provider_send_is_not_retried_automatically():
    item, _ = import_message(envelope("send-uncertain"), "u1", False, False)
    scope = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    drafted = add_draft(item["id"], "Reviewed answer", [], [], "u1", "u1", True, False)
    draft_id = drafted["drafts"][-1]["id"]
    decide(item["id"], "approve", "u1", None, draft_id, "u1", True, False)

    class UncertainClient:
        calls = 0

        def send(self, _raw, *, thread_id=None):
            self.calls += 1
            raise TimeoutError("provider reply lost")

    client = UncertainClient()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="reconcile"):
            send_approved(
                client,
                item["id"],
                draft_id,
                scope,
                "send-key-uncertain",
                "engineering@example.test",
            )
    assert client.calls == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT state FROM query_sends WHERE query_id=?", (item["id"],)
        ).fetchone()
    assert row["state"] == "uncertain"
    current = get(item["id"], "u1", True, False)
    send_id = current["sends"][0]["id"]
    with pytest.raises(PermissionError):
        reconcile_send(
            item["id"], send_id, "not_sent", None, "Checked mailbox", "u1", False, False
        )
    reconciled = reconcile_send(
        item["id"],
        send_id,
        "not_sent",
        None,
        "Checked mailbox and provider logs",
        "u1",
        True,
        False,
    )
    assert reconciled["status"] == "approved"
    assert reconciled["sends"][0]["state"] == "confirmed_not_sent"
