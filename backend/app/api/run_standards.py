"""A run's standards: which ones it compared against and why, and the
engineer's add/remove control (P2). Moved out of main.py with no logic change;
the list takes an optional page and states its total (order 117 item 5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import access, errors, schemas
from .. import applicability as applicability_mod
from .. import comparison as comparison_mod
from .. import paging as paging_mod
from .. import submittal_review as submittal_review_mod
from ..api_utils import (
    _actor_from_scope,
    _require_identity_to_write,
    reject_unknown_params,
)
from ..db import connect

router = APIRouter()


@router.get("/api/reviews/runs/{review_run_id}/standards",
         response_model=schemas.ReviewRunStandardList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def review_run_standards(
    review_run_id: str,
    request: Request,
    include_excluded: bool = Query(False),
    limit: int | None = paging_mod.limit_param(),
    offset: int = paging_mod.offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Which standards this run compared against, and WHY each one is there.

    The reason and the method are passed through unchanged. A semantic match
    says in its own words that it is not a citation, and a screen that
    summarised that away would turn "something was retrieved" into "this
    standard applies" - the substitution section 23 forbids.
    """
    reject_unknown_params(request, {"include_excluded", "limit", "offset"})
    if submittal_review_mod.get_review_run(
            review_run_id,
            allowed_document_ids=scope.allowed_document_ids) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    return _run_standards_payload(review_run_id, scope, include_excluded, limit, offset)


def _run_standards_payload(review_run_id: str, scope: access.AccessScope,
                           include_excluded: bool, limit: int | None = None,
                           offset: int = 0) -> dict:
    """The run's standards, one page of them with their total (order 117 item
    5). The cited-but-missing list is never paged: a page that hid one would
    read as "the library holds everything this submittal cites"."""
    rows = submittal_review_mod.list_applicable_standards(
        review_run_id, allowed_document_ids=scope.allowed_document_ids,
        include_excluded=include_excluded)
    out = []
    for row in rows:
        document = connect().execute(
            "SELECT filename FROM documents WHERE id = ?",
            (row["standard_document_id"],)).fetchone()
        out.append({
            "standard_document_id": row["standard_document_id"],
            "filename": document["filename"] if document else None,
            "selection_method": row.get("selection_method"),
            "selection_reason": row.get("selection_reason"),
            "confidence": row.get("confidence"),
            "included": bool(row.get("included", 1)),
            "exclusion_reason": row.get("exclusion_reason"),
            "evidence_page": row.get("evidence_page"),
            "evidence_quote": row.get("evidence_quote"),
            "scope_decision": row.get("scope_decision"),
        })
    outcome = comparison_mod.run_outcome(
        review_run_id, allowed_document_ids=scope.allowed_document_ids) or {}
    return {
        **paging_mod.page_body("standards", out, limit, offset),
        "missing_references": outcome.get("missing_references") or [],
        "held_for_confirmation": _held_note(outcome, scope),
    }


def _held_note(outcome: dict, scope: access.AccessScope) -> dict | None:
    """#620: the run's note on Company standards it left out while they wait
    for an administrator, as stored; ids only of standards this reader may
    read (rule 5), while the count and sentence stay the run's own."""
    from .. import company_standard_confirm as csc

    note = outcome.get(csc.RUN_NOTE_KEY)
    if not note:
        return None
    allowed = scope.allowed_document_ids
    ids = [
        i
        for i in note.get("standard_document_ids") or []
        if allowed is None or i in allowed
    ]
    return {**note, "standard_document_ids": ids}


@router.post("/api/reviews/runs/{review_run_id}/standards/override",
          response_model=schemas.ReviewRunStandardList,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404,
                     **schemas.ERRORS_409, **schemas.ERRORS_422})
def override_review_standard(
    review_run_id: str,
    body: schemas.StandardOverrideRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """P2: an engineer adds or removes a standard, with a reason, and the run's
    findings are recomputed from the new list.

    THE ENGINEER'S OWN ACT: a signed-in caller, named in the audit row (written
    in the same transaction as the selection). Both documents must be readable
    - a hidden one is the same 404 as a missing one. REFUSED (409) when the
    run carries an engineer's final code (that decision was made about these
    findings; start a new review), while it is still running, or when the
    caller cannot read every standard the run already uses - recomputing under
    a narrower view would silently drop another engineer's requirements.
    Cited standards the library does not hold stay MISSING_LOCALLY: adding a
    different standard does not make a missing one present.
    """
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    if not scope.user_id:
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, "an override must name the engineer who made it"))
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids)
    if run is None or not scope.may_read(body.standard_document_id):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run or standard with that id"))
    if run.get("engineer_final_code"):
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            "this run carries an engineer's final code; start a new review to change its standards"))
    if (run.get("status") or "") == "running":
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "this review is still running"))
    in_use = {r["standard_document_id"] for r in connect().execute(
        "SELECT standard_document_id FROM review_applicable_standards"
        " WHERE review_run_id = ? AND included = 1", (review_run_id,))}
    if not in_use <= scope.allowed_document_ids:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            "you cannot read every standard this review uses, so it cannot be recomputed under your view"))
    outcome = comparison_mod.run_outcome(
        review_run_id, allowed_document_ids=scope.allowed_document_ids) or {}
    try:
        applicability_mod.override(
            review_run_id, body.standard_document_id, include=body.include,
            reason=body.reason, allowed_document_ids=scope.allowed_document_ids,
            actor=_actor_from_scope(scope))
    except applicability_mod.ApplicabilityError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc
    comparison_mod.run_comparison(
        review_run_id, allowed_document_ids=scope.allowed_document_ids,
        reference_coverage=(outcome.get("completeness") or {}).get("reference_coverage"),
        missing_references=[m["identifier"] for m in outcome.get("missing_references") or []])
    return _run_standards_payload(review_run_id, scope, include_excluded=True)
