"""Project specification first (lane 6, M4): which specification a PERSON marked for a submittal, and what a review says of it.

OWNER ORDER (3 Nov 2026): when a submittal has a project specification, the datasheet is compared against it first, then the
standards, and every review reports which project specification was used, or "none held". NOTHING IS EVER CLASSIFIED AS A
PROJECT SPECIFICATION BY CODE OR BY AN AI GUESS: only a person with the `admin` role (displayed "Super user", the owner for now)
marks one, for one named submittal. Until one is marked every review prints "none held". The role is a label, not access
(CLAUDE.md rule 5): a specification the caller may not read is treated as none held, a filter only narrows.

`pin` records the marked document as a MANUAL selection of the run (an engineer's own decision, never replaced by the machine)
so the requirements read from it are compared with the datasheet like any held standard's. `note` says honestly what was done:
marked and compared (n requirements read), or marked but no requirements were read from it, so nothing was compared against it.
The comparison's own order (specification before standards when both state a requirement) is `comparison.py`'s and waits
for the planner; this module only makes the specification a compared document and reports it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .db import connect

log = logging.getLogger(__name__)

MARKABLE_ROLES = ("CONTRACT_DOCUMENT", "COMPANY_STANDARD")
NONE_HELD = "none held"
NOTE = "Project specification"


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS project_specification_mark (
            id INTEGER PRIMARY KEY AUTOINCREMENT, submittal_document_id TEXT NOT NULL,
            spec_document_id TEXT NOT NULL, action TEXT NOT NULL CHECK (action IN ('mark', 'unmark')),
            marked_by TEXT NOT NULL, marked_at TEXT NOT NULL)""")


def _is_owner(conn, user_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id"
            " WHERE u.id = ? AND u.is_active = 1 AND r.name = 'admin'",
            (user_id,),
        ).fetchone()
        is not None
    )


def mark(
    submittal_id: str, spec_id: str, by_user: str, *, undo: bool = False
) -> tuple[bool, str]:
    """A person marks (or unmarks) `spec_id` as `submittal_id`'s project specification. Append-only. (ok, why)."""
    ensure_schema()
    conn = connect()
    if not _is_owner(conn, by_user):
        return False, "only the owner (the admin role) marks a project specification"
    if submittal_id == spec_id:
        return False, "a document is not its own project specification"
    roles = {
        r["document_id"]: r["document_role"]
        for r in conn.execute(
            "SELECT document_id, document_role FROM document_classification WHERE document_id IN (?, ?)",
            (submittal_id, spec_id),
        )
    }
    if roles.get(submittal_id) != "CONTRACTOR_SUBMITTAL":
        return False, "the first document is not a contractor submittal"
    if roles.get(spec_id) not in MARKABLE_ROLES:
        return (
            False,
            "the specification must be a contract document or a company standard",
        )
    with conn:
        conn.execute(
            "INSERT INTO project_specification_mark (submittal_document_id, spec_document_id, action,"
            " marked_by, marked_at) VALUES (?,?,?,?,?)",
            (
                submittal_id,
                spec_id,
                "unmark" if undo else "mark",
                by_user,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
    return True, ""


def marked(submittal_id: str) -> str | None:
    """The specification currently marked for the submittal (the latest mark not undone), or None."""
    ensure_schema()
    state: dict[str, str] = {}
    for r in connect().execute(
        "SELECT spec_document_id, action FROM project_specification_mark"
        " WHERE submittal_document_id = ? ORDER BY id",
        (submittal_id,),
    ):
        state[r["spec_document_id"]] = r["action"]
    live = [spec for spec, action in state.items() if action == "mark"]
    return live[-1] if live else None


def used(submittal_id: str, allowed: frozenset[str]) -> dict | None:
    """{id, name, requirements} of the marked specification when the caller may read it, else None (a filter only narrows)."""
    spec = marked(submittal_id)
    if spec is None or spec not in allowed:
        return None
    conn = connect()
    doc = conn.execute(
        "SELECT filename FROM documents WHERE id = ?", (spec,)
    ).fetchone()
    if doc is None:
        return None
    count = conn.execute(
        "SELECT COUNT(*) FROM standard_requirements WHERE standard_document_id = ?"
        " AND superseded_at IS NULL",
        (spec,),
    ).fetchone()[0]
    return {"id": spec, "name": doc["filename"], "requirements": int(count)}


def line(submittal_id: str, allowed: frozenset[str]) -> str:
    """The one honest sentence every review reports."""
    found = used(submittal_id, allowed)
    if found is None:
        return f"{NOTE}: {NONE_HELD}"
    if found["requirements"] == 0:
        return (
            f"{NOTE}: {found['name']} was marked by the owner, but no requirements were read from it, so nothing was "
            "compared against it"
        )
    return f"{NOTE} used: {found['name']} (marked by the owner; {found['requirements']} requirements read from it)"


def notes(submittal_id: str, allowed: frozenset[str]) -> list[dict]:
    """The Review note (internal) every CRS carries, in the shape of the other review notes."""
    found = used(submittal_id, allowed)
    return [
        {
            "note": NOTE,
            "standard": found["name"] if found else NONE_HELD,
            "count": None,
            "detail": line(submittal_id, allowed),
        }
    ]


def pin(review_run_id: str, submittal_id: str, allowed: frozenset[str]) -> bool:
    """Record the marked specification as a manual selection of this run, when the caller may read it and it holds
    requirements. Never fails the review. True when it was recorded."""
    try:
        found = used(submittal_id, allowed)
        if found is None or found["requirements"] == 0:
            return False
        from . import applicability

        applicability.record_selection(
            review_run_id=review_run_id,
            standard_document_id=found["id"],
            method=applicability.METHOD_MANUAL,
            reason="marked by the owner as this submittal's project specification; compared before the standards",
        )
        return True
    except Exception:
        log.warning(
            "project specification: could not pin for run %s",
            review_run_id,
            exc_info=True,
        )
        return False
