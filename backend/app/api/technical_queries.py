from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import access, technical_queries, technical_query_docx
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
    item = technical_queries.add_draft(
        query_id,
        body.answer,
        body.assumptions,
        body.unresolved,
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
    item = technical_queries.decide(
        query_id,
        body.decision,
        scope.user_id,
        body.comment,
        body.draft_id,
        *_visible(scope),
    )
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
