"""The standards library: list, inventory, missing and cited standards, provenance,
the OKF concepts, clauses, requirements and their extraction, tables, conflicts,
the verification queue, clause checks, revisions and supersede.

Moved out of main.py with no logic change (planner order 79a, #692; system map target structure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import access, errors, schemas
from .. import admin as admin_mod
from .. import job_queue as job_queue_mod
from .. import okf as okf_mod
from .. import standards as standards_mod
from .. import standards_acquisition as standards_acquisition_mod
from .. import standards_inventory as standards_inventory_mod
from ..api_utils import _require_named_reviewer, reject_unknown_params, require_document
from ..paging import page_of

router = APIRouter()

#: optional page of a bare-list route; the total is in `X-Total-Count` (order 117 item 5)
_LIMIT = Query(None, ge=1, le=1000, description="page size; omit for every row")
_OFFSET = Query(0, ge=0)


# ------------------------------------------------------------- standards
#
# THE LIBRARY IS LOGICALLY SEPARATE AND PHYSICALLY THE SAME DATABASE. These
# routes read the same `documents` and `chunks` rows as everything else, under
# the same grants, through the same scope. "A dedicated library" is a statement
# about what a reader sees, never about where the bytes live.


@router.get("/api/standards", response_model=list[schemas.StandardSummary],
            responses=schemas.ERRORS_422)
def list_standards(
    request: Request,
    response: Response,
    include_superseded: bool = Query(True),
    limit: int | None = _LIMIT,
    offset: int = _OFFSET,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every COMPANY_STANDARD the caller may read.

    The role decides what belongs in the library; the grants decide what this
    caller may see. They are ANDed in the query, so the library is always a
    subset of what the caller already holds.
    """
    reject_unknown_params(request, {"include_superseded", "limit", "offset"})
    return page_of(
        standards_mod.list_standards(
            allowed_document_ids=scope.allowed_document_ids,
            include_superseded=include_superseded,
        ),
        limit,
        offset,
        response,
    )


@router.get("/api/standards/inventory",
            response_model=list[schemas.StandardInventoryEntry],
            responses=schemas.ERRORS_422)
