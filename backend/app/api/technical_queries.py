from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .. import (
    access,
    answer,
    gmail_auth,
    technical_queries,
    technical_query_docx,
)
from .. import upload as upload_mod
from ..api_utils import _require_identity_to_write

router = APIRouter()


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0, le=100_000_000)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    storage_ref: str | None = None


class ImportIn(BaseModel):
    provider: Literal["synthetic", "microsoft_graph", "gmail"]
    mailbox_id: str | None = None
    provider_message_id: str = Field(min_length=1, max_length=500)
    provider_thread_id: str | None = None
    internet_message_id: str | None = None
    from_address: str = Field(min_length=3, max_length=320)
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=500_000)
    question: str | None = Field(default=None, max_length=50_000)
    contractor_name: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=300)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    sent_at: str | None = None
    received_at: str | None = None
    raw_message_hash: str | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=20)


class DraftIn(BaseModel):
    answer: str = Field(min_length=1, max_length=100_000)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=100)


class EvidenceIn(BaseModel):
    document_id: str
    exact_quote: str = Field(min_length=1, max_length=20_000)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=500)


class EvidenceClassificationIn(BaseModel):
    evidence_state: Literal["verified", "missing", "conflicting", "ambiguous"]
    supersession_state: Literal["current", "superseded", "unknown"] = "current"
    conflict_group: str | None = Field(default=None, max_length=200)


class DecisionIn(BaseModel):
    decision: Literal["request_changes", "approve", "reject", "close"]
    comment: str | None = Field(default=None, max_length=10_000)
    draft_id: str | None = None


class SendIn(BaseModel):
    draft_id: str | None = None
    to_addresses: list[str] = Field(min_length=1, max_length=50)
    cc_addresses: list[str] = Field(default_factory=list, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=200)


class AssignmentIn(BaseModel):
    assignee_user_id: str = Field(min_length=1, max_length=200)


def _visible(scope: access.AccessScope) -> tuple[str | None, bool, bool]:
    return scope.user_id, scope.is_admin, scope.unrestricted


def _safe_item(item: dict, scope: access.AccessScope) -> dict:
    """Hide source material retained after a document grant is revoked."""
    if scope.unrestricted:
        return item
    inaccessible = {
        evidence["document_id"]
        for evidence in item.get("evidence", [])
        if evidence["document_id"] not in scope.allowed_document_ids
    }
    if not inaccessible:
        return item
    return {
        **item,
        "evidence": [
            evidence
            for evidence in item["evidence"]
            if evidence["document_id"] not in inaccessible
        ],
        "drafts": [],
        "source_access_revoked": True,
    }


