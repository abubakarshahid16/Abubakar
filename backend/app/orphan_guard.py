"""B38: stop NEW findings being orphaned. Record, then refuse by default.

16,168 of 20,288 historical `review_findings` rows (owner's evaluation,
2026-09-22; not yet verified on the new machine) carry a `requirement_id`
whose `standard_requirements` row is gone. `review_findings.requirement_id`
has no foreign key, so nothing ever refused or recorded the deletion.
NORTH-STAR section 4: "Re-extraction must not destroy historical evidence."

FOUR PATHS DELETE REQUIREMENT ROWS, and each now asks this module first:

  1. `standards.extract_requirements(replace=True)` - re-extraction deletes
     every unconfirmed row of the standard and writes new ones, new ids;
  2. `standards.decide_requirement(decision="reject")` - one row;
  3. `chunker.chunk_document` - re-chunking deletes the document's chunks,
     and `standard_requirements.chunk_id ... ON DELETE CASCADE` takes their
     requirements with them, confirmed or not;
  4. `DELETE /api/documents/{id}` - `standard_requirements.standard_document_id
     ... ON DELETE CASCADE` takes every requirement of a deleted standard.

THE CHEAP GUARD, NOT THE REDESIGN. Without a `superseded` column there is no
way to keep an old row out of future reviews, so keeping referenced rows
would trade orphans for duplicate findings. What is possible with no schema
change: count the findings a deletion would orphan, write that to
`audit_events` whatever happens, and REFUSE unless the caller explicitly
acknowledges it. So orphaning can no longer happen by default or silently.
It does not repair the existing orphans, and the versioning redesign stays
parked for the owner's sign-off.

`detail` carries ids and counts only - never requirement text or a title,
because the audit table is the one most likely to be exported.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .db import connect


class OrphaningRefused(RuntimeError):
    """A deletion would orphan review findings and nobody acknowledged it."""

    def __init__(self, action: str, document_id: str | None, findings: int):
        self.action = action
        self.document_id = document_id
        self.findings = findings
        super().__init__(
            f"refused: {action} would orphan {findings} review finding(s) that "
            f"cite requirements of document {document_id}; their requirement "
            "rows would be deleted and those findings could no longer be "
            "traced. Repeat with acknowledge_orphaned_findings=true to proceed "
            "on purpose - the count is recorded either way")


def findings_orphaned_by(requirement_where: str, params: tuple | list) -> int:
    """How many review findings cite a requirement row the WHERE selects.

    `requirement_where` is a fragment over `standard_requirements` written by
    the four call sites in this codebase - never built from user input.
    A database that has never run a review has no findings table: 0.
    """
    try:
        return connect().execute(
            "SELECT COUNT(*) FROM review_findings WHERE requirement_id IN"
            f" (SELECT id FROM standard_requirements WHERE {requirement_where})",
            tuple(params)).fetchone()[0]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise


def check(action: str, *, requirement_where: str, params: tuple | list,
          document_id: str | None, acknowledge: bool,
          actor: dict | None = None) -> int:
    """Record, then refuse unless acknowledged. Returns the count orphaned.

    Nothing is recorded when nothing would be orphaned - the ordinary case
    for a standard no review has cited yet.
    """
    orphaned = findings_orphaned_by(requirement_where, params)
    if orphaned == 0:
        return 0
    _record(action, document_id, orphaned, actor,
            outcome="ok" if acknowledge else "refused")
    if not acknowledge:
        raise OrphaningRefused(action, document_id, orphaned)
    return orphaned


def _record(action: str, document_id: str | None, orphaned: int,
            actor: dict | None, *, outcome: str) -> None:
    """The row survives whether or not the deletion goes ahead.

    Written in its own transaction BEFORE the caller's delete, so a refused
    attempt is on record too. Unlike `standards._audit`, a failure to write it
    is NOT swallowed: this record is the only trace the evidence was
    destroyed, and a deletion must not proceed without it.
    """
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO audit_events
                   (at, actor_user_id, actor_username, action,
                    resource_type, resource_id, outcome, detail)
               VALUES (?, ?, ?, ?, 'document', ?, ?, ?)""",
            (datetime.now(UTC).isoformat(timespec="seconds"),
             (actor or {}).get("id"),
             ((actor or {}).get("email") or "unauthenticated")[:200],
             f"findings.orphaning.{action}", document_id, outcome,
             f"findings_orphaned={orphaned}"))
