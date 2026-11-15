"""The role record of a review, for the page tab "How it was reviewed" (nine-role review; SPEC section B).

    GET /api/reviews/runs/{run_id}/roles     the nine roles of the run: state, why, engine, models, calls, USD (null = not known),
                                             counts produced, and what each role READ (document, pages, chapter, part, size)

BEHIND THE SWITCH, checked at request time: while `AGENT_REVIEW_NINE_ROLES_ENABLED` (or the AI reviewer) is off every route answers
404 "feature_off". SCOPE: a run the caller may not read is a 404, as every review route; a document the caller may not read is COUNTED
(`not_readable`), never named; titles are resolved here, at read time, and are never stored. A GET writes nothing. A run with no role
rows (every review before this) answers 404 "no role record".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import access, agent_review_gate, errors, nine_record, submittal_review
from ..api_utils import reject_unknown_params
from ..config import settings
from ..db import connect

NOT_RECORDED = (
    "this review has no role record (it was reviewed before the roles were recorded)"
)


def switch_on() -> bool:
    """The one switch (`AGENT_REVIEW_NINE_ROLES_ENABLED`, added to the settings by the job's builder) AND the AI reviewer. Read at request
    time; a settings object without the field (before it exists) is off."""
    return (
        bool(getattr(settings, "agent_review_nine_roles_enabled", False))
        and agent_review_gate.enabled()
    )


def _require_on() -> None:
    if not switch_on():
        raise HTTPException(status_code=404, detail=agent_review_gate.FEATURE_OFF)


router = APIRouter(dependencies=[Depends(_require_on)])


def _titles(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = (
        connect()
        .execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", sorted(ids)
        )
        .fetchall()
    )
    return {r["id"]: r["filename"] for r in rows}


def public(record, allowed: frozenset[str]) -> dict:
    """The record as the page reads it. Pure over the record and the caller's scope; a document outside it is counted, not named."""
    readable = {
        e.document_id for r in record.roles for e in r.reads if e.document_id in allowed
    }
    titles = _titles(readable)
    roles = []
    for r in record.roles:
        mine = [e for e in r.reads if e.document_id in allowed]
        calls = [c for c in record.calls if c.role_no == r.role_no]
        roles.append(
            {
                "role_no": r.role_no,
                "role": r.role,
                "state": r.state,
                "why": r.why,
                "engine": r.engine,
                "models": list(r.models),
                "calls": r.calls,
                "calls_by_state": {
                    s: sum(1 for c in calls if c.state == s)
                    for s in sorted({c.state for c in calls})
                },
                "usd": r.usd,
                "produced": dict(r.produced),
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "reads": [
                    {
                        "document_id": e.document_id,
                        "title": titles.get(e.document_id),
                        "kind": e.document_kind,
                        "pages": list(e.pages),
                        "chapter_id": e.chapter_id,
                        "part_no": e.part_no,
                        "part_of": e.part_of,
                        "chars": e.chars,
                        "pictures": e.pictures,
                    }
                    for e in mine
                ],
                "not_readable": len(
                    {
                        (e.call_id, e.document_id)
                        for e in r.reads
                        if e.document_id not in allowed
                    }
                ),
            }
        )
    return {
        "run_id": record.run_id,
        "engine_choice": record.engine_choice,
        "roles_line": record.roles_line(),
        "roles": roles,
        "documents_on_the_shown_list": None
        if record.shown_document_ids is None
        else len(
            [d for d in record.shown_document_ids if d in allowed]
        ),  # only what the caller may read: the stated boundary
        "boundary": "documents you may read",
    }


@router.get("/api/reviews/runs/{run_id}/roles")
def run_roles(
    run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    run = submittal_review.get_review_run(
        run_id, allowed_document_ids=scope.allowed_document_ids
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no review run with that id"),
        )
    record = nine_record.load_record(run_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=errors.safe_error(errors.NOT_FOUND, NOT_RECORDED)
        )
    return public(record, scope.allowed_document_ids)
