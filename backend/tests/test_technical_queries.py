from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import db, gmail_auth
from app.access import AccessScope
from app.api.technical_queries import (
    ImportIn,
    SendIn,
    _safe_item,
    generate_query_draft,
    import_technical_query,
    prepare_query_send,
)
from app.config import settings
from app.gmail_client import GmailApiClient, normalize_message
from app.gmail_worker import process_history, send_approved
from app.technical_queries import (
    add_draft,
    add_evidence,
    decide,
    ensure_schema,
    get,
    import_message,
    update_evidence,
)


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
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://example.test/oauth/callback")
    url = gmail_auth.start("u1")
    assert "gmail.readonly" in url
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


def test_direct_send_is_refused_until_approved_content_binding_exists():
    item, _ = import_message(envelope("send-1"), None, False, True)

    class FakeClient:
        calls = 0

        def send(self, _raw):
            self.calls += 1
            return "provider-send-1"

    client = FakeClient()
    drafted = add_draft(item["id"], "Draft", [], [], None, None, False, True)
    draft_id = drafted["drafts"][0]["id"]
    decide(item["id"], "approve", None, None, draft_id, None, False, True)
    with pytest.raises(RuntimeError, match="disabled"):
        send_approved(
            client,
            item["id"],
            draft_id,
            ["contractor@example.test"],
            [],
            "Subject",
            "Body",
            "send-key",
        )
    assert client.calls == 0
