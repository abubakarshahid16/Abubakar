"""What a document is: classification, kind, the playbook review.

Moved out of main.py with no logic change (planner order 73, #692; system map target structure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import access, schemas
from .. import admin as admin_mod
from .. import classification as classification_mod
from .. import doc_router as doc_router_mod
from .. import playbooks as playbooks_mod
from ..api_utils import reject_unknown_params, require_document

router = APIRouter()


@router.get("/api/classification/vocabulary",
            response_model=schemas.ClassificationVocabulary)
def classification_vocabulary(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The filter vocabulary, plus this caller's needs-classification count.

    THE VOCABULARY IS NOT SCOPED AND THE COUNT IS. A discipline the caller
    cannot read stays listed: discipline names are project structure, not
    evidence that a document exists, and hiding one teaches a user the system
    is broken rather than that they need access. The count is a statement
    about documents, so it is bounded by what they may read.
    """
    reject_unknown_params(request, set())
    return {**classification_mod.vocabulary(),
            "needs_classification":
                classification_mod.needs_classification(scope)}


@router.get("/api/classification/coverage",
            response_model=schemas.ClassificationCoverage)
def classification_coverage(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Counts per axis, scoped, with `in_register` NULL when none is loaded."""
    reject_unknown_params(request, set())
    return classification_mod.coverage(scope)


@router.get("/api/documents/{document_id}/classification",
            response_model=schemas.DocumentClassification,
            responses={**schemas.ERRORS_404})
def get_document_classification(
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """404 outside the caller's scope - the same answer every read path gives,
    and the reason they are 404 rather than 403: a 403 confirms the document
    exists."""
    require_document(document_id, scope)
    row = classification_mod.of_document(document_id)
    if row is None:
        # In scope but never classified. An empty, honest record rather than a
        # 404: the document exists and the caller may read it, and "not
        # classified yet" is the answer.
        return classification_mod.empty_record(document_id)
    return {**row, "document_id": document_id}


@router.put("/api/documents/{document_id}/classification",
            response_model=schemas.DocumentClassification,
            responses={**schemas.ERRORS_404})
def put_document_classification(
    document_id: str,
    body: schemas.ClassificationUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """CONFIRM or CHANGE a classification. THE ADMIN CAPABILITY IS REQUIRED.

    A wrong classification misroutes searches for EVERYONE, not only for the
    person who set it, so this needs a role that answers for everyone.
    `admin_mod.current_admin` is the same gate the admin surface uses and
    answers 404 rather than 403 to a non-admin - saying nothing about whether
    the document exists.

    The document must ALSO be in the caller's scope. An administrator holds
    every grant in practice, but the check is not skipped on that basis: the
    two questions are separate and this route asks both.
    """
    require_document(document_id, scope)
    classification_mod.confirm(
        document_id, doc_type=body.doc_type, discipline=body.discipline,
        doc_class=body.doc_class, subject_ids=body.subject_ids,
        confirmed_by=(actor or {}).get("id"),
        # The submittal-review metadata. `document_role` arrived through
        # `schemas.DocumentRole`, so an unknown role was already refused with a
        # 422 naming the field and cannot reach the column.
        metadata={name: getattr(body, name)
                  for name in classification_mod.METADATA_FIELDS},
        equipment_tags=body.equipment_tags)
    row = classification_mod.of_document(document_id) or {}
    return {**row, "document_id": document_id}


@router.post("/api/documents/{document_id}/playbook-review", response_model=schemas.PlaybookReport,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def playbook_review(
    document_id: str,
    body: schemas.PlaybookReviewRequest,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Review one document the caller may read against a playbook: per element
    present, unclear, missing, could not be checked, or standard not held (never
    "met"). Cited by the passage's locator. `use_ai` lets the LOCAL model propose
    a quote for an element the cue words did not settle; a proposal is kept only
    when its quote is verbatim in the passage it names."""
    require_document(document_id, scope)
    found, _broken = playbooks_mod.available()
    playbook = found.get(body.playbook_id)
    if playbook is None:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_playbook", "message": f"no usable playbook {body.playbook_id!r}"})
    proposer = playbooks_mod.task_proposer() if body.use_ai else None
    return playbooks_mod.review(document_id, playbook, allowed_document_ids=scope.allowed_document_ids,
                                proposer=proposer)


@router.get("/api/document-kinds", response_model=schemas.DocumentKindVocabulary,
            responses={**schemas.ERRORS_404})
def get_document_kinds(scope: access.AccessScope = Depends(access.current_scope)):
    """The document types the router knows, and how many of the caller's OWN
    documents are in each routing state (rule 5: a count states whose
    documents it counts)."""
    allowed = None if scope.unrestricted else scope.allowed_document_ids
    return {"kinds": doc_router_mod.kinds(), "counts": doc_router_mod.counts(allowed)}


@router.put("/api/documents/{document_id}/kind", response_model=schemas.DocumentClassification,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def put_document_kind(
    document_id: str,
    body: schemas.DocumentKindUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """A person confirms (or corrects) the document type the router suggested.
    Admin-gated like the rest of classification; a kind outside the vocabulary
    is a 422 naming it. Classification is not access control: this changes what
    the document is called, never who may read it."""
    require_document(document_id, scope)
    try:
        doc_router_mod.confirm(document_id, body.kind, (actor or {}).get("id"))
    except doc_router_mod.UnknownKind as exc:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_document_kind", "message": str(exc)}) from exc
    row = classification_mod.of_document(document_id) or {}
    return {**row, "document_id": document_id}
