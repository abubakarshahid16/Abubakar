from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import access, technical_queries
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


class DecisionIn(BaseModel):
    decision: Literal["request_changes", "approve", "reject", "close"]
    comment: str | None = Field(default=None, max_length=10_000)
    draft_id: str | None = None


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
