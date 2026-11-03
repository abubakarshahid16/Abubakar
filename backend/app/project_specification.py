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

from . import access
from .db import connect

log = logging.getLogger(__name__)

MARKABLE_ROLES = ("CONTRACT_DOCUMENT", "COMPANY_STANDARD")
NONE_HELD = "none held"
NOTE = "Project specification"
NOT_READABLE = "no such document that you may read"


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
    # Rule 5: the admin role is a label, not access. The caller must be able to read BOTH documents, and the refusal is the
    # same words for "does not exist" and "may not read", so it says nothing of a document (its class, title or existence).
    readable = access.scope_for_user(by_user).allowed_document_ids
    if submittal_id not in readable or spec_id not in readable:
        return False, NOT_READABLE
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
    """The specification currently marked for the submittal, or None.

    ONE project specification at a time: marking a second REPLACES the first, and unmarking a document that is not the
    current one changes nothing. The order is the mark record's own `id` (append order), read in that order, never a dict's
    insertion order: mark A, mark B, unmark A, mark A gives A."""
    ensure_schema()
    current: str | None = None
    for r in connect().execute(
        "SELECT spec_document_id, action FROM project_specification_mark"
        " WHERE submittal_document_id = ? ORDER BY id ASC",
        (submittal_id,),
    ):
        if r["action"] == "mark":
            current = r["spec_document_id"]
        elif current == r["spec_document_id"]:
            current = None
    return current


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


OUTCOME_USED = "used"
OUTCOME_EXCLUDED = "excluded_by_engineer"
OUTCOME_NO_REQUIREMENTS = "no_requirements"
OUTCOME_NONE = "none_held"
BY = "marked by an administrator"


def _sentence(outcome: str, name: str, requirements: int) -> str:
    if outcome == OUTCOME_USED:
        return f"{NOTE} used: {name} ({BY}; {requirements} requirements read from it)"
    if outcome == OUTCOME_EXCLUDED:
        return f"{NOTE}: {name} was {BY}, but an engineer excluded it from this run, so nothing was compared against it"
    if outcome == OUTCOME_NO_REQUIREMENTS:
        return f"{NOTE}: {name} was {BY}, but no requirements were read from it, so nothing was compared against it"
    return f"{NOTE}: {NONE_HELD}"


def line(submittal_id: str, allowed: frozenset[str]) -> str:
    """The sentence for the CURRENT mark (no run): used only where there is no run to ask, and it never says 'used'
    for a run, since a mark says nothing of what a run did (`run_line`)."""
    found = used(submittal_id, allowed)
    if found is None:
        return _sentence(OUTCOME_NONE, "", 0)
    if found["requirements"] == 0:
        return _sentence(OUTCOME_NO_REQUIREMENTS, found["name"], 0)
    return _sentence(OUTCOME_USED, found["name"], found["requirements"])


def _ensure_run_table() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS project_specification_run (
            review_run_id TEXT PRIMARY KEY, spec_document_id TEXT, name TEXT, requirements INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL, recorded_at TEXT NOT NULL)""")


def _record(
    run_id: str, spec: str | None, name: str, requirements: int, outcome: str
) -> None:
    """What THIS run did about the specification, stored at pin time; a later mark or unmark never rewrites it."""
    _ensure_run_table()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_specification_run (review_run_id, spec_document_id, name, requirements,"
            " outcome, recorded_at) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                spec,
                name,
                requirements,
                outcome,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )


def _run_facts(run_id: str, allowed: frozenset[str]) -> tuple[str, str]:
    """(sentence, standard) from the facts stored when the run ran. A specification the caller may not read reads as none
    held (a filter only narrows)."""
    _ensure_run_table()
    r = (
        connect()
        .execute(
            "SELECT * FROM project_specification_run WHERE review_run_id = ?", (run_id,)
        )
        .fetchone()
    )
    if r is None:
        return f"{NOTE}: not recorded for this run", NONE_HELD
    if r["outcome"] == OUTCOME_NONE or r["spec_document_id"] not in allowed:
        return _sentence(OUTCOME_NONE, "", 0), NONE_HELD
    return _sentence(r["outcome"], r["name"], int(r["requirements"])), r["name"]


def run_line(run_id: str, allowed: frozenset[str]) -> str:
    return _run_facts(run_id, allowed)[0]


def notes(
    submittal_id: str, allowed: frozenset[str], run_id: str | None = None
) -> list[dict]:
    """The Review note (internal) every CRS carries, in the shape of the other review notes. With a run: what that run did."""
    if run_id:
        text, standard = _run_facts(run_id, allowed)
    else:
        found = used(submittal_id, allowed)
        text, standard = (
            line(submittal_id, allowed),
            found["name"] if found else NONE_HELD,
        )
    return [{"note": NOTE, "standard": standard, "count": None, "detail": text}]


def pin(review_run_id: str, submittal_id: str, allowed: frozenset[str]) -> bool:
    """Record the marked specification as a manual selection of this run, when the caller may read it and it holds
    requirements, and STORE what the run did (used, excluded by an engineer, no requirements, none). Never fails the
    review. True when a selection was recorded now."""
    try:
        found = used(submittal_id, allowed)
        if found is None:
            _record(review_run_id, None, "", 0, OUTCOME_NONE)
            return False
        if found["requirements"] == 0:
            _record(
                review_run_id, found["id"], found["name"], 0, OUTCOME_NO_REQUIREMENTS
            )
            return False
        from . import applicability

        manual = (
            connect()
            .execute(
                "SELECT included FROM review_applicable_standards WHERE review_run_id = ? AND standard_document_id = ?"
                " AND selection_method = ?",
                (review_run_id, found["id"], applicability.METHOD_MANUAL),
            )
            .fetchone()
        )
        if manual:  # an engineer already decided about this standard for this run; the machine never replaces it
            _record(
                review_run_id,
                found["id"],
                found["name"],
                found["requirements"],
                OUTCOME_USED if manual["included"] else OUTCOME_EXCLUDED,
            )
            return False
        applicability.record_selection(
            review_run_id=review_run_id,
            standard_document_id=found["id"],
            method=applicability.METHOD_MANUAL,
            reason="marked by an administrator as this submittal's project specification; compared before the standards",
        )
        _record(
            review_run_id,
            found["id"],
            found["name"],
            found["requirements"],
            OUTCOME_USED,
        )
        return True
    except Exception:
        log.warning(
            "project specification: could not pin for run %s",
            review_run_id,
            exc_info=True,
        )
        return False
