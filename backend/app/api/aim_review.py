"""Routes of the general review's results page and file (order 14, piece C).

    GET /api/reviews/papers/{document_id}/general[?run_id=]                the stored general review, as the page draws it
    GET /api/reviews/papers/{document_id}/general/sheet[?run_id=][&copy=team|contractor]   the Excel file; the contractor copy only after the
        engineer's sign-off (409 with the reason otherwise), and then the copy KEPT at the sign-off, byte for byte
    POST .../general/decision   accept / edit / reject one comment (append-only)
    POST .../general/accept-rest   accept every comment that has no decision yet
    POST .../general/signoff   the engineer signs the review off with their own choice of the review code; builds and keeps the contractor copy

The caller's scope is checked ONCE, by `require_document` (404, never 403: a paper the caller may not read is indistinguishable from
one that does not exist). A paper with no general review, or a `run_id` that is not a general run of THIS paper, is also 404. The
file is refused with 409 whenever the page, the database and the rows of the file differ (`aim_review_completeness`). `copy=contractor`
answers 409 with the reason (`aim_review_signoff`) until the review is signed off and again once a decision changed after it. The reads
serve earlier general runs whichever way the old-engine switch stands; the writes need a signed-in user who may read the paper.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import (
    access,
    aim_review_completeness,
    aim_review_decisions,
    aim_review_signoff,
    aim_review_view,
    crs_one,
    errors,
    schemas,
)
from ..api_utils import reject_unknown_params, require_document, require_named_user
from ..db import connect

router = APIRouter()

_SUPER_USER_ONLY = {
    403: {
        "model": schemas.ErrorEnvelope,
        "description": "Only a super user can sign this review for now",
    }
}

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
        **_SUPER_USER_ONLY,
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
    run = aim_review_view.resolve(connect(), document_id, run_id)
    if run is None:
        raise _not_found(document_id)
    if copy == "contractor":
        _require_super_user(scope)
    if (
        copy == "contractor"
    ):  # only after the engineer's sign-off, and only the copy kept at it (byte for byte)
        conn = connect()
        try:
            data = aim_review_signoff.issued_copy(
                conn, run, aim_review_view.build(conn, run, scope)
            )
        except (aim_review_signoff.Refused, aim_review_view.NotFinished) as exc:
            raise HTTPException(
                status_code=409,
                detail=errors.safe_error(errors.CRS_NOT_FINISHED, str(exc)),
            ) from exc
        stem = crs_one.paper_file_stem(_stem(document_id))
        name = f"contractor-copy-{stem}.xlsx" if stem else "contractor-copy.xlsx"
        return Response(
            content=data,
            media_type=_XLSX,
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
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


class CommentDecisionIn(BaseModel):
    """One decision on one comment. The caller's identity and the time are the server's, never the body's."""

    run_id: str | None = None
    comment: int = Field(
        ..., ge=1, description="the comment's number on the page (`n`)"
    )
    part: Literal["comment", "confirmation"] = "comment"
    state: Literal["accept", "edit", "reject"]
    text: str | None = Field(None, max_length=aim_review_decisions.MAX_TEXT)
    reason: str | None = Field(None, max_length=300)


class CommentDecisionOut(BaseModel):
    """The comment's latest decision, as the page draws it (`aim_review_decisions.attach`)."""

    run_id: str
    comment: int
    part: Literal["comment", "confirmation"]
    decision: dict


@router.post(
    "/api/reviews/papers/{document_id}/general/decision",
    response_model=CommentDecisionOut,
    responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422},
)
def decide_comment(
    document_id: str,
    body: CommentDecisionIn,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Accept, edit or reject one comment of a general review. Only a signed-in user who may read the paper (404 otherwise, like every
    route here); append-only: the answer is the comment's latest decision. No sign-off or contractor copy comes from this."""
    reject_unknown_params(request, set())
    actor = require_named_user(scope, "a decision must name the engineer who made it")
    require_document(document_id, scope)
    conn = connect()
    run = aim_review_view.resolve(conn, document_id, body.run_id)
    if run is None:
        raise _not_found(document_id)
    try:
        view = aim_review_view.build(conn, run, scope)
    except aim_review_view.NotFinished as exc:
        raise _not_finished(exc) from exc
    group = (
        view["comments"] if body.part == "comment" else view.get("confirmations") or []
    )
    comment = next((c for c in group if c["n"] == body.comment), None)
    if comment is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(
                errors.NOT_FOUND,
                "no such comment in this review",
                document_id=document_id,
            ),
        )
    try:
        with conn:
            aim_review_decisions.record(
                conn, run["run_id"], document_id, comment, body.part, body.state,
                actor=actor, text=body.text, reason=body.reason,
            )  # fmt: skip
    except aim_review_decisions.Refused as exc:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc)),
        ) from exc
    aim_review_decisions.attach(
        conn,
        run["run_id"],
        [comment] if body.part == "comment" else [],
        [comment] if body.part == "confirmation" else [],
    )
    return {
        "run_id": run["run_id"],
        "comment": comment["n"],
        "part": body.part,
        "decision": comment["decision"],
    }


