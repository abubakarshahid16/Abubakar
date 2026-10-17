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
from . import submittal_review as submittal_review_mod

router = APIRouter()


@router.post("/api/reviews/facts/{fact_id}/confirm", response_model=schemas.FactConfirmation,
             responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409})
def confirm_review_fact(
    fact_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The engineer confirms one datasheet value. 401 unsigned, 404 not
    theirs to read, 409 re-read since."""
    if scope.user_id is None:
        # Under the unrestricted development mode too: there is no name to
        # write, and `confirmed_by` NULL means "not confirmed".
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, "a confirmation must name the engineer who made it"))
    try:
        fact = submittal_review_mod.confirm_fact(
            fact_id, allowed_document_ids=scope.allowed_document_ids,
            confirmed_by=scope.user_id)
    except submittal_review_mod.FactNotCurrent as exc:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            "this value was re-read since; confirm the current one")) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no datasheet value with that id"))
    return {"fact_id": fact["id"], "submittal_document_id": fact["submittal_document_id"],
            "field_name": fact["field_name"], "confirmed_by": fact["confirmed_by"],
            "confirmed_at": fact["confirmed_at"]}
