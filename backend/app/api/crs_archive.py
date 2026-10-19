"""The CRS record of a run: who decided what (order 95 piece 6a) and the
contractor copies issued (PF5, #885). Read only.

`list_issued_crs` moved out of main.py with no logic change (order 79a).
Both lists take an optional page and state their total (order 117 item 5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import access, errors, schemas
from .. import crs_issue as crs_issue_mod
from .. import submittal_review as submittal_review_mod
from ..api_utils import reject_unknown_params
from ..paging import limit_param, offset_param, page_body

router = APIRouter()


def _require_run(review_run_id: str, scope: access.AccessScope) -> None:
    if (
        submittal_review_mod.get_review_run(
            review_run_id, allowed_document_ids=scope.allowed_document_ids
        )
        is None
    ):
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no review run with that id"),
        )


@router.get(
    "/api/reviews/runs/{review_run_id}/crs/decisions",
    response_model=schemas.CrsIssueDecisionList,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def list_crs_decisions(
    review_run_id: str,
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Order 95 piece 6a: who decided what on this run's CRS, when and why,
    newest first. Read only; nothing is overwritten, so history is complete."""
    reject_unknown_params(request, {"limit", "offset"})
    _require_run(review_run_id, scope)
    return page_body("decisions", crs_issue_mod.history(review_run_id), limit, offset)


@router.get(
    "/api/reviews/runs/{review_run_id}/crs/issued",
    response_model=schemas.CrsIssuedCopyList,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def list_issued_crs(
    review_run_id: str,
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """PF5 (#885): the contractor copies issued for this run. Read only."""
    reject_unknown_params(request, {"limit", "offset"})
    _require_run(review_run_id, scope)
    return page_body("copies", crs_issue_mod.issued(review_run_id), limit, offset)