@router.get("/api/technical-queries")
def list_technical_queries(
    status: str | None = None,
    contractor: str | None = None,
    department: str | None = None,
    assignee_user_id: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
    evidence_state: str | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    return {
        "items": technical_queries.list_queries(
            *_visible(scope),
            status,
            contractor=contractor,
            department=department,
            assignee_user_id=assignee_user_id,
            received_from=received_from,
            received_to=received_to,
            evidence_state=evidence_state,
        )
    }


@router.get("/api/technical-queries/metrics")
def technical_query_metrics(
    contractor: str | None = None,
    department: str | None = None,
    assignee_user_id: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
    evidence_state: str | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    return technical_queries.metrics(
        *_visible(scope),
        contractor=contractor,
        department=department,
        assignee_user_id=assignee_user_id,
        received_from=received_from,
        received_to=received_to,
        evidence_state=evidence_state,
    )


@router.get("/api/technical-queries/providers/microsoft-graph/webhook")
def graph_validation(validationToken: str | None = Query(default=None)):
    if validationToken is None:
        raise HTTPException(status_code=400, detail="validation token is required")
    return PlainTextResponse(validationToken)


@router.get("/api/technical-queries/providers/gmail/oauth/start")
def gmail_oauth_start(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    try:
        return {"authorization_url": gmail_auth.start(scope.user_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/technical-queries/providers/gmail/oauth/callback")
def gmail_oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(
            status_code=400, detail="Gmail OAuth callback requires code and state"
        )
    user_id = gmail_auth.validate_state(state)
    if user_id is None:
        raise HTTPException(
            status_code=400, detail="Gmail OAuth state is invalid or already used"
        )
    # Token exchange is intentionally a separate activation step. This route
    # proves state handling without storing a credential or contacting Google.
    raise HTTPException(
        status_code=501,
        detail="Gmail OAuth callback is prepared; provider token exchange is not activated",
    )


@router.post("/api/technical-queries/providers/microsoft-graph/webhook")
def graph_webhook(_payload: dict):
    # No subscription secret or signature validation has been configured.
    # A public endpoint must not claim to have accepted unverified events.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


@router.post("/api/technical-queries/providers/gmail/webhook")
def gmail_webhook(_payload: dict):
    # Pub/Sub push authentication and durable queueing are prerequisites.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


@router.get("/api/technical-queries/{query_id}")
def get_technical_query(
    query_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/assignment")
def assign_technical_query(
    query_id: str,
    body: AssignmentIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.assign_query(
            query_id,
            body.assignee_user_id,
            scope.user_id,
            scope.is_admin,
            scope.unrestricted,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/import")
def import_technical_query(
    body: ImportIn, scope: access.AccessScope = Depends(access.current_scope)
):
    _require_identity_to_write(scope)
    if body.provider != "synthetic":
        raise HTTPException(
            status_code=422,
            detail="provider messages must arrive through a verified mailbox connection",
        )
    if not scope.unrestricted:
        raise HTTPException(
            status_code=403,
            detail="synthetic import is limited to isolated development mode",
        )
    try:
        item, duplicate = technical_queries.import_message(
            body.model_dump(), scope.user_id, scope.is_admin, scope.unrestricted
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"item": _safe_item(item, scope), "duplicate": duplicate}


@router.post("/api/technical-queries/{query_id}/drafts")
def create_query_draft(
    query_id: str,
    body: DraftIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.add_draft(
            query_id,
            body.answer,
            body.assumptions,
            body.unresolved,
            scope.user_id,
            *_visible(scope),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/generate-draft")
def generate_query_draft(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Generate a grounded draft through the existing citation-checked answer lane."""
    _require_identity_to_write(scope)
    current = technical_queries.get(query_id, *_visible(scope))
    if current is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    usable_evidence = [
        item
        for item in current.get("evidence", [])
        if item["evidence_state"] == "verified"
        and item["supersession_state"] == "current"
        and item["document_id"] in scope.allowed_document_ids
    ]
    if not usable_evidence:
        raise HTTPException(
            status_code=409, detail="verified evidence is required before drafting"
        )
    question = current.get("extracted_question") or " ".join(
        message.get("body", "") for message in current.get("messages", [])
    )
    try:
        result = answer.answer(
            question,
            tier="generated",
            allowed_document_ids=frozenset(
                item["document_id"] for item in usable_evidence
            ),
            model="local",
        )
    except (
        Exception
    ) as exc:  # model availability is an operational failure, not a 500 leak
        raise HTTPException(
            status_code=503, detail="the configured local drafting model is unavailable"
        ) from exc
    if result.get("answer_type") != "generated" or not result.get("answer"):
        raise HTTPException(
            status_code=409, detail="the evidence was insufficient for a grounded draft"
        )
    passages = result.get("passages") or []
    cited = result.get("cited") or []
    if not cited or any(
        not isinstance(index, int)
        or index < 1
        or index > len(passages)
        or not any(
            evidence["document_id"] == passages[index - 1].get("document_id")
            and evidence["page_start"] is not None
            and passages[index - 1].get("page_start") is not None
            and evidence["page_start"] <= passages[index - 1].get("page_end", 0)
            and evidence["page_end"] >= passages[index - 1]["page_start"]
            and evidence["exact_quote"] in (passages[index - 1].get("text") or "")
            for evidence in usable_evidence
        )
        for index in cited
    ):
        raise HTTPException(
            status_code=409,
            detail="the generated answer cited passages outside the query's verified evidence",
        )
    item = technical_queries.add_draft(
        query_id,
        result["answer"],
        [],
        [result.get("reason")] if result.get("reason") else [],
        scope.user_id,
        *_visible(scope),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/evidence")
def add_query_evidence(
    query_id: str,
    body: EvidenceIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.add_evidence(
            query_id,
            body.document_id,
            body.exact_quote,
            body.page_start,
            body.page_end,
            body.locator,
            scope.allowed_document_ids,
            scope.user_id,
            scope.is_admin,
            scope.unrestricted,
            scope.user_id,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/prepare-evidence")
def prepare_query_evidence(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.prepare_evidence(
            query_id,
            scope.allowed_document_ids,
            scope.user_id,
            scope.is_admin,
            scope.unrestricted,
            scope.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.patch("/api/technical-queries/{query_id}/evidence/{evidence_id}")
def classify_query_evidence(
    query_id: str,
    evidence_id: str,
    body: EvidenceClassificationIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    item = technical_queries.update_evidence(
        query_id,
        evidence_id,
        body.evidence_state,
        body.supersession_state,
        body.conflict_group,
        scope.user_id,
        *_visible(scope),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="query or evidence not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/attachments/{attachment_id}/file")
async def upload_query_attachment(
    query_id: str,
    attachment_id: str,
    file: UploadFile = File(...),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Ingest an attachment through the existing guarded document pipeline.

    This first slice permits the isolated development mode and administrators;
    department-specific grants are added with the query workspace in phase 2.
    """
    _require_identity_to_write(scope)
    if not (scope.unrestricted or scope.is_admin):
        raise HTTPException(
            status_code=403,
            detail="query attachment upload requires administrator access",
        )
    attachment = technical_queries.attachment_for_query(
        query_id, attachment_id, *_visible(scope)
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="query attachment not found")
    if attachment["document_id"]:
        raise HTTPException(status_code=409, detail="query attachment already uploaded")
    if file.filename != attachment["filename"]:
        raise HTTPException(
            status_code=422, detail="attachment filename does not match the message"
        )
    digest = hashlib.sha256()
    size = 0
    while block := file.file.read(1024 * 1024):
        size += len(block)
        if size > 100_000_000:
            raise HTTPException(status_code=413, detail="attachment is too large")
        digest.update(block)
    file.file.seek(0)
    if attachment["size_bytes"] and size != attachment["size_bytes"]:
        raise HTTPException(
            status_code=422, detail="attachment size does not match the message"
        )
    if attachment["sha256"] and digest.hexdigest() != attachment["sha256"]:
        raise HTTPException(
            status_code=422, detail="attachment digest does not match the message"
        )
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    item = technical_queries.link_attachment(
        query_id, attachment_id, row["id"], scope.user_id, *_visible(scope)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="query attachment not found")
    return {
        "item": _safe_item(item, scope),
        "document_id": row["id"],
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
    }


@router.post("/api/technical-queries/{query_id}/decisions")
def decide_query(
    query_id: str,
    body: DecisionIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not scope.is_admin:
        raise HTTPException(
            status_code=403, detail="an authorised reviewer is required"
        )
    try:
        item = technical_queries.decide(
            query_id,
            body.decision,
            scope.user_id,
            body.comment,
            body.draft_id,
            *_visible(scope),
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.get("/api/technical-queries/{query_id}/response.docx")
def query_response_docx(
    query_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    if not scope.unrestricted and any(
        evidence["document_id"] not in scope.allowed_document_ids
        for evidence in item.get("evidence", [])
    ):
        raise HTTPException(
            status_code=403,
            detail="source access has changed; response must be reviewed again",
        )
    try:
        path = technical_query_docx.render(item)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"technical-query-{query_id}.docx",
    )


@router.post("/api/technical-queries/{query_id}/send")
def prepare_query_send(
    query_id: str,
    _body: SendIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Refuse sending until the mailbox integration is activated."""
    _require_identity_to_write(scope)
    if technical_queries.get(query_id, *_visible(scope)) is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    raise HTTPException(status_code=503, detail="email sending is not configured")


@router.post("/api/technical-queries/{query_id}/confirm-resolution")
def confirm_query_resolution(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not scope.is_admin:
        raise HTTPException(
            status_code=403, detail="an authorised reviewer is required"
        )
    try:
        item = technical_queries.decide(
            query_id,
            "close",
            scope.user_id,
            "contractor or authorised internal confirmation",
            None,
            *_visible(scope),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)
