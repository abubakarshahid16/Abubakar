from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import (
    access,
    answer,
    errors,
    gmail_auth,
    gmail_sync,
    gmail_worker,
    technical_queries,
    technical_query_docx,
)
from .. import upload as upload_mod
from ..api_utils import _require_identity_to_write
from ..config import settings
from ..db import connect
from ..gmail_client import GmailApiClient

router = APIRouter(dependencies=[Depends(technical_queries.ensure_ready)])


class _Open(BaseModel):
    """A response model that names the fields every client relies on and lets the rest through."""

    model_config = ConfigDict(extra="allow")


class QueryOut(_Open):
    id: str
    subject: str
    status: str
    can_review: bool | None = None


class QueryList(BaseModel):
    items: list[QueryOut]


class ImportOut(BaseModel):
    item: QueryOut
    duplicate: bool


class AttachmentOut(_Open):
    item: QueryOut
    document_id: str | None = None


class SendOut(_Open):
    item: QueryOut
    sent: bool
    provider_message_id: str | None = None


class MetricsOut(BaseModel):
    received: int = 0
    triage: int = 0
    drafting: int = 0
    awaiting_review: int = 0
    changes_requested: int = 0
    approved: int = 0
    send_pending: int = 0
    sent: int = 0
    awaiting_confirmation: int = 0
    resolved: int = 0
    duplicate: int = 0
    cancelled: int = 0
    failed: int = 0
    total: int = 0


class MailboxConnectedOut(BaseModel):
    mailbox_id: str
    email: str
    connection_state: str


class WebhookAckOut(BaseModel):
    accepted: bool


class RowsOut(BaseModel):
    items: list[dict[str, Any]]


class OauthStartOut(BaseModel):
    authorization_url: str


class ActivateOut(BaseModel):
    imported: int
    connection_state: str


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


class GenerateDraftIn(BaseModel):
    """Which engine writes the draft answer. `claude` is refused unless its own switch is on (the owner has not approved that lane)."""

    engine: Literal["local", "claude"] = "local"


class ManualOut(_Open):
    item: QueryOut
    uploaded: int = 0


class DraftIn(BaseModel):
    answer: str = Field(min_length=1, max_length=100_000)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=100)


class RoutingRuleIn(BaseModel):
    match_type: Literal["address", "domain"]
    match_value: str = Field(min_length=3, max_length=320)
    contractor_name: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=300)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=technical_queries.MAX_CONFIRMED_QUESTION)


class EvidenceIn(BaseModel):
    document_id: str
    exact_quote: str = Field(min_length=1, max_length=20_000)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=500)


class EvidenceClassificationIn(BaseModel):
    evidence_state: Literal["verified", "missing", "conflicting", "ambiguous", "rejected"]  # a reviewer sets these; "proposed" is the system's own
    supersession_state: Literal["current", "superseded", "unknown"] = "unknown"
    conflict_group: str | None = Field(default=None, max_length=200)


class DecisionIn(BaseModel):
    decision: Literal["request_changes", "approve", "reject", "close"]
    comment: str | None = Field(default=None, max_length=10_000)
    draft_id: str | None = None


class SendIn(BaseModel):
    draft_id: str = Field(min_length=1, max_length=200)
    mailbox_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)


class AssignmentIn(BaseModel):
    assignee_user_id: str = Field(min_length=1, max_length=200)


class TriageIn(BaseModel):
    contractor_name: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=300)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: str | None = Field(default=None, max_length=40)


class ReconcileSendIn(BaseModel):
    outcome: Literal["sent", "not_sent"]
    provider_message_id: str | None = Field(default=None, max_length=500)
    comment: str = Field(min_length=1, max_length=1000)


class GmailLabelIn(BaseModel):
    label_id: str = Field(min_length=1, max_length=200)


def _refuse(status_code: int, message: str, code: str = errors.INVALID_PARAMETER):
    """A refusal the screen can show in words: the shared client renders a server
    reason only when it arrives as {code, message}, never as a bare string."""
    return HTTPException(status_code=status_code, detail=errors.safe_error(code, message))