class SignoffIn(BaseModel):
    run_id: str | None = None
    review_code: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="the engineer's own choice of one of the configured codes",
    )
    statement: str | None = Field(None, max_length=300)


class RunIn(BaseModel):
    run_id: str | None = None


def _require_super_user(scope: access.AccessScope) -> None:
    """The sign-off and the contractor copy: the admin capability AND may-read (checked before this), until the owner names engineer
    accounts. A plain 403 with a sentence: the route is the same for every reader, so it reveals nothing."""
    if not scope.is_admin:
        raise HTTPException(
            status_code=403,
            detail=errors.safe_error(
                errors.SUPER_USER_ONLY, aim_review_signoff.SUPER_USER_WORDS
            ),
        )


def _signing_context(
    document_id: str,
    run_id: str | None,
    request: Request,
    scope: access.AccessScope,
    *,
    sign: bool = False,
):
    """The caller's user id (a signed-in user who may read the paper), the connection, the run and its view; 404/409 as the other routes."""
    reject_unknown_params(request, set())
    actor = require_named_user(scope, "a sign-off must name the engineer who signs")
    require_document(document_id, scope)
    if sign:
        _require_super_user(scope)
    conn = connect()
    run = aim_review_view.resolve(conn, document_id, run_id)
    if run is None:
        raise _not_found(document_id)
    try:
        return actor, conn, run, aim_review_view.build(conn, run, scope)
    except aim_review_view.NotFinished as exc:
        raise _not_finished(exc) from exc


class AcceptRestOut(BaseModel):
    run_id: str
    accepted: int
    signoff: str


class SignoffOut(BaseModel):
    run_id: str
    signoff: dict


@router.post(
    "/api/reviews/papers/{document_id}/general/accept-rest",
    response_model=AcceptRestOut,
    responses={
        **schemas.ERRORS_401,
        **_SUPER_USER_ONLY,
        **schemas.ERRORS_404,
        **schemas.ERRORS_409,
    },
)
def accept_rest(
    document_id: str,
    body: RunIn,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Accept every comment and confirmation that has no decision yet, each as its own (append-only) decision. It decides every open
    comment at once, so it is the sign-off's right (a super user and may-read), not a single decision's."""
    actor, conn, run, view = _signing_context(
        document_id, body.run_id, request, scope, sign=True
    )
    n = aim_review_signoff.accept_rest(conn, run, view, actor)
    return {
        "run_id": run["run_id"],
        "accepted": n,
        "signoff": aim_review_signoff.status(
            conn, run, aim_review_view.build(conn, run, scope)
        )["state"],
    }


@router.post(
    "/api/reviews/papers/{document_id}/general/signoff",
    response_model=SignoffOut,
    responses={
        **schemas.ERRORS_401,
        **_SUPER_USER_ONLY,
        **schemas.ERRORS_404,
        **schemas.ERRORS_409,
    },
)
def sign_off(
    document_id: str,
    body: SignoffIn,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The engineer signs the review off (their own choice of the review code); the contractor copy is built and kept with it. 409 names
    each comment that stands in the way; nothing is written then."""
    actor, conn, run, view = _signing_context(
        document_id, body.run_id, request, scope, sign=True
    )
    try:
        status = aim_review_signoff.sign(
            conn, run, view, actor, body.review_code, body.statement
        )
    except aim_review_signoff.Refused as exc:
        detail = {
            **errors.safe_error(errors.CRS_NOT_FINISHED, str(exc)),
            "message": str(exc),
            "blockers": exc.blockers,
        }
        raise HTTPException(status_code=409, detail=detail) from exc
    return {"run_id": run["run_id"], "signoff": status}
