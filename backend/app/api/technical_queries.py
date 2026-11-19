from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .. import (
    access,
    answer,
    email_provider,
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


def _visible(scope: access.AccessScope) -> tuple[str | None, bool, bool]:
    return scope.user_id, scope.is_admin, scope.unrestricted


@router.get("/api/technical-queries")
def list_technical_queries(
    status: str | None = None, scope: access.AccessScope = Depends(access.current_scope)
):
    return {"items": technical_queries.list_queries(*_visible(scope), status)}


@router.get("/api/technical-queries/metrics")
def technical_query_metrics(scope: access.AccessScope = Depends(access.current_scope)):
    return technical_queries.metrics(*_visible(scope))


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
def graph_webhook(payload: dict):
    """Acknowledge and normalize notifications; never fetch or send here."""
    try:
        notifications = email_provider.graph_notifications(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "accepted": len(notifications),
        "notifications": [n.__dict__ for n in notifications],
    }


@router.post("/api/technical-queries/providers/gmail/webhook")
def gmail_webhook(payload: dict):
    notification = email_provider.gmail_notification(payload)
    return {"accepted": notification is not None, "notification": notification}


@router.get("/api/technical-queries/{query_id}")
def get_technical_query(
    query_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return item


@router.post("/api/technical-queries/import")
def import_technical_query(
    body: ImportIn, scope: access.AccessScope = Depends(access.current_scope)
):
    _require_identity_to_write(scope)
    item, duplicate = technical_queries.import_message(
        body.model_dump(), scope.user_id, scope.is_admin, scope.unrestricted
    )
    return {"item": item, "duplicate": duplicate}


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
    return item


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
    if not current.get("evidence"):
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
            allowed_document_ids=scope.allowed_document_ids,
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
    return item


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
    return item


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
    return item


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
    return item


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
    if technical_queries.get(query_id, *_visible(scope)) is None:
        raise HTTPException(status_code=404, detail="technical query not found")
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
        "item": item,
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
    try:
        item = technical_queries.decide(
            query_id,
            body.decision,
            scope.user_id,
            body.comment,
            body.draft_id,
            *_visible(scope),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return item


@router.get("/api/technical-queries/{query_id}/response.docx")
def query_response_docx(
    query_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
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
    body: SendIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Record an explicit send request without contacting an email provider.

    Provider activation is a separate operational change requiring credentials
    and owner approval. This endpoint cannot send accidentally.
    """
    _require_identity_to_write(scope)
    try:
        item = technical_queries.prepare_send(
            query_id,
            body.draft_id,
            body.to_addresses,
            body.cc_addresses,
            body.idempotency_key,
            scope.user_id,
            *_visible(scope),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return {"item": item, "sent": False, "reason": "email provider is not configured"}


@router.post("/api/technical-queries/{query_id}/confirm-resolution")
def confirm_query_resolution(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
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
    return item
