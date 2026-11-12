"""ONE Review button (owner decision, 12 Nov 2026, #1584 comment 6820183348): the pre-start plan, the start, and the owner's yes
for a contract upload.

    GET    /api/reviews/plan?submittal_document_id=&engine=   what WOULD run: no side effect, no call, no model load
    POST   /api/reviews/start                                  queue what the plan allows (admin); 409 with a plain sentence
    POST   /api/reviews/contract-yes                           record the owner's yes for ONE contract upload (admin)
    DELETE /api/reviews/contract-yes/{document_id}             withdraw it (admin)

The resolver is `review_engine.decide`; this file only carries it. Scope: a paper the caller may not read is a 404, as everywhere.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import (
    access,
    contract_yes,
    errors,
    review_engine,
    review_engine_start,
    review_jobs,
    schemas,
    submittal_review,
)
from .. import admin as admin_mod
from ..api_utils import (
    _require_identity_to_write,
    reject_unknown_params,
    require_document,
)
from ..db import connect

router = APIRouter()


class ReviewStartRequest(BaseModel):
    submittal_document_id: str
    engine: Literal["automatic", "claude", "local"] = "automatic"
    project_document_ids: list[str] = Field(default=[], max_length=10)
    fresh: bool = False


class PlanPart(BaseModel):
    name: str
    engine: str
    why: str


class ReviewPlanOut(BaseModel):
    """What the Review button WOULD run (`review_engine.plan_for`): plain facts; the other keys it adds (cost, documents, boundary, ...) pass through."""

    model_config = {"extra": "allow"}
    choice: str
    parts: list[PlanPart]
    text_leaves: bool
    refused: str | None = None
    refused_code: str | None = None
    needs_yes: bool = False
    unscored: bool = False
    wont_run: list[dict[str, Any]] = []


class ContractYesRecord(BaseModel):
    model_config = {"extra": "allow"}
    document_id: str | None = None
    status: str | None = None
    approved_by: str | None = None
    approved_on: str | None = None
    withdrawn_by: str | None = None
    withdrawn_on: str | None = None


class ContractYesWithdrawn(BaseModel):
    withdrawn: bool


class ContractYesRequest(BaseModel):
    document_id: str


def _is_admin(request: Request) -> bool:
    """True for an admin (or, under AUTH_MODE=disabled with no identity, as `current_admin` allows). Never raises."""
    try:
        admin_mod.current_admin(request)
    except HTTPException:
        return False
    return True


def _actor(admin: dict | None, scope: access.AccessScope) -> str:
    return str(
        (admin or {}).get("email")
        or (admin or {}).get("id")
        or scope.user_id
        or "owner"
    )


@router.get(
    "/api/reviews/plan", response_model=ReviewPlanOut, responses={**schemas.ERRORS_404}
)
def review_plan(
    request: Request,
    submittal_document_id: str = Query(...),
    engine: Literal["automatic", "claude", "local"] = Query("automatic"),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The plan for this paper and this choice, in plain facts. Writes nothing and calls nothing."""
    reject_unknown_params(request, {"submittal_document_id", "engine"})
    require_document(submittal_document_id, scope)
    conn = connect()
    got = review_engine.plan_for(
        conn, submittal_document_id, scope.allowed_document_ids, engine
    )
    record = contract_yes.record_of(submittal_document_id)
    if record is not None and not _is_admin(
        request
    ):  # who approved is for admins; anyone sees that a yes stands
        record = {k: v for k, v in record.items() if k in ("document_id", "status")}
    got["contract_yes"] = record
    return got


@router.post(
    "/api/reviews/start",
    response_model=schemas.ReviewRunSummary,
    responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409},
)
def start_review(
    body: ReviewStartRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Queue the review the plan allows for this choice (admin, like every review start). A refusal is a 409 with a plain
    sentence and queues nothing. Claude is never used silently for Local only, and Local is never used silently for Claude."""
    _require_identity_to_write(scope)
    reject_unknown_params(request, set())
    require_document(body.submittal_document_id, scope)
    try:
        run_id, _plan = review_engine_start.start(
            body.submittal_document_id,
            scope.allowed_document_ids,
            scope.user_id,
            body.engine,
            fresh=body.fresh,
            project_document_ids=tuple(body.project_document_ids),
        )
    except review_engine_start.StartRefused as exc:
        detail = errors.safe_error(errors.INVALID_PARAMETER, exc.sentence)
        raise HTTPException(
            status_code=409, detail={**detail, "code": exc.code}
        ) from exc
    except review_jobs.ReviewAlreadyActive as exc:
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                f"a review of this submittal is already queued or running ({exc.args[0]})",
            ),
        ) from exc
    from .. import main as main_mod

    run = submittal_review.get_review_run(
        run_id, allowed_document_ids=scope.allowed_document_ids
    )
    return main_mod._run_summary(run, scope)


@router.post(
    "/api/reviews/contract-yes",
    response_model=ContractYesRecord,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_409},
)
def record_contract_yes(
    body: ContractYesRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    admin: dict | None = Depends(admin_mod.current_admin),
):
    _require_identity_to_write(scope)
    reject_unknown_params(request, set())
    require_document(body.document_id, scope)
    try:
        return contract_yes.grant(body.document_id, _actor(admin, scope))
    except contract_yes.YesRefused as exc:
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc)),
        ) from exc


@router.delete(
    "/api/reviews/contract-yes/{document_id}",
    response_model=ContractYesWithdrawn,
    responses={**schemas.ERRORS_404},
)
def withdraw_contract_yes(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    admin: dict | None = Depends(admin_mod.current_admin),
):
    _require_identity_to_write(scope)
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return {"withdrawn": contract_yes.withdraw(document_id, _actor(admin, scope))}
