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
)
from app.technical_queries import (
    REVIEWER_CAPABILITY,
    add_draft,
    add_evidence,
    assign_query,
    confirm_question,
    decide,
    ensure_schema,
    get,
    import_message,
    link_attachment,
    list_queries,
    metrics,
    prepare_evidence,
    update_evidence,
    validate_send_evidence,
)
from app.technical_query_docx import render as render_query_docx


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "queries.sqlite")
    monkeypatch.setattr(
        settings, "technical_queries_enabled", True
    )  # the feature is switched off by default
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


def hold_contract(document_id: str, filename: str = "contract.pdf") -> None:
    """A held contract document (role CONTRACT_DOCUMENT) the queries' evidence search looks in."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                document_id,
                filename,
                document_id.encode().hex().ljust(64, "0")[:64],
                1,
                filename,
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO document_classification(document_id,document_role,suggested_by) VALUES (?,?,?)",
            (document_id, "CONTRACT_DOCUMENT", "rules"),
        )


def cited(item_id: str, doc: str = "lib-cited") -> list[dict]:
    """Verified, current evidence on a held page and the citation of it: a draft is approved only if it cites evidence like this."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (doc, "c.pdf", doc.encode().hex().ljust(64, "0")[:64], 1, "c.pdf", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            (doc, 1, "The limit is 12 bar.", 20, 0, 1),
        )
    added = add_evidence(item_id, doc, "The limit is 12 bar.", 1, 1, None, frozenset({doc}), "owner", True, False, "owner")
    evidence_id = added["evidence"][-1]["id"]
    update_evidence(item_id, evidence_id, "verified", "current", None, "owner", "owner", True, False, reviewer=True)
    return [{"evidence_id": evidence_id, "label": "S1", "document_id": doc, "page": 1, "exact_quote": "The limit is 12 bar."}]


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
        AccessScope(
            "u1", frozenset(), capabilities=frozenset({"admin", REVIEWER_CAPABILITY})
        ),
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

    hold_contract("contract-1")
    monkeypatch.setattr(
        "app.technical_query_questions._ask",
        lambda page_text: ["What is the permitted coating thickness?"],
    )

    def fake_search(question, **kwargs):
        captured["question"] = question
        # the query's own attachment is never searched; only the held contract is
        assert kwargs["document_id"] == "contract-1"
        return {"hits": []}

    monkeypatch.setattr("app.search.search", fake_search)
    result = prepare_evidence(
        item["id"], frozenset({"query-pdf", "contract-1"}), "u1", True, False, "u1"
    )
    assert "What is the permitted coating thickness?" in captured["question"]
    assert "[Attachment" not in captured["question"]
    # A cover note ("Please see attached.") is not a question (lead-4, 26 Nov 2026): the page says the question is in the attachment.
    assert result["extracted_question_main"] == ""
    assert "query.pdf" in result["email_question_note"]
    assert result["attachment_context"] == [
        {
            "filename": "query.pdf",
            "page": 1,
            "text": "What is the permitted coating thickness?",
        }
    ]
    assert "What is the permitted coating thickness?" in result["proposed_question"]
    assert "[Attachment" not in result["proposed_question"]
    # each question is proposed on its own, with its file and page, for the engineer to confirm
    assert result["proposed_questions"] == [
        {
            "question": "What is the permitted coating thickness?",
            "filename": "query.pdf",
            "page": 1,
        }
    ]
    assert result["confirmed_question"] is None
    assert result["evidence"] == []
    assert (
        result["evidence_coverage"]["line"] == "Searched 1 of 1 contracts, hits in 0. No held standard that you may read: none was searched."
    )
    repeated = prepare_evidence(
        item["id"], frozenset({"query-pdf", "contract-1"}), "u1", True, False, "u1"
    )
    assert repeated["extracted_question"] == result["extracted_question"]
    assert repeated["proposed_question"] == result["proposed_question"]


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
            (
                "lib-doc",
                "standard.pdf",
                "a1" * 32,
                1,
                "standard.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("lib-doc", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    hold_contract("lib-doc")
    item, _ = import_message(envelope("twice"), "u1", False, False)
    monkeypatch.setattr(
        "app.search.search",
        lambda question, **_k: {
            "hits": [
                {
                    "document_id": "lib-doc",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "The limit is 12 bar.",
                }
            ]
        },
    )
    for _ in range(3):
        result = prepare_evidence(
            item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1"
        )
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["supersession_state"] == "unknown"
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET confirmed_by='u1' WHERE document_id='lib-doc'"
        )
    result = prepare_evidence(
        item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1"
    )
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["supersession_state"] == "current"
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET superseded_by='newer' WHERE document_id='lib-doc'"
        )
    result = prepare_evidence(
        item["id"], frozenset({"lib-doc"}), "u1", True, False, "u1"
    )
    assert result["evidence"][0]["supersession_state"] == "superseded"


