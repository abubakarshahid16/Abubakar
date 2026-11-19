from __future__ import annotations

import pytest

from app import db, gmail_auth
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


def test_new_message_in_same_provider_thread_is_follow_up():
    first, _ = import_message(envelope("thread-message-1"), "u1", False, False)
    follow = envelope("thread-message-2")
    follow["body"] = "Additional information for the same question."
    second, duplicate = import_message(follow, "u1", False, False)
    assert duplicate is False
    assert second["id"] == first["id"]
    assert len(second["messages"]) == 2
    assert any(event["event"] == "follow_up_received" for event in second["events"])


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
    first = process_history(client, "history-1", None, mailbox_id="test-mailbox")
    second = process_history(client, "history-1", None, mailbox_id="test-mailbox")
    assert first[0]["duplicate"] is False
    assert second[0]["duplicate"] is True


def test_approved_send_is_idempotent_and_does_not_retry_unknown_outcome():
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
    assert (
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
        == "provider-send-1"
    )
    assert (
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
        == "provider-send-1"
    )
    assert client.calls == 1
