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
(`standards.selectable_standard_ids`), and a review that skips one says so.
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
    "NotAnAdministrator",
    "confirm",
    "held_clause",
    "held_ids",
]