def test_prepare_evidence_does_not_search_the_querys_own_attachment(monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "own-attachment",
                "query.pdf",
                "e" * 64,
                1,
                "query.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
    item, _ = import_message(envelope("scope-check"), "u1", False, False)
    link_attachment(
        item["id"],
        item["messages"][0]["attachments"][0]["id"],
        "own-attachment",
        "u1",
        "u1",
        True,
        False,
    )
    seen = {}

    hold_contract("library-doc")
    hold_contract(
        "own-attachment"
    )  # even a contract-role attachment is never searched: it is the contractor's own paper

    def fake_search(question, **kwargs):
        seen.setdefault("scopes", []).append(kwargs["allowed_document_ids"])
        return {"hits": []}

    monkeypatch.setattr("app.search.search", fake_search)
    # Another query's attachment is just as much a contractor paper.
    other_envelope = envelope("other-query")
    other_envelope["provider_thread_id"] = "thread-other"
    other, _ = import_message(other_envelope, "u1", False, False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "other-attachment",
                "other.pdf",
                "f1" * 32,
                1,
                "other.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
    link_attachment(
        other["id"],
        other["messages"][0]["attachments"][0]["id"],
        "other-attachment",
        "u1",
        "u1",
        True,
        False,
    )
    hold_contract("other-attachment")
    prepare_evidence(
        item["id"],
        frozenset({"own-attachment", "other-attachment", "library-doc"}),
        "u1",
        True,
        False,
        "u1",
    )
    assert seen["scopes"] == [frozenset({"library-doc"})]


def test_quote_matches_a_clause_the_pdf_wrapped_across_lines_but_not_a_changed_number():
    from app.technical_queries import _quote_on_pages

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                "wrapped-source",
                "standard.pdf",
                "f" * 64,
                1,
                "standard.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            (
                "wrapped-source",
                1,
                "4.2 Carbon steel shall receive a total dry film\nthickness of not less than 280 micrometres.\n",
                90,
                0,
                1,
            ),
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
    item = add_draft(item["id"], "Answer for review", [], [], "u1", "u1", False, False, citations=cited(item["id"]))
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
            reviewer=True,
        )
    with pytest.raises(ValueError, match="latest draft"):
        decide(
            item["id"],
            "approve",
            "owner",
            None,
            None,
            "owner",
            True,
            False,
            reviewer=True,
        )
    approved = decide(
        item["id"],
        "approve",
        "owner",
        None,
        latest_id,
        "owner",
        True,
        False,
        reviewer=True,
    )
    assert approved["status"] == "approved"


