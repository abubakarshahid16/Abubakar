"""TEST send of a query's draft to the owner's OWN mailbox (owner, 26 Nov 2026 23:14 PKT): only the mailbox the query was imported from,
never another recipient, never Cc or Bcc (two locks in code), the subject marked TEST, only with the switch on and the mailbox's separate
re-grant of gmail.send. Sending to a contractor stays off. Invented addresses; no network (fake transport and token store)."""

from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage

import pytest

from app import db, gmail_auth
from app import technical_queries as tq
from app import technical_query_test_send as T
from app.config import settings
from app.gmail_client import GmailApiClient
from tests.test_technical_queries import envelope
from tests.test_tq_g_feature_off import (  # noqa: F401 - storage: the autouse database fixture
    on,
    storage,
)

OWN = "queries@example.test"


class _Store:
    def __init__(self):
        self.saved = {}

    def save_refresh_token(self, mailbox_id, token):
        self.saved[mailbox_id] = token


class _Sender:
    """A Gmail client whose transport records the request instead of calling Google."""

    def __init__(self):
        self.calls = []

    def __call__(self, mailbox_id):
        def transport(method, url, **kwargs):
            self.calls.append((method, url, kwargs.get("json")))

            class R:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"id": "sent-1"}

            return R()

        return GmailApiClient("invented-token", transport=transport)


@pytest.fixture
def gmail_query(monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_test_send_enabled", True)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) "
            "VALUES ('mb1','u1',?,'h1','L1','active','x','x')",
            (OWN,),
        )
    item, _ = tq.import_message(
        {**envelope("send-1"), "provider": "gmail", "mailbox_id": "mb1"},
        "u1",
        False,
        False,
    )
    item = tq.add_draft(
        item["id"],
        "Class 300 applies [S1].",
        [],
        [],
        "u1",
        "u1",
        False,
        False,
        model="synthetic-local",
    )
    return item


def _grant():
    with db.connect() as conn:
        conn.execute(
            "UPDATE gmail_mailboxes SET test_send_granted_at='x' WHERE id='mb1'"
        )


def _send(item, sender):
    return T.send(
        item["id"],
        item["drafts"][-1]["id"],
        "u1",
        False,
        False,
        "u1",
        reviewer=True,
        client_factory=sender,
    )


def test_the_test_send_goes_only_to_the_importing_mailbox_marked_test_with_no_cc_or_bcc(
    gmail_query,
):
    _grant()
    sender = _Sender()
    assert _send(gmail_query, sender)["sent_to"] == OWN
    [(method, url, payload)] = sender.calls
    assert method == "POST" and url.endswith("/messages/send")
    sent = message_from_bytes(
        base64.urlsafe_b64decode(payload["raw"]), policy=policy.default
    )
    assert (
        sent["To"] == OWN
        and sent["From"] == OWN
        and sent["Cc"] is None
        and sent["Bcc"] is None
    )
    assert sent["Subject"].startswith(T.TEST_MARK)
    assert sent.get_content().startswith("TEST ONLY.")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT state,to_addresses,cc_addresses FROM query_sends WHERE query_id=?",
            (gmail_query["id"],),
        ).fetchone()
    assert tuple(row) == ("test_sent", f'["{OWN}"]', "[]")
    assert (
        tq.get(gmail_query["id"], "u1", False, False)["status"] == "awaiting_review"
    )  # a test send changes nothing about the query


