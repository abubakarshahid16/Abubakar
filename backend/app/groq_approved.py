"""Which documents' quotes may go to the second AI (Groq). Owner decision 17 Nov 2026 (#1584): no client document goes
outside without approval.

A SEPARATE LIST, `<data_dir>/groq_approved_documents.json`, outside git, edited by the owner only; the same shape as the
Claude list (`claude_approved`), by file sha256, so a changed revision is not approved by its predecessor:

    {"documents": [{"sha256": "...", "document_id": "doc_...", "label": "...", "status": "approved",
                    "approved_by": "...", "approved_on": "2026-11-17"}]}

Missing, empty or unreadable = nothing approved = nothing is sent. Only `"status": "approved"` counts; there is NO
automatic route onto this list (no switch adds a row).

`refusal(ids)` is asked by `groq_transport.send` before a client is built. A body may carry a document's words only when
EVERY declared document:
  * is on the Claude approved list as it counts now (`claude_approved.approved_hashes`: blocks removed, an automatic row
    only while its switch is on) AND on this list;
  * is not blocked by the client's register name block or the owner's block file (`claude_approved._blocked_ids`; a block
    file that cannot be read refuses everything);
  * is not a contract (`claude_auto_approve.is_contract_paper`; unreadable counts as a contract).
And the run's plan is not Local only (`review_engine.claude_barred`): Local only means nothing leaves the machine.
Nothing declared is refused (fail closed). This module opens no socket and reads no document text.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path

from .config import settings

LIST_NAME = "groq_approved_documents.json"
APPROVED = "approved"

#: Refusal codes (the first word the caller records; ids and counts only, never a title).
UNDECLARED = "undeclared"
LOCAL_ONLY = "local_only"
UNKNOWN_DOCUMENT = "unknown_document"
BLOCKED = "blocked"
LISTS_UNREADABLE = "lists_unreadable"
CONTRACT = "contract"
NOT_ON_CLAUDE_LIST = "not_on_claude_list"
NOT_ON_GROQ_LIST = "not_on_groq_list"
NOT_APPROVED_CODES = frozenset(
    {
        UNKNOWN_DOCUMENT,
        BLOCKED,
        LISTS_UNREADABLE,
        CONTRACT,
        NOT_ON_CLAUDE_LIST,
        NOT_ON_GROQ_LIST,
    }
)


def list_path() -> Path:
    return Path(settings.data_dir) / LIST_NAME


def approved_hashes() -> frozenset[str]:
    """The sha256 of every `approved` row of the Groq list. Unreadable or the wrong shape: none (never fails open)."""
    path = list_path()
    try:
        if not path.is_file():
            return frozenset()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    rows = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return frozenset()
    return frozenset(
        str(r.get("sha256") or "").strip().lower()
        for r in rows
        if isinstance(r, dict)
        and str(r.get("status") or "").strip().lower() == APPROVED
        and str(r.get("sha256") or "").strip()
    )


def refusal(document_ids: Collection[str] | None) -> str | None:
    """A refusal code when a body carrying these documents must not leave, else None. See the module docstring."""
    import sqlite3

    from . import claude_approved, claude_auto_approve, review_engine

    if review_engine.claude_barred():
        return LOCAL_ONLY
    ids = frozenset(str(d) for d in (document_ids or ()) if d)
    if not ids:
        return UNDECLARED
    try:
        hashes = claude_approved._hashes_of(ids)
        if any(not h for h in hashes.values()):
            return UNKNOWN_DOCUMENT
        if claude_approved._blocked_ids(hashes):
            return BLOCKED
    except claude_approved.BlockListUnreadable:
        return LISTS_UNREADABLE
    except sqlite3.Error:
        return LISTS_UNREADABLE
    if any(claude_auto_approve.is_contract_paper(d) for d in sorted(ids)):
        return CONTRACT
    if not set(hashes.values()) <= claude_approved.approved_hashes():
        return NOT_ON_CLAUDE_LIST
    if not set(hashes.values()) <= approved_hashes():
        return NOT_ON_GROQ_LIST
    return None