def _reviewer(scope: access.AccessScope) -> bool:
    return technical_queries.is_reviewer(scope.capabilities, scope.unrestricted)


def _visible(scope: access.AccessScope) -> tuple[str | None, bool, bool]:
    return scope.user_id, scope.is_admin, scope.unrestricted


def _safe_item(item: dict, scope: access.AccessScope) -> dict:
    """Hide source material retained after a document grant is revoked."""
    item = {
        **item,
        "can_review": _reviewer(scope),
        "messages": [
            {key: value for key, value in message.items() if key != "raw_storage_ref"}
            for message in item.get("messages", [])
        ],
    }
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


@router.get("/api/technical-queries", response_model=QueryList)
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


@router.get("/api/technical-queries/metrics", response_model=MetricsOut)
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


@router.get("/api/technical-queries/providers/microsoft-graph/webhook", response_class=PlainTextResponse, responses={200: {"content": {"text/plain": {"schema": {"type": "string"}}}}})
def graph_validation(validationToken: str | None = Query(default=None)):
    if validationToken is None:
        raise HTTPException(status_code=400, detail="validation token is required")
    return PlainTextResponse(validationToken)


@router.get("/api/technical-queries/providers/gmail/oauth/start", response_model=OauthStartOut)
def gmail_oauth_start(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(
            status_code=403, detail="only an administrator can connect a mailbox"
        )
    try:
        gmail_auth.connection_ready()
        return {"authorization_url": gmail_auth.start(scope.user_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/technical-queries/providers/gmail/mailboxes", response_model=RowsOut)
def gmail_mailboxes(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(
            status_code=403, detail="only an administrator can view connected mailboxes"
        )
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,email,label_id,connection_state FROM gmail_mailboxes WHERE owner_user_id=? ORDER BY email",
            (scope.user_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/api/technical-queries/providers/gmail/mailboxes/{mailbox_id}/labels", response_model=RowsOut)
def gmail_mailbox_labels(
    mailbox_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT 1 FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state='needs_label'",
            (mailbox_id, scope.user_id),
        ).fetchone()
    if mailbox is None:
        raise HTTPException(
            status_code=404, detail="mailbox is not awaiting label selection"
        )
    try:
        return {"items": GmailApiClient(gmail_auth.access_token(mailbox_id)).labels()}
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Gmail labels are unavailable"
        ) from exc


@router.post("/api/technical-queries/providers/gmail/mailboxes/{mailbox_id}/activate", response_model=ActivateOut)
def activate_gmail_mailbox(
    mailbox_id: str,
    body: GmailLabelIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT 1 FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state='needs_label'",
            (mailbox_id, scope.user_id),
        ).fetchone()
    if mailbox is None:
        raise HTTPException(
            status_code=404, detail="mailbox is not awaiting label selection"
        )
    try:
        imported = gmail_worker.activate_label(
            GmailApiClient(gmail_auth.access_token(mailbox_id)),
            mailbox_id,
            scope.user_id,
            body.label_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Gmail label import did not finish; retry safely"
        ) from exc
    gmail_sync.start()
    return {"imported": len(imported), "connection_state": "active"}


@router.get("/api/technical-queries/providers/gmail/oauth/callback", response_model=MailboxConnectedOut)
def gmail_oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(
            status_code=400, detail="Gmail OAuth callback requires code and state"
        )
    try:
        mailbox = gmail_auth.complete(code, state)
        gmail_sync.start()
        return mailbox
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Gmail connection could not be completed; try again"
        ) from exc


@router.post("/api/technical-queries/providers/microsoft-graph/webhook", response_model=WebhookAckOut)
def graph_webhook(_payload: dict):
    # No subscription secret or signature validation has been configured.
    # A public endpoint must not claim to have accepted unverified events.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


@router.post("/api/technical-queries/providers/gmail/webhook", response_model=WebhookAckOut)
def gmail_webhook(_payload: dict):
    # Pub/Sub push authentication and durable queueing are prerequisites.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


@router.get("/api/technical-queries/routing-rules", response_model=RowsOut)
def get_routing_rules(scope: access.AccessScope = Depends(access.current_scope)):
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    return {"items": technical_queries.list_routing_rules()}


@router.put("/api/technical-queries/routing-rules", response_model=RowsOut)
def put_routing_rule(
    body: RoutingRuleIn, scope: access.AccessScope = Depends(access.current_scope)
):
    if not scope.user_id:
        raise _refuse(403, "an administrator is required")
    try:
        items = technical_queries.set_routing_rule(
            body.match_type, body.match_value, body.contractor_name, body.department,
            scope.user_id, scope.is_admin,
        )
    except PermissionError as exc:
        raise _refuse(403, str(exc)) from exc
    except ValueError as exc:
        raise _refuse(422, str(exc)) from exc
    return {"items": items}


@router.delete("/api/technical-queries/routing-rules/{rule_id}", response_model=RowsOut)
def remove_routing_rule(
    rule_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    if not scope.user_id:
        raise _refuse(403, "an administrator is required")
    try:
        return {"items": technical_queries.delete_routing_rule(rule_id, scope.is_admin)}
    except PermissionError as exc:
        raise _refuse(403, str(exc)) from exc


@router.get("/api/technical-queries/reviewers", response_model=RowsOut)
def list_technical_query_reviewers(scope: access.AccessScope = Depends(access.current_scope)):
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    return {"items": technical_queries.list_reviewers()}


@router.put("/api/technical-queries/reviewers/{user_id}", response_model=RowsOut)
def grant_technical_query_reviewer(
    user_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    return _change_reviewer(user_id, True, scope)


@router.delete("/api/technical-queries/reviewers/{user_id}", response_model=RowsOut)
def revoke_technical_query_reviewer(
    user_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    return _change_reviewer(user_id, False, scope)


def _change_reviewer(user_id: str, granted: bool, scope: access.AccessScope):
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    actor = {"id": scope.user_id, "email": None}
    try:
        found = technical_queries.set_reviewer(user_id, granted, actor)
    except PermissionError as exc:
        raise _refuse(403, str(exc)) from exc
    except ValueError as exc:
        raise _refuse(409, str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail="user not found")
    return {"items": technical_queries.list_reviewers()}


@router.get("/api/technical-queries/assignees", response_model=RowsOut)
def technical_query_assignees(
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not scope.is_admin:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,display_name FROM users WHERE is_active=1 ORDER BY display_name"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/api/technical-queries/{query_id}", response_model=QueryOut)
def get_technical_query(
    query_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.get("/api/technical-queries/{query_id}/messages/{message_id}/original.eml", response_class=FileResponse, responses={200: {"content": {"message/rfc822": {"schema": {"type": "string", "format": "binary"}}}}})
def download_original_query_email(
    query_id: str,
    message_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    message = next((row for row in item["messages"] if row["id"] == message_id), None)
    if message is None or not message.get("raw_storage_ref"):
        raise HTTPException(status_code=404, detail="original email not stored")
    folder = (settings.data_dir / "technical_query_mail").resolve()
    path = Path(message["raw_storage_ref"]).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise HTTPException(status_code=404, detail="original email not stored")
    if hashlib.sha256(path.read_bytes()).hexdigest() != message["raw_message_hash"]:
        raise HTTPException(
            status_code=409, detail="stored original email failed integrity check"
        )
    return FileResponse(
        path, media_type="message/rfc822", filename=f"query-message-{message_id}.eml"
    )


@router.post("/api/technical-queries/{query_id}/assignment", response_model=QueryOut)
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


@router.post("/api/technical-queries/{query_id}/triage", response_model=QueryOut)
def triage_technical_query(
    query_id: str,
    body: TriageIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.triage_query(
            query_id,
            body.contractor_name.strip() or None if body.contractor_name else None,
            body.department.strip() or None if body.department else None,
            body.priority,
            body.due_at,
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


@router.post("/api/technical-queries/import", response_model=ImportOut)
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


@router.post("/api/technical-queries/manual", response_model=ManualOut)
async def new_query_by_hand(
    subject: str = Form(..., min_length=1, max_length=500),
    body: str = Form(..., min_length=1, max_length=500_000),
    contractor_name: str | None = Form(default=None, max_length=300),
    from_address: str = Form(default="entered by hand", min_length=3, max_length=320),
    question: str | None = Form(default=None, max_length=50_000),
    files: list[UploadFile] = File(default_factory=list),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """A query entered by hand, with its papers uploaded, so the feature works with no mailbox. A qualified reviewer or an administrator
    makes it; the files (administrator only, as for any query attachment) go through the guarded document pipeline and the attachment
    safety check, exactly like an emailed attachment."""
    _require_identity_to_write(scope)
    if not (_reviewer(scope) or scope.is_admin or scope.unrestricted):
        raise _refuse(403, "a qualified technical-query reviewer or an administrator is required to enter a query")
    if files and not (scope.unrestricted or scope.is_admin):
        raise _refuse(403, "uploading the papers of a query requires administrator access")
    attachments = []
    for upload in files:
        digest, size = hashlib.sha256(), 0
        while block := upload.file.read(1024 * 1024):
            size += len(block)
            if size > 100_000_000:
                raise HTTPException(status_code=413, detail="attachment is too large")
            digest.update(block)
        upload.file.seek(0)
        attachments.append(
            {
                "filename": upload.filename or "",
                "media_type": upload.content_type or "application/octet-stream",
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            }
        )
    envelope = {
        "provider": "manual",
        "mailbox_id": None,
        "provider_message_id": f"manual-{uuid.uuid4()}",
        "from_address": from_address,
        "to_addresses": [],
        "cc_addresses": [],
        "subject": subject,
        "body": body,
        "question": question,
        "contractor_name": contractor_name,
        "attachments": attachments,
    }
    try:
        item, _dup = technical_queries.import_message(envelope, scope.user_id, scope.is_admin, scope.unrestricted)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 422, detail=str(exc)) from exc
    rows = [a for m in item.get("messages", []) for a in m.get("attachments", [])]
    uploaded = 0
    for upload, row in zip(files, rows, strict=False):
        _ingest_query_attachment(item["id"], row, upload, scope)
        uploaded += 1
    refreshed = technical_queries.get(item["id"], *_visible(scope)) or item
    return {"item": _safe_item(refreshed, scope), "uploaded": uploaded}


@router.post("/api/technical-queries/{query_id}/drafts", response_model=QueryOut)
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
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/confirm-question", response_model=QueryOut)
def confirm_query_question(
    query_id: str,
    body: QuestionIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """An engineer confirms the wording the draft will answer. The email stays as
    received; this is the clean question the answer checks are run on."""
    _require_identity_to_write(scope)
    try:
        item = technical_queries.confirm_question(
            query_id, body.question, *_visible(scope), scope.user_id, reviewer=_reviewer(scope)
        )
    except PermissionError as exc:
        raise _refuse(403, str(exc)) from exc
    except ValueError as exc:
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/generate-draft", response_model=QueryOut)
def generate_query_draft(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    body: GenerateDraftIn | None = None,
):
    """Generate a grounded draft through the existing citation-checked answer lane. The engine is the local model unless the request asks
    for Claude, which is refused ("not approved by the owner") unless its own switch is on; the owner has not approved that lane, and the
    chat's per-request consent is chat's lane only, never used here."""
    _require_identity_to_write(scope)
    engine = body.engine if body else "local"
    if engine == "claude" and not settings.technical_query_claude_draft_enabled:
        raise _refuse(409, technical_queries.CLAUDE_DRAFT_OFF_WORDS)
    current = technical_queries.get(query_id, *_visible(scope))
    if current is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    with connect() as conn:
        attachment_documents = technical_queries.query_attachment_document_ids(conn)
    usable_evidence = [
        item
        for item in current.get("evidence", [])
        if item["document_id"] not in attachment_documents
        and item["evidence_state"] == "verified"
        and item["supersession_state"] == "current"
        and item["document_id"] in scope.allowed_document_ids
    ]
    if not usable_evidence:
        raise _refuse(409, "verified, current evidence is required before drafting")
    question = (current.get("confirmed_question") or "").strip()
    if not question:
        raise _refuse(
            409, "an engineer must confirm the question before a draft is generated"
        )
    try:
        result = answer.answer(
            question,
            tier="generated",
            allowed_document_ids=frozenset(
                item["document_id"] for item in usable_evidence
            ),
            model="local" if engine == "local" else None,  # None: the app's own engine, behind the approved list of documents
        )
    except (
        Exception
    ) as exc:  # model availability is an operational failure, not a 500 leak
        raise _refuse(
            503,
            "the configured local drafting model is unavailable",
            errors.MODEL_UNAVAILABLE,
        ) from exc
    if result.get("answer_type") != "generated" or not result.get("answer"):
        reason = (result.get("reason") or "").strip()
        raise _refuse(
            409,
            "the evidence was insufficient for a grounded draft"
            + (f": {reason}" if reason else ""),
        )
    passages = result.get("passages") or []
    cited = result.get("cited") or []
    citations = []
    for index in cited:
        if not isinstance(index, int) or index < 1 or index > len(passages):
            break
        passage = passages[index - 1]
        match = next(
            (
                evidence
                for evidence in usable_evidence
                if evidence["document_id"] == passage.get("document_id")
                and evidence["page_start"] is not None
                and passage.get("page_start") is not None
                and evidence["page_start"] <= passage.get("page_end", 0)
                and evidence["page_end"] >= passage["page_start"]
                and evidence["exact_quote"] in (passage.get("text") or "")
            ),
            None,
        )
        if match is None:
            break
        citations.append(
            {
                "label": f"S{index}",
                "evidence_id": match["id"],
                "document_id": match["document_id"],
                "page": match["page_start"],
                "exact_quote": match["exact_quote"],
            }
        )
    if not cited or len(citations) != len(cited):
        raise _refuse(
            409,
            "the generated answer cited passages outside the query's verified evidence",
        )
    item = technical_queries.add_draft(
        query_id,
        result["answer"],
        [],
        [result.get("reason")] if result.get("reason") else [],
        scope.user_id,
        *_visible(scope),
        citations=citations,
        model=result.get("model"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/evidence", response_model=QueryOut)
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


@router.post("/api/technical-queries/{query_id}/prepare-evidence", response_model=QueryOut)
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
        raise _refuse(422, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.patch("/api/technical-queries/{query_id}/evidence/{evidence_id}", response_model=QueryOut)
def classify_query_evidence(
    query_id: str,
    evidence_id: str,
    body: EvidenceClassificationIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.update_evidence(
            query_id,
            evidence_id,
            body.evidence_state,
            body.supersession_state,
            body.conflict_group,
            scope.user_id,
            *_visible(scope),
            reviewer=_reviewer(scope),
        )
    except PermissionError as exc:
        raise _refuse(403, str(exc)) from exc
    except ValueError as exc:
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="query or evidence not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/attachments/{attachment_id}/file", response_model=AttachmentOut)
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
    current = technical_queries.get(query_id, *_visible(scope))
    if current and current["status"] in {
        "send_pending",
        "sent",
        "awaiting_confirmation",
        "resolved",
    }:
        raise HTTPException(status_code=409, detail="sent query attachments are locked")
    return _ingest_query_attachment(query_id, attachment, file, scope)


def _ingest_query_attachment(query_id: str, attachment: dict, file: UploadFile, scope: access.AccessScope) -> dict:
    """Check one uploaded file against its attachment row (name, size, digest) and ingest it through the guarded document pipeline; the
    link then runs the static safety check (`attachment_safety`). Shared by the attachment route and the by-hand route."""
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
    admin_role = None
    if not scope.unrestricted and scope.user_id:
        try:
            admin_role, _ = access.upload_admin_role(scope.user_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if (
        duplicate_of is not None
        and not scope.may_read(row["id"])
        and not scope.unrestricted
    ):
        raise HTTPException(
            status_code=403, detail="the existing document is not readable"
        )
    if duplicate_of is None and admin_role is not None and scope.user_id:
        access.grant_uploaded_document_to_admin(row["id"], admin_role, scope.user_id)
    item = technical_queries.link_attachment(
        query_id, attachment["id"], row["id"], scope.user_id, *_visible(scope)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="query attachment not found")
    return {
        "item": _safe_item(item, scope),
        "document_id": row["id"],
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
    }


@router.post("/api/technical-queries/{query_id}/decisions", response_model=QueryOut)
def decide_query(
    query_id: str,
    body: DecisionIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not _reviewer(scope):
        raise _refuse(403, "a qualified technical-query reviewer is required")
    try:
        item = technical_queries.decide(
            query_id,
            body.decision,
            scope.user_id,
            body.comment,
            body.draft_id,
            *_visible(scope),
            reviewer=_reviewer(scope),
        )
    except (PermissionError, ValueError) as exc:
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


@router.get("/api/technical-queries/{query_id}/response.docx", response_class=FileResponse, responses={200: {"content": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document": {"schema": {"type": "string", "format": "binary"}}}}})
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


@router.post("/api/technical-queries/{query_id}/send", response_model=SendOut)
def prepare_query_send(
    query_id: str,
    body: SendIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Send only after an authorised user explicitly requests this approved draft."""
    _require_identity_to_write(scope)
    if not technical_queries.SENDING_APPROVED:
        raise _refuse(409, technical_queries.SEND_OFF_WORDS)
    if not _reviewer(scope) or not scope.user_id:
        raise _refuse(403, "a qualified technical-query reviewer is required to send")
    item = technical_queries.get(query_id, *_visible(scope))
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT email FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state='active' AND label_id IS NOT NULL",
            (body.mailbox_id, scope.user_id),
        ).fetchone()
    if mailbox is None:
        raise HTTPException(
            status_code=409,
            detail="a connected mailbox owned by the sender is required",
        )
    try:
        provider_id = gmail_worker.send_approved(
            GmailApiClient(gmail_auth.access_token(body.mailbox_id)),
            query_id,
            body.draft_id,
            scope,
            body.idempotency_key,
            mailbox["email"],
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=503,
            detail="email provider is unavailable or send outcome needs reconciliation",
        ) from exc
    refreshed = technical_queries.get(query_id, *_visible(scope))
    return {
        "item": _safe_item(refreshed, scope),
        "sent": True,
        "provider_message_id": provider_id,
    }


@router.post("/api/technical-queries/{query_id}/sends/{send_id}/reconcile", response_model=QueryOut)
def reconcile_query_send(
    query_id: str,
    send_id: str,
    body: ReconcileSendIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    try:
        item = technical_queries.reconcile_send(
            query_id,
            send_id,
            body.outcome,
            body.provider_message_id,
            body.comment,
            scope.user_id,
            scope.is_admin,
            scope.unrestricted,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query send not found")
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/confirm-resolution", response_model=QueryOut)
def confirm_query_resolution(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    if not _reviewer(scope):
        raise _refuse(403, "a qualified technical-query reviewer is required")
    try:
        item = technical_queries.decide(
            query_id,
            "close",
            scope.user_id,
            "contractor or authorised internal confirmation",
            None,
            *_visible(scope),
            reviewer=_reviewer(scope),
        )
    except ValueError as exc:
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)
