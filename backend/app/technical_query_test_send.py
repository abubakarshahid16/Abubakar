"""TEST send of a technical query's draft reply to the owner's OWN mailbox (owner, 26 Nov 2026 23:14 PKT: "When you are sending the email
back to me then there is no problem in it"; relayed by lead-4). It is a test of the reply, never a reply to the contractor: sending to a
contractor stays off until the owner writes "sending approved" (the send route only refuses; untouched).

Enforced in code, not by the screen:
- the ONLY recipient is the exact address of the Gmail mailbox the query was imported from; `send` takes no recipient at all;
- never a Cc or a Bcc; a message with any other recipient is refused here AND in `gmail_client.send_to_self` before Google is called;
- the subject starts with TEST_MARK and the body says, first, that it is a test;
- only while TECHNICAL_QUERY_TEST_SEND_ENABLED is on (off by default: this lane's way-back switch), only for a mailbox whose owner made
  the separate re-grant of the send scope (`gmail_auth.start(..., purpose="test_send")`), only by a technical-query reviewer;
- each send is recorded (query, draft, the address, when; state `test_sent`) and in the query's history.
"""

from __future__ import annotations

import json
import uuid
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any

from .config import settings
from .db import connect

TEST_MARK = "[TEST, not sent to the contractor]"
FIRST_LINE = (
    "TEST ONLY. This is the proposed reply to the technical query below, sent to your own mailbox so you can read it. "
    "Nothing was sent to the contractor. AI, to be checked."
)


def enabled() -> bool:
    return bool(getattr(settings, "technical_query_test_send_enabled", False))


def own_mailbox(conn, query_id: str) -> tuple[str, str]:
    """(mailbox id, address) of the ONE Gmail mailbox the query's mails were imported from, re-granted for test sending; else a plain
    refusal (a query typed in by hand, a mailbox not re-granted, or mails from more than one mailbox)."""
    boxes = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT mailbox_id FROM query_messages WHERE query_id=? AND provider='gmail' AND mailbox_id IS NOT NULL",
            (query_id,),
        )
    }
    if len(boxes) != 1:
        raise ValueError("a test send needs a query imported from one Gmail mailbox")
    row = conn.execute(
        "SELECT id, email, connection_state, test_send_granted_at FROM gmail_mailboxes WHERE id=?",
        (next(iter(boxes)),),
    ).fetchone()
    if row is None or row["connection_state"] != "active":
        raise ValueError("the mailbox this query came from is not connected")
    if not row["test_send_granted_at"]:
        raise ValueError(
            "allow test sending for this mailbox first (Technical queries, mailbox, Allow test sending)"
        )
    return row["id"], str(row["email"]).strip().lower()


def only_self(message: EmailMessage, address: str) -> None:
    """The first lock: the message's only recipient is `address`; no Cc, no Bcc, no resent header."""
    to = [a.strip().lower() for _n, a in getaddresses(message.get_all("To", []))]
    others = [
        h
        for h in message
        if h.lower() in {"cc", "bcc", "resent-to", "resent-cc", "resent-bcc"}
    ]
    if to != [address.strip().lower()] or others:
        raise PermissionError(
            "a test send goes only to the mailbox the query came from: no other recipient, no Cc, no Bcc"
        )


def build(address: str, item: dict[str, Any], draft: dict[str, Any]) -> EmailMessage:
    """The test message: to and from the mailbox itself, the subject marked, the body the draft and its sources."""
    message = EmailMessage()
    message["From"] = address
    message["To"] = address
    message["Subject"] = f"{TEST_MARK} {item.get('subject') or 'Technical query'}"
    try:
        citations = json.loads(draft.get("citations_json") or "[]")
    except ValueError:
        citations = []
    names = {
        e["id"]: (e.get("source_name") or e["document_id"])
        for e in item.get("evidence", [])
    }
    sources = [
        f"{c.get('label')}: {names.get(c.get('evidence_id'), c.get('document_id'))}, page {c.get('page')}"
        for c in citations
    ]
    question = (draft.get("question") or "").strip()
    lines = [
        FIRST_LINE,
        "",
        "What the contractor asks:",
        question,
        "",
        "Proposed reply:",
        draft.get("answer") or "",
    ]
    if sources:
        lines += ["", "Sources:", *sources]
    message.set_content("\n".join(lines))
    return message


def send(query_id: str, draft_id: str, user_id, is_admin: bool, unrestricted: bool, actor_user_id, *, reviewer: bool,
         client_factory=None) -> dict[str, Any]:  # fmt: skip
    """Send the query's draft `draft_id` as a TEST to the mailbox the query came from. Returns {sent_to, at}."""
    from . import technical_queries as tq

    if not enabled():
        raise PermissionError("test sending is switched off")
    tq._require_reviewer(reviewer, unrestricted, "send a test of the reply")
    item = tq.get(query_id, user_id, is_admin, unrestricted)
    if item is None:
        raise LookupError("technical query not found")
    draft = next((d for d in item.get("drafts", []) if d["id"] == draft_id), None)
    if draft is None:
        raise ValueError("the draft is not one of this query's drafts")
    with connect() as conn:
        mailbox_id, address = own_mailbox(conn, query_id)
    message = build(address, item, draft)
    only_self(message, address)
    if client_factory is None:
        from . import gmail_auth
        from .gmail_client import GmailApiClient

        def client_factory(mailbox: str):
            return GmailApiClient(gmail_auth.access_token(mailbox))

    sent = client_factory(mailbox_id).send_to_self(
        message.as_bytes(), address
    )  # the second lock is in the client
    at = tq.now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO query_sends(id,query_id,draft_id,idempotency_key,to_addresses,cc_addresses,state,provider_message_id,error,created_at) "
            "VALUES (?,?,?,?,?,?,'test_sent',?,NULL,?)",
            (
                str(uuid.uuid4()),
                query_id,
                draft_id,
                f"test-{uuid.uuid4()}",
                json.dumps([address]),
                "[]",
                str(sent.get("id") or ""),
                at,
            ),
        )
        tq._event(
            conn,
            query_id,
            "test_reply_sent",
            actor_user_id,
            f"draft={draft_id}; to the importing mailbox",
        )
    return {"sent_to": address, "at": at}