def standards_inventory(
    request: Request,
    response: Response,
    include_superseded: bool = Query(True),
    limit: int | None = _LIMIT,
    offset: int = _OFFSET,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The standards inventory (B5 part 2): every COMPANY_STANDARD the
    caller may read, with family, licence status, source-file hash, and
    whether any submittal the caller may read cites it.

    Same scope rule as `/api/standards` (CLAUDE.md rule 5): the role decides
    what belongs in the library, the grants decide what this caller may see,
    ANDed - never widened by this route.
    """
    reject_unknown_params(request, {"include_superseded", "limit", "offset"})
    return page_of(
        standards_inventory_mod.inventory_rows(
            allowed_document_ids=scope.allowed_document_ids,
            include_superseded=include_superseded,
        ),
        limit,
        offset,
        response,
    )


@router.get("/api/standards/cited-but-not-held",
            response_model=list[schemas.CitedButNotHeld],
            responses=schemas.ERRORS_422)
def standards_cited_but_not_held(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every standard cited by a submittal or a SAES requirement's own
    normative reference that is NOT in the local library, with where it was
    cited - the missing list for the CRS and for the owner to take to the
    standards body.

    Same scope rule as every other standards route (CLAUDE.md rule 5): the
    caller's own grants bound which submittals and which standards this can
    ever see - never widened by this route.
    """
    reject_unknown_params(request, set())
    return standards_inventory_mod.cited_but_not_held(
        allowed_document_ids=scope.allowed_document_ids)


@router.get("/api/standards/missing",
            response_model=list[schemas.MissingStandard],
            responses=schemas.ERRORS_422)
def standards_missing(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Standards beyond the library - API, ASME, ASTM, ISO, IEC, NFPA, NACE,
    NORSOK, and the client's own - that a submittal or a SAES requirement
    cites and the library does not hold, each with the publisher's own
    catalogue page and whether it has been requested. Nothing is fetched:
    every one of these is sold under licence (standards_acquisition.py).
    Scope: exactly the cited-but-not-held list's (CLAUDE.md rule 5)."""
    reject_unknown_params(request, set())
    return standards_acquisition_mod.missing_standards(
        allowed_document_ids=scope.allowed_document_ids)


@router.post("/api/standards/missing/request",
             response_model=schemas.StandardRequestResult,
             responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def request_missing_standard(
    body: schemas.StandardRequestBody,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Record that a missing standard has been asked for, under the signed-in
    engineer's name. Only a standard on the caller's own missing list."""
    _require_named_reviewer(scope, "requesting a standard")
    try:
        return standards_acquisition_mod.mark_requested(
            body.identifier, user_id=scope.user_id, note=body.note,
            allowed_document_ids=scope.allowed_document_ids)
    except standards_acquisition_mod.AcquisitionError as exc:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, str(exc))) from exc


@router.post("/api/standards/{document_id}/provenance",
             response_model=schemas.StandardProvenance,
             responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def record_standard_provenance(
    document_id: str,
    body: schemas.ExternalCopyBody,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Mark an uploaded standard as a copy obtained externally - the client's
    "stored, hashed, cited and marked as externally obtained" - recording
    where it came from, the file's hash, and who recorded it."""
    _require_named_reviewer(scope, "recording where a standard came from")
    try:
        return standards_acquisition_mod.record_external_copy(
            document_id, identifier=body.identifier,
            obtained_from=body.obtained_from, user_id=scope.user_id,
            allowed_document_ids=scope.allowed_document_ids)
    except standards_acquisition_mod.AcquisitionError as exc:
        status = 404 if "no such" in str(exc) else 422
        raise HTTPException(status_code=status, detail=errors.safe_error(
            errors.NOT_FOUND if status == 404 else errors.INVALID_PARAMETER, str(exc))) from exc


@router.get("/api/standards/{document_id}/provenance",
            response_model=schemas.StandardProvenanceRead,
            responses={**schemas.ERRORS_404})
def get_standard_provenance(
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Where a held standard's copy came from, or null when nothing was
    recorded (not claimed either way)."""
    if document_id not in scope.allowed_document_ids:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such standard"))
    return {"provenance": standards_acquisition_mod.provenance_of(document_id)}


@router.get("/api/standards/{document_id}/okf", response_model=schemas.OkfReport,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_okf_report(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """#513: the OKF build report for one standard - how many concepts and
    cited links its stored requirements give, and how many requirements'
    citations do not resolve, by reason. Counts and ids only; read only
    (nothing is written, no file is made)."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    built = okf_mod.build([document_id], allowed_document_ids=scope.allowed_document_ids)
    return {"document_id": document_id, **built["report"],
            "problems": len(okf_mod.problems(built["concepts"]))}


def _okf_concept_or_404(document_id: str, concept_id: str,
                        scope: access.AccessScope) -> dict:
    built = okf_mod.build([document_id], allowed_document_ids=scope.allowed_document_ids)
    concept = next((c for c in built["concepts"] if c["id"] == concept_id), None)
    if concept is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such OKF concept"))
    return concept


@router.post("/api/standards/{document_id}/okf/concepts/{concept_id}/approve",
             response_model=schemas.OkfApproval,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def approve_okf_concept(
    document_id: str,
    concept_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """R29/#833: an engineer confirms one OKF concept, at its CURRENT
    content hash. Re-deciding an already-confirmed concept at the same
    content is a no-op in effect (the same decision, re-dated)."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    concept = _okf_concept_or_404(document_id, concept_id, scope)
    okf_mod.approve(concept["id"], concept["content_sha256"], decided_by=scope.user_id)
    return okf_mod.approval_status(concept)


@router.post("/api/standards/{document_id}/okf/concepts/{concept_id}/reject",
             response_model=schemas.OkfApproval,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def reject_okf_concept(
    document_id: str,
    concept_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """R29/#833: an engineer rejects one OKF concept, at its CURRENT
    content hash."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    concept = _okf_concept_or_404(document_id, concept_id, scope)
    okf_mod.reject(concept["id"], concept["content_sha256"], decided_by=scope.user_id)
    return okf_mod.approval_status(concept)


@router.get("/api/standards/{document_id}/clauses",
            response_model=list[schemas.StandardClause],
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_clauses(
    document_id: str,
    request: Request,
    response: Response,
    limit: int | None = _LIMIT,
    offset: int = _OFFSET,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The clause hierarchy, read from the chunks the document already has."""
    reject_unknown_params(request, {"limit", "offset"})
    require_document(document_id, scope)
    return page_of(
        standards_mod.clause_hierarchy(
            document_id, allowed_document_ids=scope.allowed_document_ids
        ),
        limit,
        offset,
        response,
    )


@router.get("/api/standards/{document_id}/requirements",
            response_model=list[schemas.StandardRequirement],
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_requirements(
    document_id: str,
    request: Request,
    response: Response,
    limit: int | None = _LIMIT,
    offset: int = _OFFSET,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"limit", "offset"})
    require_document(document_id, scope)
    return page_of(
        standards_mod.list_requirements(
            document_id, allowed_document_ids=scope.allowed_document_ids
        ),
        limit,
        offset,
        response,
    )


@router.post("/api/standards/{document_id}/requirements/extract",
             response_model=schemas.StandardExtraction,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def extract_standard_requirements(
    document_id: str,
    request: Request,
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Re-read a standard and record every obligation it states.

    THE ADMIN CAPABILITY IS REQUIRED. Extraction replaces the unconfirmed rows
    for a standard, which changes what every later reader sees, so it needs the
    role that answers for everyone - the same reasoning as classification.
    Confirmed rows are never deleted. B38: replacing rows review findings cite
    is refused (409) unless acknowledge_orphaned_findings=true.
    """
    reject_unknown_params(request, {"acknowledge_orphaned_findings"})
    require_document(document_id, scope)
    return standards_mod.extract_requirements(
        document_id, allowed_document_ids=scope.allowed_document_ids, actor=actor,
        acknowledge_orphaned_findings=acknowledge_orphaned_findings)


@router.get("/api/standards/{document_id}/tables",
            response_model=schemas.TableReport,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_tables(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every table of a standard, parsed or explicitly UNPARSED.

    The unparsed ones are the point: `parsed_fraction` is the honest measure of
    how much of a standard's tabular content was actually read, and a
    requirement set with the sentences and none of the tables looks complete
    while missing the numbers an engineer checks against.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.table_report(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@router.get("/api/standards/conflicts",
            response_model=list[schemas.RequirementConflict],
            responses=schemas.ERRORS_422)
def standard_conflicts(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Fields two standards limit differently. SURFACED, NEVER RESOLVED.

    Only over standards the caller may read, so a conflict involving a document
    they hold no grant for is not shown at all - rather than shown with one
    side missing, which would disclose that the other side exists.
    """
    reject_unknown_params(request, set())
    return standards_mod.conflicts(allowed_document_ids=scope.allowed_document_ids)


@router.get("/api/standards/verification-queue",
            response_model=list[schemas.StandardRequirement],
            responses=schemas.ERRORS_422)
def standard_verification_queue(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Requirements awaiting a human, across every standard the caller may read."""
    reject_unknown_params(request, {"limit"})
    rows = standards_mod.verification_queue(
        allowed_document_ids=scope.allowed_document_ids, limit=limit)
    return [
        {**row, "exceptions": standards_mod.requirements_3b.decode_exceptions(
            row.get("exceptions"))}
        for row in rows
    ]


@router.post("/api/standards/requirements/{requirement_id}/decision",
             response_model=schemas.RequirementDecisionResult,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def decide_standard_requirement(
    requirement_id: str,
    body: schemas.RequirementDecisionRequest,
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Confirm, edit or reject an extracted requirement. ADMIN, and AUDITED.

    A correction sets `extraction_method` to 'human': after it the row is a
    person's statement rather than a machine's guess, and nothing downstream
    may present it as extracted. B38: rejecting a requirement review findings
    cite is refused (409) unless acknowledge_orphaned_findings=true.
    """
    try:
        return standards_mod.decide_requirement(
            requirement_id, decision=body.decision,
            allowed_document_ids=scope.allowed_document_ids,
            actor=actor, edits=body.edits,
            acknowledge_orphaned_findings=acknowledge_orphaned_findings)
    except standards_mod.RequirementError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc


@router.get("/api/standards/clause-checks",
            response_model=list[schemas.ClauseCheckDraft],
            responses=schemas.ERRORS_422)
def list_clause_checks(
    request: Request,
    status: str = Query("draft", pattern="^(draft|accepted|rejected|replaced)$"),
    limit: int = Query(200, ge=1, le=500),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """#645: checks the AI proposed for clause sentences and code verified,
    for the standards the caller may read. Read only."""
    reject_unknown_params(request, {"status", "limit"})
    from .. import ai_requirements
    return ai_requirements.list_drafts(
        allowed_document_ids=scope.allowed_document_ids, status=status, limit=limit)


@router.post("/api/standards/clause-checks/{draft_id}/decision",
             response_model=schemas.ClauseCheckDecisionResult,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def decide_clause_check(
    draft_id: str,
    body: schemas.ClauseCheckDecisionRequest,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """#645: accept or reject a clause-check draft. ADMIN, and AUDITED.

    Accept is verified by code again and VERSIONED: a new confirmed numeric
    limit is written and the sentence row is superseded, not deleted. A draft
    the caller may not read is 404, like every route."""
    from .. import ai_requirements
    try:
        return ai_requirements.decide_draft(
            draft_id, decision=body.decision,
            allowed_document_ids=scope.allowed_document_ids, actor=actor)
    except ai_requirements.DraftError as exc:
        status = 404 if str(exc).startswith("no clause-check draft") else 422
        raise HTTPException(status_code=status, detail=errors.safe_error(
            errors.NOT_FOUND if status == 404 else errors.INVALID_PARAMETER,
            str(exc))) from exc


@router.post("/api/standards/{document_id}/requirements/extract-async",
             response_model=schemas.ExtractionJob,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def queue_standard_extraction(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Queue extraction on the EXISTING worker rather than blocking this request.

    Master plan section 26 asks that long-running work use the background job
    mechanism and expose progress without blocking. Section 24 allows one
    worker and puts background standard reprocessing LAST, so this queues onto
    the ingestion worker and is drained only when no document needs processing.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    # INTERACTIVE (#177): an administrator is waiting on this one, so it
    # runs ahead of the backfill the ingestion hook queues for every standard.
    job_id = standards_mod.enqueue_extraction(
        document_id, actor=actor, priority=job_queue_mod.PRIORITY_INTERACTIVE)
    return {"job_id": job_id, "document_id": document_id, "state": "queued"}


@router.get("/api/standards/{document_id}/extraction-state",
            response_model=schemas.ExtractionJob,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_extraction_state(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    state = standards_mod.extraction_job_state(
        document_id, allowed_document_ids=scope.allowed_document_ids)
    return state or {"state": "none"}


@router.get("/api/standards/{document_id}/revisions",
            response_model=list[schemas.StandardSummary],
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_revisions(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every revision of the same standard number the caller may read."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.revision_history(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@router.post("/api/standards/{document_id}/supersede",
             response_model=schemas.SupersedeRequest,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def supersede_standard(
    document_id: str,
    body: schemas.SupersedeRequest,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Mark a standard as replaced, or clear the mark. ADMIN, and AUDITED.

    A superseded standard stops being SELECTED for new reviews and stays fully
    readable and citable - an engineer must still be able to open the revision
    a submittal was reviewed against last year.
    """
    require_document(document_id, scope)
    try:
        result = standards_mod.supersede(
            document_id, body.superseded_by,
            allowed_document_ids=scope.allowed_document_ids, actor=actor)
    except standards_mod.RequirementError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc), document_id=document_id)) from exc
    return {"superseded_by": result["superseded_by"]}