@pytest.mark.parametrize(
    "headers",
    [
        {"To": "contractor@vendor.example"},
        {"To": f"{OWN}, contractor@vendor.example"},
        {"To": OWN, "Cc": "contractor@vendor.example"},
        {"To": OWN, "Bcc": "contractor@vendor.example"},
        {"To": OWN, "Resent-To": "contractor@vendor.example"},
    ],
)
def test_a_different_recipient_or_any_cc_or_bcc_is_refused_by_both_locks_before_google_is_called(
    headers,
):
    message = EmailMessage()
    message["From"] = OWN
    for name, value in headers.items():
        message[name] = value
    message["Subject"] = f"{T.TEST_MARK} x"
    message.set_content("x")
    with pytest.raises(PermissionError):
        T.only_self(message, OWN)  # lock 1, in the sender
    called = []
    client = GmailApiClient(
        "invented-token", transport=lambda *a, **k: called.append(1)
    )
    with pytest.raises(PermissionError):
        client.send_to_self(
            message.as_bytes(), OWN
        )  # lock 2, in the one module that may open the socket
    assert called == []


def test_nothing_is_sent_with_the_switch_off_without_the_re_grant_or_by_a_non_reviewer(
    gmail_query, monkeypatch
):
    sender = _Sender()
    with pytest.raises(ValueError, match="allow test sending"):  # not re-granted
        _send(gmail_query, sender)
    _grant()
    with pytest.raises(PermissionError):
        T.send(
            gmail_query["id"],
            gmail_query["drafts"][-1]["id"],
            "u1",
            False,
            False,
            "u1",
            reviewer=False,
            client_factory=sender,
        )
    monkeypatch.setattr(settings, "technical_query_test_send_enabled", False)
    with pytest.raises(PermissionError, match="switched off"):
        _send(gmail_query, sender)
    assert sender.calls == []


def test_a_query_typed_in_by_hand_has_no_own_mailbox_to_send_to(monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_test_send_enabled", True)
    item, _ = tq.import_message(
        envelope("by-hand"), "u1", False, False
    )  # provider synthetic: no Gmail mailbox
    item = tq.add_draft(item["id"], "x", [], [], "u1", "u1", False, False, model="m")
    with pytest.raises(ValueError, match="one Gmail mailbox"):
        _send(item, _Sender())


def test_connecting_stays_read_only_and_the_re_grant_adds_send_to_the_same_mailbox(
    gmail_query, monkeypatch
):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "invented-client")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:8000/cb")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "invented-secret")
    assert "gmail.send" not in gmail_auth.start(
        "u1"
    )  # the ordinary connect asks read only
    url = gmail_auth.start("u1", "test_send")
    assert "gmail.readonly" in url and "gmail.send" in url
    state = url.split("state=", 1)[1].split("&", 1)[0]
    store = _Store()
    granted = {
        "refresh_token": "r2",
        "access_token": "a2",
        "scope": f"{gmail_auth.SCOPES[0]} {gmail_auth.TEST_SEND_SCOPE}",
    }
    result = gmail_auth.complete("code", state, exchange=lambda d: granted, profile=lambda t: {"emailAddress": OWN, "historyId": "h2"},
                                 store=store)  # fmt: skip
    assert (
        result["mailbox_id"] == "mb1"
        and result["test_send"] == "granted"
        and store.saved == {"mb1": "r2"}
    )
    with db.connect() as conn:
        assert conn.execute(
            "SELECT test_send_granted_at FROM gmail_mailboxes WHERE id='mb1'"
        ).fetchone()[0]
        assert (
            conn.execute("SELECT COUNT(*) FROM gmail_mailboxes").fetchone()[0] == 1
        )  # the same mailbox, no second row
    # Google did not grant sending: nothing changes
    state2 = gmail_auth.start("u1", "test_send").split("state=", 1)[1].split("&", 1)[0]
    with pytest.raises(RuntimeError, match="did not grant sending"):
        gmail_auth.complete("code", state2, exchange=lambda d: {**granted, "scope": gmail_auth.SCOPES[0]},
                            profile=lambda t: {"emailAddress": OWN, "historyId": "h3"}, store=_Store())  # fmt: skip
    monkeypatch.setattr(settings, "technical_query_test_send_enabled", False)
    with pytest.raises(RuntimeError, match="switched off"):
        gmail_auth.start("u1", "test_send")
