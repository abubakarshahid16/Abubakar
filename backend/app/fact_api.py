"""POST /api/reviews/facts/{fact_id}/confirm - an engineer confirms one value
the datasheet reader read (#473, audit D04).

An `APIRouter`, like `watch_api`, so main.py includes one line.

WHAT IT CHANGES. `submittal_facts.confirmed_by` and `confirmed_at`, through
`submittal_review.confirm_fact`, the column's only writer. From then on
`comparison` treats the value as human-verified (no AI-quote proof is
needed) and the facts reader never supersedes it. A guess is shown as a
guess until a human confirms it (rule 4); this is the confirming.

WHO. The signed-in caller, by their own id - a confirmation nobody signed is
refused with 401, never stored with a NULL name. The fact must be on a
submittal the caller may read (404, the same answer as "no such fact"). A
superseded fact is 409: confirming it would bless a value the review no
longer uses. Ids only reach the audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import access, errors, schemas
from . import comparison as comparison_mod
from . import submittal_review as submittal_review_mod
from .db import connect

router = APIRouter()


@router.post(
    "/api/reviews/facts/{fact_id}/confirm",
    response_model=schemas.FactConfirmation,
    responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409},
)
def confirm_review_fact(
    fact_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The engineer confirms one datasheet value. 401 unsigned, 404 not
    theirs to read, 409 re-read since."""
    if scope.user_id is None:
        # Under the unrestricted development mode too: there is no name to
        # write, and `confirmed_by` NULL means "not confirmed".
        raise HTTPException(
            status_code=401,
            detail=errors.safe_error(
                errors.UNAUTHENTICATED,
                "a confirmation must name the engineer who made it",
            ),
        )
    try:
        fact = submittal_review_mod.confirm_fact(
            fact_id,
            allowed_document_ids=scope.allowed_document_ids,
            confirmed_by=scope.user_id,
        )
    except submittal_review_mod.FactNotCurrent as exc:
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "this value was re-read since; confirm the current one",
            ),
        ) from exc
    if fact is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(
                errors.NOT_FOUND, "no datasheet value with that id"
            ),
        )
    return {
        "fact_id": fact["id"],
        "submittal_document_id": fact["submittal_document_id"],
        "field_name": fact["field_name"],
        "confirmed_by": fact["confirmed_by"],
        "confirmed_at": fact["confirmed_at"],
    }


def _finding_counts(review_run_id: str) -> tuple[dict[str, int], int]:
    """This run's findings by compliance status, and how many are held as "the
    value is not trusted yet" (`comparison.LOW_TRUST_VALUE`)."""
    rows = (
        connect()
        .execute(
            "SELECT COALESCE(compliance_status, '') AS s, COUNT(*) AS n, "
            "SUM(CASE WHEN reason_code = ? OR ai_rationale LIKE ? THEN 1 ELSE 0 END) AS held "
            "FROM review_findings WHERE review_run_id = ? GROUP BY s",
            (
                comparison_mod.LOW_TRUST_VALUE,
                comparison_mod.LOW_TRUST_VALUE + "%",
                review_run_id,
            ),
        )
        .fetchall()
    )
    return {r["s"] or "none": r["n"] for r in rows}, sum(r["held"] or 0 for r in rows)


def _run_to_judge_again(review_run_id: str, scope: access.AccessScope) -> dict:
    """The run a batch confirmation may change, or the refusal: 404 no such run
    for this caller; 409 an engineer's final code is set, it is still running,
    or the caller cannot read every standard it uses (judging it again under a
    narrower view would silently drop another engineer's requirements)."""
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no review run with that id"),
        )
    if run.get("engineer_final_code") or (run.get("status") or "") == "running":
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "this review carries an engineer's final code or is still running; "
                "start a new review to change it",
            ),
        )
    in_use = {
        r["standard_document_id"]
        for r in connect().execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1",
            (review_run_id,),
        )
    }
    if not in_use <= scope.allowed_document_ids:
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "you cannot read every standard this review uses, "
                "so it cannot be judged again under your view",
            ),
        )
    return run


def _judge_again(review_run_id: str, scope: access.AccessScope) -> None:
    """The run's own comparison, as the standards override runs it."""
    outcome = (
        comparison_mod.run_outcome(
            review_run_id, allowed_document_ids=scope.allowed_document_ids
        )
        or {}
    )
    comparison_mod.run_comparison(
        review_run_id,
        allowed_document_ids=scope.allowed_document_ids,
        reference_coverage=(outcome.get("completeness") or {}).get(
            "reference_coverage"
        ),
        missing_references=[
            m["identifier"] for m in outcome.get("missing_references") or []
        ],
    )


@router.post(
    "/api/reviews/runs/{review_run_id}/facts/confirm",
    response_model=schemas.FactBatchConfirmation,
    responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409},
)
def confirm_review_facts(
    review_run_id: str,
    body: schemas.FactBatchConfirmRequest,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Order 161 A: the engineer confirms the values of one page they ticked,
    all or none, and the run is judged again so the findings that rested on
    them now state a verdict (or the reason they still cannot).

    The judging is the run's own comparison (`run_comparison`, as the standards
    override does), never a second one; an engineer's earlier decisions on
    findings survive it. 401 unsigned, 404 no such run or value for this
    caller, 409 see `_run_to_judge_again`, or a value was re-read since."""
    if scope.user_id is None:
        raise HTTPException(
            status_code=401,
            detail=errors.safe_error(
                errors.UNAUTHENTICATED,
                "a confirmation must name the engineer who made it",
            ),
        )
    run = _run_to_judge_again(review_run_id, scope)
    try:
        done = submittal_review_mod.confirm_facts(
            body.fact_ids,
            submittal_document_id=run["submittal_document_id"],
            allowed_document_ids=scope.allowed_document_ids,
            confirmed_by=scope.user_id,
        )
    except submittal_review_mod.FactsNotConfirmable as exc:
        if exc.missing:
            raise HTTPException(
                status_code=404,
                detail=errors.safe_error(
                    errors.NOT_FOUND, "a value in the list is not on this review"
                ),
            ) from exc
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "a value in the list was re-read since; confirm the current ones",
            ),
        ) from exc
    status_before, held_before = _finding_counts(review_run_id)
    _judge_again(review_run_id, scope)
    status_after, held_after = _finding_counts(review_run_id)
    return {
        "review_run_id": review_run_id,
        "confirmed": len(done["confirmed"]),
        "already_confirmed": len(done["already"]),
        "held_before": held_before,
        "held_after": held_after,
        "status_before": status_before,
        "status_after": status_after,
        "boundary": "the values of this batch and the findings of this review run only",
    }
