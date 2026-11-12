"""The owner's yes for ONE contract upload, to send it to Claude (owner decision, 12 Nov 2026, #1584 comment 6820183348).

"Contracts: allowed on Local without asking; on Claude ask me once per upload and record my yes."

WHERE THE YES LIVES. In the one approved list (`claude_approved`, `<data_dir>/claude_approved_documents.json`), as a row with
`source` `contract_yes`, status `approved`, the file's sha256, the document id, WHO (`approved_by`) and WHEN (`approved_on`). So
the gate that every Claude call asks (`claude_approved.refusal`) already honours it, and a changed file (a new sha256) is not
covered: the new upload asks again. A withdrawn yes is the same row with status `withdrawn`, `withdrawn_by`, `withdrawn_on`.
Every grant and withdrawal is also an audit event (`contract_yes_granted`, `contract_yes_withdrawn`: ids and hashes, never a
title). The block list still wins: a blocked hash or name is refused here and at the gate.

ADMIN ONLY (the route checks; this module takes the actor's name). Opens no socket; reads no document text.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from . import claude_approved, claude_auto_approve
from .claude_approved import APPROVED, CONTRACT_YES_SOURCE, WITHDRAWN
from .db import connect

AUDIT_GRANTED = "contract_yes_granted"
AUDIT_WITHDRAWN = "contract_yes_withdrawn"
NEEDS_YES_WORDS = "needs the owner's yes for this upload"


class YesRefused(Exception):
    """The yes could not be recorded. The message is a plain sentence, never a document text."""


def _row(document_id: str):
    return (
        connect()
        .execute(
            "SELECT id, filename, sha256 FROM documents WHERE id = ?", (document_id,)
        )
        .fetchone()
    )


def _audit(action: str, actor: str, document_id: str, sha: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type,"
            " resource_id, outcome, detail) VALUES (?, NULL, ?, ?, ?, ?, 'ok', ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                actor,
                action,
                "document",
                document_id,
                json.dumps({"sha256": sha}, sort_keys=True),
            ),
        )


def _yes_rows(sha: str, rows: list[dict]) -> list[dict]:
    return [
        r
        for r in rows
        if str(r.get("sha256") or "").strip().lower() == sha
        and r.get("source") == CONTRACT_YES_SOURCE
    ]


def has_yes(document_id: str) -> bool:
    """Is there a standing yes for THIS file (its sha256) and is it still approved at the gate (not blocked, not withdrawn)?"""
    row = _row(document_id)
    sha = ((row["sha256"] if row else "") or "").strip().lower()
    if not sha:
        return False
    return sha in claude_approved.approved_hashes() and any(
        r.get("status") == APPROVED for r in _yes_rows(sha, claude_approved._entries())
    )


def grant(document_id: str, actor: str) -> dict:
    """Record the owner's yes for this upload. Raises `YesRefused` for an unknown document, one with no checksum, a blocked
    one, or an unreadable list. Idempotent: a standing yes is returned as it is."""
    row = _row(document_id)
    sha = ((row["sha256"] if row else "") or "").strip().lower()
    if row is None or not sha:
        raise YesRefused(
            "this document has no stored checksum, so a yes cannot be recorded for it"
        )
    today = datetime.now(UTC).date().isoformat()
    with claude_auto_approve._locked():
        try:
            data = claude_approved.read_list_strict()
            blocks = claude_approved.blocked_hashes()
            marked = claude_approved.marked_name_keys()
        except claude_approved.BlockListUnreadable as exc:
            raise YesRefused(
                f"the approved list or the block file has a fault ({exc}); nothing was recorded"
            ) from exc
        if sha in blocks or claude_approved.name_is_blocked(row["filename"], marked):
            raise YesRefused(
                "this file is blocked for the cloud model by name or checksum; a yes cannot lift a block"
            )
        rows = data["documents"]
        mine = _yes_rows(sha, rows)
        standing = [r for r in mine if r.get("status") == APPROVED]
        if standing:
            return standing[0]
        entry = {
            "sha256": sha,
            "document_id": document_id,
            "label": row["filename"],
            "status": APPROVED,
            "approved_by": actor,
            "approved_on": today,
            "source": CONTRACT_YES_SOURCE,
        }
        rows.append(entry)
        claude_auto_approve._write(data)
    _audit(AUDIT_GRANTED, actor, document_id, sha)
    return entry


def withdraw(document_id: str, actor: str) -> bool:
    """Withdraw the yes for this file. True when a standing yes was withdrawn."""
    row = _row(document_id)
    sha = ((row["sha256"] if row else "") or "").strip().lower()
    if not sha:
        return False
    today = datetime.now(UTC).date().isoformat()
    with claude_auto_approve._locked():
        data = claude_approved.read_list_strict()
        standing = [
            r for r in _yes_rows(sha, data["documents"]) if r.get("status") == APPROVED
        ]
        for r in standing:
            r.update(status=WITHDRAWN, withdrawn_by=actor, withdrawn_on=today)
        if standing:
            claude_auto_approve._write(data)
    if standing:
        _audit(AUDIT_WITHDRAWN, actor, document_id, sha)
    return bool(standing)


def record_of(document_id: str) -> dict | None:
    """Who, when and which document of the yes for this file (the standing one, else the last withdrawn); None when never given."""
    row = _row(document_id)
    sha = ((row["sha256"] if row else "") or "").strip().lower()
    if not sha:
        return None
    mine = _yes_rows(sha, claude_approved._entries())
    if not mine:
        return None
    pick = next((r for r in mine if r.get("status") == APPROVED), mine[-1])
    keys = (
        "document_id",
        "status",
        "approved_by",
        "approved_on",
        "withdrawn_by",
        "withdrawn_on",
    )
    return {k: pick.get(k) for k in keys if pick.get(k) is not None}
