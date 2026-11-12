"""The redesigned review page's routes: ONE list of points per paper, a decision on each, and the engineer's own added points (owner,
12 Nov 2026; SPEC.md).

    GET  /api/reviews/papers/{document_id}/points            the merged list worst first, the tile counts, the proposed review code
    POST /api/reviews/papers/{document_id}/points/decision   Keep, Edit or Remove one point (Edit needs text, Remove a one-line reason)
    POST /api/reviews/papers/{document_id}/points/decisions  Keep several points at once ("Keep all" of a group)
    POST /api/reviews/papers/{document_id}/points/add        the engineer's own point

Read: any caller who may read the paper; every rule book or document the caller may not read is counted, never named. Write: an
identified engineer (not only an admin, like the other decision routes), and only on a point of the list the caller was shown.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import (
    access,
    crs_issue,
    errors,
)
from .. import (
    review_point_decisions as dec,
)
from .. import (
    review_point_sync as sync,
)
from .. import (
    review_points_service as svc,
)
from ..api_utils import (
    _require_identity_to_write,
    reject_unknown_params,
    require_document,
)

router = APIRouter()


class DecisionRequest(BaseModel):
    point_id: str
    state: Literal["keep", "edit", "remove"]
    text: str | None = Field(None, max_length=4000)
    reason: str | None = Field(None, max_length=300)


class BulkKeepRequest(BaseModel):
    point_ids: list[str] = Field(min_length=1, max_length=500)


class AddPointRequest(BaseModel):
    text: str = Field(max_length=4000)
    page: int | None = Field(None, ge=1)
    rule_book: str | None = Field(None, max_length=200)
    clause: str | None = Field(None, max_length=100)


def _actor(scope: access.AccessScope) -> str:
    _require_identity_to_write(scope)
    if scope.user_id is None:
        raise HTTPException(
            status_code=401,
            detail=errors.safe_error(
                errors.UNAUTHENTICATED, "a decision must name the engineer who made it"
            ),
        )
    return scope.user_id


def _point(listing: dict, point_id: str) -> dict:
    for p in listing["points"]:
        if p["id"] == point_id:
            return p
    raise HTTPException(
        status_code=404,
        detail=errors.safe_error(errors.NOT_FOUND, "no such point in this review"),
    )


def _decide(listing: dict, paper_id: str, body: DecisionRequest, actor: str) -> dict:
    point = _point(listing, body.point_id)
    if point["source"] == "added":
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER, "an added point is decided by definition"
            ),
        )
    original = point.get("action") if body.state == "edit" else None
    try:
        if point["source"] == "rule_check" and listing["runs"]["rule_check"]:
            # BOTH decision records, and the findings behind the point, in ONE transaction (`review_point_sync`)
            return sync.record_rule_decision(
                paper_id,
                listing["runs"]["rule_check"],
                body.point_id.removeprefix("rc:"),
                body.state,
                actor=actor,
                finding_ids=point.get("finding_ids"),
                text=body.text,
                reason=body.reason,
                original=original,
            )
        return dec.decide(
            paper_id,
            body.point_id,
            body.state,
            actor=actor,
            text=body.text,
            reason=body.reason,
            original=original,
        )
    except (dec.PointRefused, crs_issue.IssueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc)),
        ) from exc


@router.get("/api/reviews/papers/{document_id}/points", response_model=dict)
def points(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return svc.assemble(document_id, scope)


@router.post("/api/reviews/papers/{document_id}/points/decision", response_model=dict)
def decide_point(
    document_id: str,
    body: DecisionRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    actor = _actor(scope)
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    listing = svc.assemble(document_id, scope)
    _decide(listing, document_id, body, actor)
    return svc.assemble(document_id, scope)


@router.post("/api/reviews/papers/{document_id}/points/decisions", response_model=dict)
def keep_points(
    document_id: str,
    body: BulkKeepRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    actor = _actor(scope)
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    listing = svc.assemble(document_id, scope)
    for pid in body.point_ids:  # all-or-nothing on the ids: an unknown one refuses the whole click before anything is written
        _point(listing, pid)
    for pid in body.point_ids:
        _decide(
            listing,
            document_id,
            DecisionRequest(point_id=pid, state="keep", reason="Kept in bulk"),
            actor,
        )
    return svc.assemble(document_id, scope)


@router.post("/api/reviews/papers/{document_id}/points/add", response_model=dict)
def add_point(
    document_id: str,
    body: AddPointRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    actor = _actor(scope)
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    try:
        dec.add_point(
            document_id,
            body.text,
            actor=actor,
            page=body.page,
            rule_book=body.rule_book,
            clause=body.clause,
        )
    except dec.PointRefused as exc:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc)),
        ) from exc
    return svc.assemble(document_id, scope)