def test_unverified_provider_claim_and_unconnected_send_are_refused():
    scope = AccessScope(
        "u1", frozenset(), capabilities=frozenset({"admin", REVIEWER_CAPABILITY})
    )
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
    scope = AccessScope(
        "u1", frozenset(), capabilities=frozenset({"admin", REVIEWER_CAPABILITY})
    )
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
        reviewer=True,
    )
    scope = AccessScope("u1", frozenset({"doc-2"}))
    monkeypatch.setattr(
        "app.answer.answer",
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
    seen_questions = []
    original_answer = __import__("app.answer", fromlist=["answer"]).answer

    def spying_answer(question, *_args, **_kwargs):
        seen_questions.append(question)
        return original_answer(question)

    # Nothing is drafted from a question no engineer has confirmed.
    with pytest.raises(HTTPException) as unconfirmed:
        generate_query_draft(item["id"], scope)
    assert unconfirmed.value.status_code == 409
    assert "confirm the question" in unconfirmed.value.detail["message"]
    confirm_question(
        item["id"],
        "What is the approved limit?",
        "u1",
        False,
        False,
        "u1",
        reviewer=True,
    )
    monkeypatch.setattr("app.answer.answer", spying_answer)
    with pytest.raises(HTTPException) as blocked:
        generate_query_draft(item["id"], scope)
    assert blocked.value.status_code == 409
    assert "outside the query's verified evidence" in blocked.value.detail["message"]
    assert seen_questions == ["What is the approved limit?"]
    assert get(item["id"], "u1", False, False)["drafts"] == []
    monkeypatch.setattr(
        "app.answer.answer",
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


def test_confirming_a_question_keeps_the_email_and_rejects_empty_or_late_changes():
    item, _ = import_message(envelope("confirm-q"), "u1", False, False)
    assert item["confirmed_question"] is None
    confirmed = confirm_question(
        item["id"], "  What coating applies?  ", "u1", False, False, "u1", reviewer=True
    )
    assert confirmed["confirmed_question"] == "What coating applies?"
    assert confirmed["confirmed_question_by"] == "u1"
    assert (
        confirmed["extracted_question"]
        == "Please confirm the applicable coating schedule."
    )
    assert (
        confirmed["messages"][0]["body"]
        == "Please confirm the applicable coating schedule."
    )
    with pytest.raises(ValueError):
        confirm_question(item["id"], "   ", "u1", False, False, "u1", reviewer=True)
    with pytest.raises(ValueError):
        confirm_question(
            item["id"], "x" * 5001, "u1", False, False, "u1", reviewer=True
        )
    drafted = add_draft(item["id"], "Answer", [], [], "owner", "owner", True, False, citations=cited(item["id"]))
    decide(
        item["id"],
        "approve",
        "owner",
        None,
        drafted["drafts"][-1]["id"],
        "owner",
        True,
        False,
        reviewer=True,
    )
    with pytest.raises(ValueError):
        confirm_question(
            item["id"],
            "Changed after approval",
            "u1",
            False,
            False,
            "u1",
            reviewer=True,
        )


def test_refusal_reason_from_the_answer_checks_reaches_the_engineer(monkeypatch):
    item, _ = import_message(envelope("refusal-reason"), "u1", False, False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("doc-r", "r.pdf", "c3" * 32, 1, "r.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("doc-r", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    add_evidence(
        item["id"],
        "doc-r",
        "The limit is 12 bar.",
        1,
        1,
        None,
        frozenset({"doc-r"}),
        "u1",
        True,
        False,
        "u1",
    )
    update_evidence(
        item["id"],
        get(item["id"], "u1", True, False)["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        True,
        False,
        reviewer=True,
    )
    confirm_question(
        item["id"], "What is QX-1?", "u1", True, False, "u1", reviewer=True
    )
    monkeypatch.setattr(
        "app.answer.answer",
        lambda *_a, **_k: {
            "answer_type": "insufficient_evidence",
            "answer": None,
            "reason": "QX-1 does not appear anywhere in the indexed documents",
        },
    )
    with pytest.raises(HTTPException) as refused:
        generate_query_draft(
            item["id"],
            AccessScope(
                "u1",
                frozenset({"doc-r"}),
                capabilities=frozenset({"admin", REVIEWER_CAPABILITY}),
            ),
        )
    assert refused.value.status_code == 409
    assert "QX-1 does not appear anywhere" in refused.value.detail["message"]


def test_a_proposed_question_is_the_emails_own_or_the_models_numbered_questions_never_a_copy_of_the_pages():
    from app.technical_queries import original_email_question, propose_question

    proposals = [
        {"question": "Confirm the thickness.", "filename": "q.pdf", "page": 1},
        {"question": "State the standard.", "filename": "q.pdf", "page": 2},
    ]
    assert (
        propose_question("Please confirm the thickness.", proposals)
        == "Please confirm the thickness.\n1. State the standard."
    )  # what the email already says is not said twice
    assert (
        propose_question("", proposals)
        == "1. Confirm the thickness.\n2. State the standard."
    )
    assert propose_question("", []) == ""
    legacy = "Email part.\n\n[Attachment q.pdf, page 1]\nPDF text"
    assert original_email_question(legacy) == "Email part."
    assert original_email_question("[Attachment q.pdf, page 1]\nPDF text") == ""


def _attachment_evidence(item_id_suffix: str):
    """A query whose attachment document also holds a stored 'verified' evidence row,
    as older code saved it."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                f"att-{item_id_suffix}",
                "att.pdf",
                item_id_suffix.ljust(64, "9")[:64],
                1,
                "att.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            (f"att-{item_id_suffix}", 1, "Contractor wrote 99 bar.", 24, 0, 1),
        )
    item, _ = import_message(envelope(f"stale-{item_id_suffix}"), "u1", False, False)
    link_attachment(
        item["id"],
        item["messages"][0]["attachments"][0]["id"],
        f"att-{item_id_suffix}",
        "u1",
        "u1",
        True,
        False,
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,supersession_state,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"ev-{item_id_suffix}",
                item["id"],
                f"att-{item_id_suffix}",
                1,
                1,
                "Contractor wrote 99 bar.",
                "h",
                "current",
                "2026-01-01T00:00:00Z",
            ),
        )
    return item


def test_old_evidence_from_a_contractor_attachment_needs_review_and_blocks_approval_and_send():
    item = _attachment_evidence("a1")
    ensure_schema()  # the startup sweep
    row = get(item["id"], "owner", True, False)["evidence"][0]
    assert row["evidence_state"] == "needs_review"
    drafted = add_draft(
        item["id"], "Answer", [], [], "owner", "owner", True, False, citations=cited(item["id"])
    )
    with pytest.raises(ValueError, match="needs a reviewer's decision before approval"):
        decide(
            item["id"],
            "approve",
            "owner",
            None,
            drafted["drafts"][-1]["id"],
            "owner",
            True,
            False,
            reviewer=True,
        )
    with pytest.raises(ValueError, match="before sending"):
        validate_send_evidence(
            get(item["id"], "owner", True, False), frozenset({"att-a1"}), False
        )
    # The contractor-facing file does not carry it.
    from pathlib import Path

    path = render_query_docx(
        get(item["id"], "owner", True, False), Path(settings.data_dir) / "stale.docx"
    )
    with ZipFile(path) as package:
        assert (
            "Contractor wrote 99 bar" not in package.read("word/document.xml").decode()
        )
    # A reviewer's decision stands: a later sweep does not undo it.
    update_evidence(
        item["id"],
        "ev-a1",
        "rejected",
        "current",
        None,
        "owner",
        "owner",
        True,
        False,
        reviewer=True,
    )
    ensure_schema()
    assert (
        get(item["id"], "owner", True, False)["evidence"][0]["evidence_state"]
        == "rejected"
    )
    validate_send_evidence(
        get(item["id"], "owner", True, False), frozenset({"att-a1", "lib-cited"}), False
    )
    decide(
        item["id"],
        "approve",
        "owner",
        None,
        drafted["drafts"][-1]["id"],
        "owner",
        True,
        False,
        reviewer=True,
    )


def test_conflicting_or_ambiguous_evidence_blocks_approval_and_send_until_resolved():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            ("lib-c", "c.pdf", "d4" * 32, 1, "c.pdf", "ready", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("lib-c", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    item, _ = import_message(envelope("conflict-block"), "owner", True, False)
    added = add_evidence(
        item["id"],
        "lib-c",
        "The limit is 12 bar.",
        1,
        1,
        None,
        frozenset({"lib-c"}),
        "owner",
        True,
        False,
        "owner",
    )
    evidence_id = added["evidence"][0]["id"]
    drafted = add_draft(
        item["id"], "Answer", [], [], "owner", "owner", True, False, citations=[{"evidence_id": evidence_id}]
    )
    draft_id = drafted["drafts"][-1]["id"]
    for state in ("conflicting", "ambiguous"):
        update_evidence(
            item["id"],
            evidence_id,
            state,
            "current",
            None,
            "owner",
            "owner",
            True,
            False,
            reviewer=True,
        )
        with pytest.raises(ValueError, match=f"marked {state}"):
            decide(
                item["id"],
                "approve",
                "owner",
                None,
                draft_id,
                "owner",
                True,
                False,
                reviewer=True,
            )
        with pytest.raises(ValueError, match="before sending"):
            validate_send_evidence(
                get(item["id"], "owner", True, False), frozenset({"lib-c"}), False
            )
    update_evidence(
        item["id"],
        evidence_id,
        "verified",
        "current",
        None,
        "owner",
        "owner",
        True,
        False,
        reviewer=True,
    )
    decide(
        item["id"],
        "approve",
        "owner",
        None,
        draft_id,
        "owner",
        True,
        False,
        reviewer=True,
    )


def test_an_attachment_row_a_person_added_by_hand_is_not_swept():
    item = _attachment_evidence("a2")
    with db.connect() as conn:
        conn.execute("DELETE FROM query_evidence")
    added = add_evidence(
        item["id"],
        "att-a2",
        "Contractor wrote 99 bar.",
        1,
        1,
        None,
        frozenset({"att-a2"}),
        "owner",
        True,
        False,
        "owner",
    )
    ensure_schema()
    assert (
        get(item["id"], "owner", True, False)["evidence"][0]["evidence_state"]
        == "verified"
    )
    assert added["evidence"][0]["evidence_state"] == "verified"


def test_only_a_qualified_reviewer_may_confirm_decide_classify_or_send():
    item, _ = import_message(envelope("reviewer-gate"), "owner", True, False)
    with pytest.raises(PermissionError, match="qualified technical-query reviewer"):
        confirm_question(item["id"], "A question?", "owner", True, False, "owner")
    with pytest.raises(PermissionError, match="qualified technical-query reviewer"):
        update_evidence(
            item["id"], "x", "verified", "current", None, "owner", "owner", True, False
        )
    with pytest.raises(PermissionError, match="qualified technical-query reviewer"):
        decide(item["id"], "approve", "owner", None, "d", "owner", True, False)
    admin_only = AccessScope("owner", frozenset(), capabilities=frozenset({"admin"}))
    from app.api.technical_queries import (
        DecisionIn,
        QuestionIn,
        confirm_query_question,
        decide_query,
    )

    with pytest.raises(HTTPException) as denied:
        confirm_query_question(
            item["id"], QuestionIn(question="A question?"), admin_only
        )
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        decide_query(
            item["id"], DecisionIn(decision="approve", draft_id="d"), admin_only
        )
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        prepare_query_send(
            item["id"],
            SendIn(draft_id="d", mailbox_id="m", idempotency_key="k" * 16),
            admin_only,
        )
    assert denied.value.status_code == 409  # sending is refused for everyone
    reviewer = AccessScope(
        "owner", frozenset(), capabilities=frozenset({REVIEWER_CAPABILITY})
    )
    confirmed = confirm_query_question(
        item["id"], QuestionIn(question="A question?"), reviewer
    )
    assert confirmed["confirmed_question"] == "A question?"
    assert confirmed["can_review"] is True


def test_admin_grants_and_revokes_the_reviewer_role_but_not_to_themselves():
    from app.technical_queries import list_reviewers, set_reviewer

    admin = {"id": "owner", "email": "owner@example.test"}
    assert list_reviewers() == []
    with pytest.raises(PermissionError, match="themselves"):
        set_reviewer("owner", True, admin)
    assert set_reviewer("u1", True, admin) is True
    assert [row["id"] for row in list_reviewers()] == ["u1"]
    assert set_reviewer("nobody", True, admin) is False
    from app import access as access_mod

    assert REVIEWER_CAPABILITY in access_mod.scope_for_user("u1").capabilities
    assert set_reviewer("u1", False, admin) is True
    assert REVIEWER_CAPABILITY not in access_mod.scope_for_user("u1").capabilities
    assert list_reviewers() == []
    with db.connect() as conn:
        actions = [
            r["action"]
            for r in conn.execute("SELECT action FROM audit_events ORDER BY id")
        ]
    assert actions[-2:] == [
        "technical_query_reviewer_granted",
        "technical_query_reviewer_revoked",
    ]


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
            (
                "doc-internal-id",
                "SYN-STD-001.pdf",
                "b2" * 32,
                1,
                "x.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("doc-internal-id", 1, "The limit is 12 bar.", 20, 0, 1),
        )
    item, _ = import_message(envelope("word-names"), "u1", False, False)
    add_evidence(
        item["id"],
        "doc-internal-id",
        "The limit is 12 bar.",
        1,
        1,
        None,
        frozenset({"doc-internal-id"}),
        "u1",
        True,
        False,
        "u1",
    )
    item = add_draft(
        item["id"], "First line.\nSecond line.", [], [], "u1", "u1", True, False
    )
    path = render_query_docx(item, tmp_path / "names.docx")
    with ZipFile(path) as package:
        document = package.read("word/document.xml").decode()
    assert "SYN-STD-001.pdf" in document
    assert "doc-internal-id" not in document
    assert "Status:" not in document
    assert "First line.</w:t></w:r><w:r><w:br/></w:r><w:r><w:t" in document


def test_word_response_separates_email_question_attachment_text_and_confirmed_question(
    tmp_path,
):
    item, _ = import_message(envelope("word-sections"), "u1", False, False)
    drafted = add_draft(item["id"], "The answer.", [], [], "u1", "u1", True, False)
    drafted["attachment_context"] = [
        {"filename": "q.pdf", "page": 2, "text": "Attachment line."}
    ]
    drafted["confirmed_question"] = "Confirmed wording?"
    path = render_query_docx(drafted, tmp_path / "sections.docx")
    with ZipFile(path) as package:
        document = package.read("word/document.xml").decode()
    assert "Original question (from the email)" in document
    assert "Please confirm the applicable coating schedule." in document
    assert "Attachment text: q.pdf, page 2" in document
    assert "Question answered (confirmed by the engineer)" in document
    assert "Confirmed wording?" in document
    assert "[Attachment" not in document
    assert "Assumptions" not in document and "Unresolved points" not in document


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
            AccessScope(
                "owner",
                frozenset(),
                capabilities=frozenset({"admin", REVIEWER_CAPABILITY}),
            )
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
        reviewer=True,
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
    assert "gmail.send" not in url
    state = url.split("state=", 1)[1].split("&", 1)[0]
    assert gmail_auth.validate_state(state) == "u1"
    assert gmail_auth.consume_state(state) == "u1"
    assert gmail_auth.consume_state(state) is None


def test_gmail_oauth_uses_application_settings_when_shell_env_is_empty(monkeypatch):
    for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "gmail_client_id", "synthetic-settings-client")
    monkeypatch.setattr(settings, "gmail_client_secret", "synthetic-settings-secret")
    monkeypatch.setattr(
        settings,
        "gmail_redirect_uri",
        "http://127.0.0.1:8110/api/technical-queries/providers/gmail/oauth/callback",
    )
    assert gmail_auth._config() == (
        "synthetic-settings-client",
        settings.gmail_redirect_uri,
    )
    assert gmail_auth._client_secret() == "synthetic-settings-secret"


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


def _routed_envelope(message_id, sender, **extra):
    data = envelope(message_id)
    data["provider_thread_id"] = "thread-" + message_id
    data["from_address"] = sender
    data.update(extra)
    return data


def test_routing_rules_fill_blank_fields_by_address_then_domain_and_keep_what_the_message_says():
    from app.technical_queries import list_routing_rules, set_routing_rule

    set_routing_rule(
        "domain", "Acme-Contractor.test", "Acme Contractors", "Piping", "u1", True
    )
    set_routing_rule(
        "address",
        "chief@acme-contractor.test",
        "Acme Contractors",
        "Process",
        "u1",
        True,
    )
    by_address, _ = import_message(
        _routed_envelope("r1", "Chief Engineer <Chief@Acme-Contractor.test>"),
        "u1",
        False,
        False,
    )
    assert (by_address["contractor_name"], by_address["department"]) == (
        "Acme Contractors",
        "Process",
    )
    assert by_address["routing_source"].startswith("rule:")
    by_domain, _ = import_message(
        _routed_envelope("r2", "clerk@acme-contractor.test"), "u1", False, False
    )
    assert by_domain["department"] == "Piping"
    kept, _ = import_message(
        _routed_envelope("r3", "clerk@acme-contractor.test", department="Civil"),
        "u1",
        False,
        False,
    )
    assert (kept["contractor_name"], kept["department"]) == (
        "Acme Contractors",
        "Civil",
    )
    unknown, _ = import_message(
        _routed_envelope("r4", "someone@elsewhere.test"), "u1", False, False
    )
    assert unknown["contractor_name"] is None and unknown["routing_source"] is None
    from app.technical_queries import triage_query

    triaged = triage_query(
        by_domain["id"], "Other Co", "Mechanical", "normal", None, "owner", True, False
    )
    assert triaged["routing_source"] == "manual"
    assert len(list_routing_rules()) == 2


def test_routing_rules_refuse_public_mail_domains_bad_input_and_non_admins():
    from app.technical_queries import delete_routing_rule, set_routing_rule

    with pytest.raises(ValueError, match="public mail domain"):
        set_routing_rule("domain", "gmail.com", "X", None, "u1", True)
    with pytest.raises(ValueError, match="full email address"):
        set_routing_rule("address", "no-at-sign", "X", None, "u1", True)
    with pytest.raises(ValueError, match="company domain"):
        set_routing_rule("domain", "localhost", "X", None, "u1", True)
    with pytest.raises(ValueError, match="contractor, a department"):
        set_routing_rule("address", "a@b.test", " ", None, "u1", True)
    with pytest.raises(PermissionError):
        set_routing_rule("address", "a@b.test", "X", None, "u1", False)
    with pytest.raises(PermissionError):
        delete_routing_rule("nope", False)
    # an exact address on a public service is allowed
    rules = set_routing_rule(
        "address", "person@gmail.com", "Sole Trader", None, "u1", True
    )
    assert rules[0]["match_value"] == "person@gmail.com"
    assert delete_routing_rule(rules[0]["id"], True) == []


def test_complete_workflow_from_email_to_resolution(monkeypatch, tmp_path):
    """The whole path through the real route functions: an email with a PDF attachment, evidence,
    a confirmed question, a cited draft, review, the Word file, the send route refusing, resolution.
    Only search, the answer model and Gmail are replaced."""
    import json

    import pymupdf

    from app.api.technical_queries import (
        DecisionIn,
        QuestionIn,
        confirm_query_question,
        confirm_query_resolution,
        decide_query,
        prepare_query_evidence,
        query_response_docx,
    )

    clause = "4.2 Carbon steel exposed to marine atmosphere shall receive three coats."
    attachment_pdf = tmp_path / "question.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "What coating does carbon steel need?")
    pdf.save(str(attachment_pdf))
    pdf.close()
    with db.connect() as conn:
        for doc_id, name, path in (
            ("lib-e2e", "SYN-COATING.pdf", "lib.pdf"),
            ("att-e2e", "question.pdf", str(attachment_pdf)),
        ):
            conn.execute(
                "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
                (
                    doc_id,
                    name,
                    doc_id.ljust(64, "0")[:64],
                    1,
                    path,
                    "2026-01-01T00:00:00Z",
                ),
            )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            (
                "lib-e2e",
                2,
                "4 Coating\n" + clause.replace("exposed to", "exposed\nto") + "\n",
                90,
                0,
                1,
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
            ("att-e2e", 1, "What coating does carbon steel need?", 36, 0, 1),
        )
        conn.execute(
            "INSERT INTO document_classification(document_id,document_role,suggested_by,confirmed_by) VALUES (?,?,?,?)",
            ("lib-e2e", "CONTRACT_DOCUMENT", "rules", "owner"),
        )
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "mb-e2e",
                "owner",
                "engineering@example.test",
                "h1",
                "Label_TQ",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
    reviewer = AccessScope(
        "owner",
        frozenset({"lib-e2e", "att-e2e"}),
        capabilities=frozenset({"admin", REVIEWER_CAPABILITY}),
    )
    plain_admin = AccessScope(
        "owner", frozenset({"lib-e2e", "att-e2e"}), capabilities=frozenset({"admin"})
    )

    # 1. the email arrives, routed by a rule, with its attachment checked
    set_routing = __import__("app.technical_queries", fromlist=["x"]).set_routing_rule
    set_routing(
        "domain", "contractor.example", "Example Contractor", "Piping", "owner", True
    )
    data = envelope("e2e")
    data.update(
        from_address="engineer@contractor.example", body="See attached.", question=None
    )
    item, _ = import_message(data, "owner", True, False)
    assert (item["contractor_name"], item["department"]) == (
        "Example Contractor",
        "Piping",
    )
    linked = link_attachment(
        item["id"],
        item["messages"][0]["attachments"][0]["id"],
        "att-e2e",
        "owner",
        "owner",
        True,
        False,
    )
    assert (
        linked["messages"][0]["attachments"][0]["scan_status"] == "static_check_clean"
    )

    # 2. evidence is found in the library, never in the attachment
    monkeypatch.setattr(
        "app.technical_query_questions._ask",
        lambda page_text: ["What coating does carbon steel need?"],
    )
    monkeypatch.setattr(
        "app.search.search",
        lambda question, **kw: {
            "hits": [
                {
                    "document_id": "lib-e2e",
                    "page_start": 2,
                    "page_end": 2,
                    "text": clause,
                },
                {
                    "document_id": "att-e2e",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "What coating does carbon steel need?",
                },
            ]
        },
    )
    queued = prepare_query_evidence(item["id"], reviewer)
    assert queued["evidence_job"]["state"] == "queued"  # the request only queues the job and answers at once
    from app import technical_query_jobs

    technical_query_jobs.run_job(queued["evidence_job"]["id"], wait_for_review=False)
    prepared = get(item["id"], "owner", True, False)
    assert prepared["evidence_job"]["state"] == "done"
    # a passage the search found is only PROPOSED: no person has judged that it answers the question
    assert [
        (e["document_id"], e["evidence_state"], e["supersession_state"])
        for e in prepared["evidence"]
    ] == [("lib-e2e", "proposed", "current")]
    # a reviewer reads the passage and keeps it as evidence; only then can a draft rest on it
    update_evidence(
        item["id"],
        prepared["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "owner",
        "owner",
        True,
        False,
        reviewer=True,
    )
    # the cover note "See attached." is not a question (lead-4, 26 Nov 2026)
    assert prepared["proposed_question"] == "1. What coating does carbon steel need?"
    assert (
        prepared["evidence_coverage"]["line"] == "Searched 1 of 1 contracts, hits in 1. No held standard that you may read: none was searched."
    )

    # 3. nothing is drafted until a reviewer confirms the question
    with pytest.raises(HTTPException) as early:
        generate_query_draft(item["id"], reviewer)
    assert "confirm the question" in early.value.detail["message"]
    with pytest.raises(HTTPException) as not_reviewer:
        confirm_query_question(
            item["id"], QuestionIn(question="What coating applies?"), plain_admin
        )
    assert not_reviewer.value.status_code == 403
    confirm_query_question(
        item["id"],
        QuestionIn(question="What coating applies to carbon steel?"),
        reviewer,
    )
    asked = {}

    def fake_answer(question, **kwargs):
        asked["question"], asked["scope"] = question, kwargs["allowed_document_ids"]
        return {
            "answer_type": "generated",
            "answer": "Three coats [S1].",
            "cited": [1],
            "passages": [
                {
                    "document_id": "lib-e2e",
                    "page_start": 2,
                    "page_end": 2,
                    "text": clause,
                }
            ],
            "model": "synthetic-model",
        }

    monkeypatch.setattr("app.answer.answer", fake_answer)
    drafted = generate_query_draft(item["id"], reviewer)
    assert asked == {
        "question": "What coating applies to carbon steel?",
        "scope": frozenset({"lib-e2e"}),
    }
    assert drafted["status"] == "awaiting_review"
    assert (
        json.loads(drafted["drafts"][-1]["citations_json"])[0]["exact_quote"] == clause
    )

    # 4. only a reviewer approves; then the Word file carries the pieces apart
    draft_id = drafted["drafts"][-1]["id"]
    with pytest.raises(HTTPException) as refused:
        decide_query(
            item["id"], DecisionIn(decision="approve", draft_id=draft_id), plain_admin
        )
    assert refused.value.status_code == 403
    assert (
        decide_query(
            item["id"], DecisionIn(decision="approve", draft_id=draft_id), reviewer
        )["status"]
        == "approved"
    )
    docx = query_response_docx(item["id"], reviewer)
    with ZipFile(docx.path) as package:
        word = package.read("word/document.xml").decode()
    for expected in (
        "Technical Query Response",
        # "See attached." is a cover note, not a question
        "No question in the email text. The question is in the attachment: query.pdf",
        "Attachment text: query.pdf, page 1",
        "Question answered (confirmed by the engineer)",
        "Three coats [S1].",
        "SYN-COATING.pdf",
    ):
        assert expected in word
    assert "DRAFT" not in word and "lib-e2e" not in word and "[Attachment" not in word

    # 5. nothing is emailed from here: the send route only refuses; the engineer hands the Word file over and closes the query
    with pytest.raises(HTTPException) as no_send:
        prepare_query_send(
            item["id"],
            SendIn(draft_id=draft_id, mailbox_id="mb-e2e", idempotency_key="k" * 16),
            reviewer,
        )
    assert no_send.value.status_code == 409 and "not approved by the owner" in str(
        no_send.value.detail
    )
    resolved = confirm_query_resolution(item["id"], reviewer)
    assert resolved["status"] == "resolved"
    with db.connect() as conn:
        events = [
            r["event"]
            for r in conn.execute(
                "SELECT event FROM query_events WHERE query_id=? ORDER BY created_at",
                (item["id"],),
            )
        ]
    for expected in ("evidence_prepared", "question_confirmed", "decision"):
        assert expected in events
