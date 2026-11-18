"""Routes of the general review's results page and file (order 14, piece C).

    GET /api/reviews/papers/{document_id}/general[?run_id=]                the stored general review, as the page draws it
    GET /api/reviews/papers/{document_id}/general/sheet[?run_id=][&copy=team]   the Excel file (team copy only)

The caller's scope is checked ONCE, by `require_document` (404, never 403: a paper the caller may not read is indistinguishable from
one that does not exist). A paper with no general review, or a `run_id` that is not a general run of THIS paper, is also 404. The
file is refused with 409 whenever the page, the database and the rows of the file differ (`aim_review_completeness`). `copy=contractor`
answers 409 `NO_CONTRACTOR_COPY_WORDS`: there is no contractor copy and no sign-off for a general review. These routes only read what
is stored: they serve earlier general runs whichever way the old-engine switch stands.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import (
    access,
    aim_review_completeness,
    aim_review_gate,
    aim_review_view,
    crs_one,
    errors,
    schemas,
)
from ..api_utils import reject_unknown_params, require_document
from ..db import connect

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_GENERAL_WORDS = "this paper has no general review"


class GeneralReviewOut(BaseModel):
    """The general review's page (`aim_review_view.served`): the contract keys typed, the additive keys passed through."""

    model_config = {"extra": "allow"}
    paper_document_id: str
    run_id: str
    method: str
    mark: str
    status: str
    comments: list[dict]
    points: list[dict]


def _not_found(document_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=errors.safe_error(
            errors.NOT_FOUND, NO_GENERAL_WORDS, document_id=document_id
        ),
    )


def _not_finished(exc: aim_review_view.NotFinished) -> HTTPException:
    return HTTPException(
        status_code=409, detail=errors.safe_error(errors.CRS_NOT_FINISHED, str(exc))
    )


@router.get(
    "/api/reviews/papers/{document_id}/general",
    response_model=GeneralReviewOut,
    responses={**schemas.ERRORS_404},
)
def general_review(
    document_id: str,
    request: Request,
    run_id: str | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"run_id"})
    require_document(document_id, scope)
    try:
        view = aim_review_view.served(connect(), document_id, scope, run_id)
    except aim_review_view.NotFinished as exc:
        raise _not_finished(exc) from exc
    if view is None:
        raise _not_found(document_id)
    return view


@router.get(
    "/api/reviews/papers/{document_id}/general/sheet",
    response_class=Response,
    responses={
        200: {"content": {_XLSX: {}}, "description": "The general review's file"},
        **schemas.ERRORS_404,
    },
)
def general_sheet(
    document_id: str,
    request: Request,
    run_id: str | None = None,
    copy: Literal["team", "contractor"] = "team",
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"run_id", "copy"})
    require_document(document_id, scope)
    if (
        copy == "contractor"
    ):  # no contractor copy and no sign-off for a general review (the one sentence lives in the gate)
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.CRS_NOT_FINISHED, aim_review_gate.NO_CONTRACTOR_COPY_WORDS
            ),
        )
    run = aim_review_view.resolve(connect(), document_id, run_id)
    if run is None:
        raise _not_found(document_id)
    try:  # THE HARD RULE: page, database and file rows agree, or the file is refused with the sentence
        data = aim_review_completeness.file_or_refuse(run["run_id"], scope)
    except aim_review_view.NotFinished as exc:
        raise _not_finished(exc) from exc
    except aim_review_completeness.Incomplete as exc:
        # the sentence is made of counts, numbers and pages (no document text): given whole, not cut at the error helper's limit
        detail = {**errors.safe_error(errors.CRS_NOT_FINISHED, ""), "message": str(exc)}
        raise HTTPException(status_code=409, detail=detail) from exc
    stem = crs_one.paper_file_stem(_stem(document_id))
    name = f"general-review-{stem}.xlsx" if stem else "general-review.xlsx"
    return Response(
        content=data,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _stem(document_id: str) -> str:
    """The paper's file stem for the download's name, from the database."""
    from pathlib import Path

    row = (
        connect()
        .execute("SELECT filename FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    return Path(str(row["filename"] or "")).stem if row else ""
