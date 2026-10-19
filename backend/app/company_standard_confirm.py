"""#620 (owner decision 2026-10-08): a Company standard uploaded by a non-admin
is held for an administrator's confirmation before reviews use it.

WHO UPLOADED is the upload route's own record: the document is granted to the
uploader's roles with `document_role_access.granted_by = uploader`
(`access.grant_uploaded_document_to_disciplines` / `_to_admin`). A standard is
HELD when all of these hold:

  * it has at least one upload grant with a recorded granter, and
  * no granter of it is an administrator, and
  * its first such grant is at or after `settings.company_standard_confirm_from`
    (the cut-off; empty = every standard, see #620 options a/b/c), and
  * no administrator has confirmed it (`company_standard_confirmations`).

A held standard stays READABLE by its disciplines (classification is not
access control, CLAUDE.md rule 5); only review SELECTION skips it
(`standards.selectable_standard_ids`). A review that skips one SAYS SO: the
review job stores `standards_held_for_confirmation` on the run
(`record_on_run`), with the option-(a) boundary in plain words, and
`GET /api/reviews/runs/{id}/standards` returns it. An administrator lists
held standards and confirms one through `/api/admin/company-standards/...`.
Confirming is admin-only, idempotent and audited.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .config import settings
from .db import connect

CONFIRMED_ACTION = "company_standard.confirmed"


class NotAnAdministrator(PermissionError):
    """Only an administrator may confirm a Company standard (#620)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


#: A standard is held: an upload grant by a non-admin only, on or after the
#: cut-off, and no admin confirmation. `?` = the cut-off ('' = no cut-off).
_HELD = """
    EXISTS (SELECT 1 FROM document_role_access a
             WHERE a.document_id = {doc} AND a.granted_by IS NOT NULL)
    AND NOT EXISTS (SELECT 1 FROM document_role_access a
                     JOIN user_roles ur ON ur.user_id = a.granted_by
                     JOIN roles r ON r.id = ur.role_id
                    WHERE a.document_id = {doc} AND r.name = 'admin')
    AND (SELECT MIN(a.granted_at) FROM document_role_access a
          WHERE a.document_id = {doc} AND a.granted_by IS NOT NULL) >= ?
    AND NOT EXISTS (SELECT 1 FROM company_standard_confirmations k
                     WHERE k.document_id = {doc})
"""


def held_clause(column: str) -> tuple[str, list[str]]:
    """(SQL, params): a condition true for a HELD standard, on `column`."""
    return _HELD.format(doc=column), [str(settings.company_standard_confirm_from or "")]


def held_ids(document_ids: frozenset[str]) -> frozenset[str]:
    """Which of `document_ids` are held for an administrator's confirmation."""
    if not document_ids:
        return frozenset()
    marks = ",".join("?" for _ in document_ids)
    clause, params = held_clause("d.id")
    rows = (
        connect()
        .execute(
            f"SELECT d.id FROM documents d WHERE d.id IN ({marks}) AND {clause}",
            [*sorted(document_ids), *params],
        )
        .fetchall()
    )
    return frozenset(r["id"] for r in rows)


#: The run outcome key that says a review left held standards out.
RUN_NOTE_KEY = "standards_held_for_confirmation"


def _held_current(allowed_document_ids: frozenset[str] | None) -> list[dict]:
    """Current (not superseded) Company standards the caller may read that are
    held right now, with when they were first uploaded. The same scope and
    supersession rule as `standards.selectable_standard_ids`, so these are
    exactly the standards a review by this caller leaves out. `None` = every
    held standard, for the administrator's list only (`list_held`): the
    grants scope has no corpus-wide value (`standards._scope_clause`)."""
    from .standards import COMPANY_STANDARD, _scope_clause

    if allowed_document_ids is None:
        where, args = " WHERE 1 = 1", []
    else:
        where, args = _scope_clause(allowed_document_ids, "d.id")
    clause, params = held_clause("d.id")
    rows = (
        connect()
        .execute(
            "SELECT d.id, d.filename,"
            " (SELECT MIN(a.granted_at) FROM document_role_access a"
            "   WHERE a.document_id = d.id AND a.granted_by IS NOT NULL) AS uploaded_at"
            " FROM documents d JOIN document_classification c ON c.document_id = d.id"
            + where
            + " AND c.document_role = ? AND c.superseded_by IS NULL AND "
            + clause
            + " ORDER BY d.id",
            [*args, COMPANY_STANDARD, *params],
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def held_readable(allowed_document_ids: frozenset[str]) -> list[str]:
    """The ids of `_held_current`: what a review by this caller leaves out."""
    return [row["id"] for row in _held_current(allowed_document_ids)]


def list_held() -> list[dict]:
    """Every held Company standard, for the administrator's list: id, file
    name and first upload time. Admin-only at the route."""
    return _held_current(None)


def run_note(held: list[str]) -> dict | None:
    """The run's note for the held standards it left out, or None for none.
    Says the boundary (owner's option a, 19 Oct 2026): standards uploaded
    before the cut-off count as confirmed."""
    if not held:
        return None
    cutoff = str(settings.company_standard_confirm_from or "")
    n = len(held)
    noun = "Company standard was" if n == 1 else "Company standards were"
    boundary = (
        f" Company standards uploaded before {cutoff[:10]} count as confirmed."
        if cutoff
        else " Every Company standard a non-administrator uploaded waits for confirmation."
    )
    return {
        "count": n,
        "standard_document_ids": list(held),
        "confirm_from": cutoff or None,
        "sentence": (
            f"{n} {noun} not used in this review: uploaded by a non-administrator, "
            "waiting for an administrator's confirmation." + boundary
        ),
    }


def record_on_run(review_run_id: str, held: list[str]) -> None:
    """Add the run note to the run's stored outcome (written once by the
    comparison step before this is called). Nothing is written when no
    standard was held."""
    note = run_note(held)
    if note is None:
        return
    conn = connect()
    with conn:
        row = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
        ).fetchone()
        if row is None:
            return
        outcome = json.loads(row["outcome_json"] or "{}")
        outcome[RUN_NOTE_KEY] = note
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), review_run_id),
        )


def confirm(document_id: str, *, actor_user_id: str, actor_username: str) -> bool:
    """An administrator confirms one Company standard for reviews. True when
    this call confirmed it, False when it was already confirmed (idempotent:
    no second row, no second audit event). Raises NotAnAdministrator."""
    from . import access

    if not access.is_admin(actor_user_id):
        raise NotAnAdministrator("only an administrator may confirm a Company standard")
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO company_standard_confirmations"
            " (document_id, confirmed_by, confirmed_by_name, confirmed_at) VALUES (?, ?, ?, ?)",
            (document_id, actor_user_id, actor_username, _now()),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT INTO audit_events (at, actor_user_id, actor_username, action,"
            " resource_type, resource_id, outcome, detail)"
            " VALUES (?, ?, ?, ?, 'document', ?, 'ok', ?)",
            (
                _now(),
                actor_user_id,
                actor_username,
                CONFIRMED_ACTION,
                document_id,
                json.dumps({"issue": 620}),
            ),
        )
    return True


__all__ = [
    "CONFIRMED_ACTION",
    "RUN_NOTE_KEY",
    "NotAnAdministrator",
    "confirm",
    "held_clause",
    "held_ids",
    "held_readable",
    "list_held",
    "record_on_run",
    "run_note",
]
