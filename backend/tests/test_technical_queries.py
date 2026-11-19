from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import HTTPException, UploadFile

from app import db, gmail_auth
from app.access import AccessScope
from app.api.technical_queries import (
    ImportIn,
    SendIn,
    _safe_item,
    download_original_query_email,
    generate_query_draft,
    import_technical_query,
    prepare_query_send,
    upload_query_attachment,
)
from app.config import settings
from app.gmail_client import GmailApiClient, GmailMessage, normalize_message
from app.gmail_worker import poll_mailbox, process_history, send_approved
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


def test_unverified_provider_claim_and_unconfigured_send_are_refused():
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
                to_addresses=["contractor@example.test"], idempotency_key="send-key-1"
            ),
            scope,
        )
    assert blocked_send.value.status_code == 503
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
    add_evidence(
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


def test_word_preview_marks_unapproved_response_and_missing_evidence(tmp_path):
    item, _ = import_message(envelope("word-preview"), "u1", False, False)
    item = add_draft(item["id"], "Proposed answer", [], [], "u1", "u1", False, False)
    path = render_query_docx(item, tmp_path / "preview.docx")
    with ZipFile(path) as package:
        document = package.read("word/document.xml").decode()
    assert "DRAFT Technical Query Response" in document
    assert "No verified source evidence" in document


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
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                "mailbox-1",
                "u1",
                "engineering@example.test",
                "h1",
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    class FakeClient:
        fail = True

        def history_delta(self, cursor):
            assert cursor == "h1"
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
