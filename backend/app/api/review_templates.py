"""The review-template and baseline-rule lists, each with an optional page and
its total (order 117 item 5). Moved out of main.py with no other change; the
POST routes that create them stay in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .. import access, schemas
from .. import review as review_mod
from ..api_utils import reject_unknown_params
from ..paging import limit_param, offset_param, page_body

router = APIRouter()


@router.get(
    "/api/reviews/templates",
    response_model=schemas.ReviewTemplateList,
    responses=schemas.ERRORS_422,
)
def list_review_templates(
    request: Request,
    discipline: str | None = Query(None),
    deliverable_type: str | None = Query(None),
    active_only: bool = Query(True),
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    _scope: access.AccessScope = Depends(access.current_scope),
):
    """List versioned, governed review templates available to the caller."""
    reject_unknown_params(
        request, {"discipline", "deliverable_type", "active_only", "limit", "offset"}
    )
    templates = review_mod.list_templates(
        active_only=active_only,
        discipline=discipline,
        deliverable_type=deliverable_type,
    )
    return page_body("templates", templates, limit, offset)


@router.get(
    "/api/reviews/baseline-rules", response_model=schemas.ReviewBaselineRuleList
)
def list_review_baseline_rules(
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    _scope: access.AccessScope = Depends(access.current_scope),
):
    return page_body("rules", review_mod.list_baseline_rules(), limit, offset)
