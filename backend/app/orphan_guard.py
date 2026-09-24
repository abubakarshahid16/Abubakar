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

THE CHEAP GUARD, NOT THE REDESIGN - for REQUIREMENTS. Without a `superseded`
column there is no way to keep an old row out of future reviews, so keeping
referenced rows would trade orphans for duplicate findings. What is possible
with no schema change: count the findings a deletion would orphan, write that
to `audit_events` whatever happens, and REFUSE unless the caller explicitly
acknowledges it. So orphaning can no longer happen by default or silently.
It does not repair the existing orphans, and the requirements versioning
redesign stays parked for the owner's sign-off.

FACTS GOT THE REDESIGN (#179, owner-authorised 2026-09-25). B40's fifth path,
`datasheets.extract_facts(replace=True)`, no longer deletes anything:
`submittal_facts.superseded_at` marks the replaced rows, every reader of
current facts leaves them out, and a finding's `fact_id` keeps resolving. So
there is no facts guard left to refuse; `findings_orphaned_by_facts` stays as
the COUNT of findings that cite the rows being superseded, and
`record_facts_superseded` writes that count beside the number of rows marked.

`detail` carries ids and counts only - never requirement text or a title,
because the audit table is the one most likely to be exported.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .db import connect

#: What the SCREEN says each refused action is. The message is read by a person
#: in the UI, so it names what they pressed, not the internal path.
_BLOCKED = {
    "re_extraction": "Re-extract is blocked",
    "document_delete": "Delete is blocked",
    "reject": "Rejecting this requirement is blocked",
    "re_chunk": "Re-chunking is blocked",
}

#: The way forward that EXISTS on screen. An updated standard is a new
#: document plus "Superseded by" on the old one, which deletes nothing.
_WHAT_TO_DO = ("To update a standard, upload the new revision and set "
               "\"Superseded by\" on this standard in the Standards page.")

#: What each kind of citation is called in the message, and what to do about
#: it. `requirements` wording is B38's, unchanged. The `facts` kind B40 added
#: is gone with the facts guard (#179 supersession) - facts are no longer
#: deleted, so no message about deleting them is ever shown.
_KINDS = {
    "requirements": ("this standard's requirements", _WHAT_TO_DO),
}


class OrphaningRefused(RuntimeError):
    """A deletion would orphan review findings and nobody acknowledged it.

    THE MESSAGE SAYS WHAT TO DO, not an API flag (owner, 2026-09-22). It used
    to end "repeat with acknowledge_orphaned_findings=true", which nobody can
    do from a screen and which read as a bug. The flag still exists on the
    API for an admin who must re-extract on purpose; the confirm-and-proceed
    dialog that would expose it on screen is agreed but deferred.
    """

    def __init__(self, action: str, document_id: str | None, findings: int,
                 kind: str = "requirements"):
        self.action = action
        self.document_id = document_id
        self.findings = findings
        self.kind = kind
        cite = "cites" if findings == 1 else "cite"
        plural = "" if findings == 1 else "s"
        what, advice = _KINDS[kind]
        super().__init__(
            f"{_BLOCKED.get(action, 'This change is blocked')} because "
            f"{findings} review finding{plural} {cite} {what}, and they could "
            f"no longer be traced. {advice}")


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


def findings_orphaned_by_facts(fact_where: str, params: tuple | list) -> int:
    """How many review findings cite a `submittal_facts` row the WHERE selects.

    B40, the same shape as `findings_orphaned_by` one table over:
    `review_findings.fact_id` has no foreign key either. Since #179 nothing
    deletes those rows - `extract_facts(replace=True)` supersedes them - so
    this is no longer a count of findings ABOUT to be orphaned but of
    findings whose cited fact is about to stop being current, recorded by
    `record_facts_superseded`. The name is kept for the callers that read it.
    """
    try:
        return connect().execute(
            "SELECT COUNT(*) FROM review_findings WHERE fact_id IN"
            f" (SELECT id FROM submittal_facts WHERE {fact_where})",
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
    return _decide(action, findings_orphaned_by(requirement_where, params),
                   document_id, acknowledge, actor, kind="requirements")


def record_facts_superseded(conn: sqlite3.Connection, action: str,
                            document_id: str, *, superseded: int,
                            findings_citing: int,
                            actor: dict | None = None) -> None:
    """#179: the record of a re-read that replaced current facts.

    Written ON THE CALLER'S CONNECTION, inside the caller's transaction, so
    the mark and its record commit together or not at all - the opposite of
    `_record`, which must survive a refused deletion. Nothing is refused
    here because nothing is destroyed: the rows stay and the findings still
    resolve. `findings_citing` is how many findings cite one of the rows
    marked, stated so a reader knows how much history now points at a
    non-current reading. Counts only, never a fact's text.
    """
    conn.execute(
        """INSERT INTO audit_events
               (at, actor_user_id, actor_username, action,
                resource_type, resource_id, outcome, detail)
           VALUES (?, ?, ?, ?, 'document', ?, 'ok', ?)""",
        (datetime.now(UTC).isoformat(timespec="seconds"),
         (actor or {}).get("id"),
         ((actor or {}).get("email") or "unauthenticated")[:200],
         f"facts.superseded.{action}", document_id,
         f"facts_superseded={superseded} findings_citing={findings_citing}"))


def _decide(action: str, orphaned: int, document_id: str | None,
            acknowledge: bool, actor: dict | None, *, kind: str) -> int:
    if orphaned == 0:
        return 0
    _record(action, document_id, orphaned, actor,
            outcome="ok" if acknowledge else "refused")
    if not acknowledge:
        raise OrphaningRefused(action, document_id, orphaned, kind)
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
