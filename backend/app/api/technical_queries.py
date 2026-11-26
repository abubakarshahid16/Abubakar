from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import (
    access,
    attachment_safety,
    chat_model,
    claude_approved,
    errors,
    gmail_auth,
    gmail_sync,
    gmail_import_jobs,
    technical_queries,
    technical_query_auto,
    technical_query_claude,
    technical_query_contracts,
    technical_query_docx,
    technical_query_jobs,
    verified_passages,
)
from .. import upload as upload_mod
from ..api_utils import _require_identity_to_write, reject_unknown_params
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
    open_with_due_date: int = 0
    overdue: int = 0


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
    import_job: str | None = None


class CheckNowOut(BaseModel):
    import_job: str


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
    """Which engine writes the draft answer. Local by default. `claude` (owner approved, #1584 comment 7170031292) sends only the
    contract documents named in `document_ids` (the engineer's choice for this one query) and the query's own text; any other engine
    is refused as not approved by the owner."""

    engine: str = Field(default="local", max_length=40)
    document_ids: list[str] = Field(default_factory=list, max_length=100)


class ManualOut(_Open):
    item: QueryOut
    uploaded: int = 0


class DraftIn(BaseModel):
    answer: str = Field(min_length=1, max_length=100_000)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=100)


class RoutingRuleIn(BaseModel):
    match_type: Literal["address", "domain", "contractor_code", "discipline"]
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


LIST_COLUMNS = (
    "id", "subject", "status", "priority", "contractor_name", "department", "assignee_user_id",
    "received_at", "due_at", "routing_source", "confirmed_question_at",
    "ref_type", "ref_number", "discipline_code", "title_short", "needs_person",
)  # fmt: skip


def _attachment_documents(item: dict) -> set[str]:
    return {
        a["document_id"]
        for m in item.get("messages", [])
        for a in m.get("attachments", [])
        if a.get("document_id")
    }


def _hide_unreadable_attachment_text(item: dict, scope: access.AccessScope) -> dict:
    """Text copied out of an attachment is shown only to a person who may read that attachment's document (rule 5: a copy never widens
    access). When a person may not, the copy, the questions found in it and the wording built from it are left out, and it says so."""
    if _attachment_documents(item) <= set(scope.readable_with_attachments):
        return item
    return {
        **item,
        "attachment_context": [],
        "proposed_questions": [],
        "proposed_question": None,
        "attachment_text_hidden": True,
    }


#: Why Claude cannot write a query's reply now, in plain words, by the lane's own reason code (never the key, only whether one is set).
_CLAUDE_WHY = {
    "PROVIDER_OFF": "Claude is switched off on this computer",
    "TASK_ENGINE_LOCAL": "Claude is switched off for query replies on this computer",
    "EGRESS_OFF": "sending to Claude is switched off on this computer",
    "KEY_MISSING": "no Claude key is set on this computer",
}


def _draft_engines() -> dict:
    """Which engine may write a draft now (owner, 27 Nov 2026 00:02: "Claude shown unavailable + why"): the same two checks the draft
    route makes before any request (the draft-engine setting, then the lane), read only. The account's own credit is not known here:
    a press that the account refuses still shows the server's refusal."""
    from .. import reasoning_provider

    if settings.technical_query_draft_engine.strip().lower() != "claude":
        return {"claude": {"available": False, "why": _CLAUDE_WHY["TASK_ENGINE_LOCAL"]}}
    code, words = reasoning_provider.claude_unavailable_for_task(settings.technical_query_draft_engine)
    if code is None:
        return {"claude": {"available": True, "why": None}}
    return {"claude": {"available": False, "why": _CLAUDE_WHY.get(code, words)}}


def _subject_codes(item: dict) -> dict:
    """The contractor code the subject's number holds (`technical_query_subject`, the same reading the routing rules use), so an empty
    Contractor field can say what the subject holds; nothing when the subject carries no TQ/CFC number."""
    from .. import technical_query_subject

    ref = technical_query_subject.parse(item.get("subject")) or {}
    return {"contractor_code": ref.get("contractor_code") or None}


def _safe_item(item: dict, scope: access.AccessScope) -> dict:
    """Hide source material retained after a document grant is revoked."""
    item = {
        **item,
        **_subject_codes(item),
        "draft_engines": _draft_engines(),
        "can_review": _reviewer(scope),
        "messages": [
            {key: value for key, value in message.items() if key != "raw_storage_ref"}
            for message in item.get("messages", [])
        ],
    }
    if scope.unrestricted:
        return item
    item = _hide_unreadable_attachment_text(item, scope)
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
    ref_type: str | None = None,
    discipline: str | None = None,
    number: str | None = None,
    needs_person: bool | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    rows = technical_queries.list_queries(
        *_visible(scope),
        status,
        contractor=contractor,
        department=department,
        assignee_user_id=assignee_user_id,
        received_from=received_from,
        received_to=received_to,
        evidence_state=evidence_state,
        ref_type=ref_type,
        discipline=discipline,
        number=number,
        needs_person=needs_person,
    )
    # The queue shows a fixed set of columns: stored attachment text and the questions found in it are in the detail, behind the grant check.
    return {"items": [{key: row.get(key) for key in LIST_COLUMNS if key in row} for row in rows]}


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
        raise _refuse(424, str(exc)) from exc


@router.get("/api/technical-queries/providers/gmail/mailboxes", response_model=RowsOut)
def gmail_mailboxes(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(
            status_code=403, detail="only an administrator can view connected mailboxes"
        )
    with connect() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(gmail_mailboxes)")}
        checked = "last_checked_at" if "last_checked_at" in columns else "NULL AS last_checked_at"
        checked += ",status_note" if "status_note" in columns else ",NULL AS status_note"
        rows = conn.execute(
            f"SELECT id,email,label_id,connection_state,{checked} FROM gmail_mailboxes WHERE owner_user_id=? ORDER BY email",
            (scope.user_id,),
        ).fetchall()
        items = [{**dict(row), "import_job": gmail_import_jobs.latest(conn, row["id"])} for row in rows]
    return {"items": items}


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
        raise _refuse(
            424, "Gmail could not be reached, so the labels could not be listed. Try again in a moment."
        ) from exc


@router.post("/api/technical-queries/providers/gmail/mailboxes/{mailbox_id}/activate", response_model=ActivateOut)
def activate_gmail_mailbox(
    mailbox_id: str,
    body: GmailLabelIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Save the label and set the mailbox ACTIVE first, in this one short request; the existing mail is imported by a background job (one message at a
    time, progress on the screen). A failure here says one plain sentence and changes nothing."""
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT 1 FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state='needs_label'",
            (mailbox_id, scope.user_id),
        ).fetchone()
    if mailbox is None:
        raise HTTPException(status_code=404, detail="mailbox is not awaiting label selection")
    try:
        labels = {label.get("id") for label in GmailApiClient(gmail_auth.access_token(mailbox_id)).labels()}
    except Exception as exc:
        raise _refuse(424, "Gmail could not be reached, so nothing was changed. Try again in a moment.") from exc
    if body.label_id not in labels:
        raise _refuse(422, "That is not one of your own Gmail labels. Choose a label you created.")
    with connect() as conn:
        changed = conn.execute(
            "UPDATE gmail_mailboxes SET label_id=?,connection_state='active',updated_at=? WHERE id=? AND connection_state='needs_label'",
            (body.label_id, technical_queries.now(), mailbox_id),
        )
    if changed.rowcount != 1:
        raise _refuse(409, "The mailbox changed while you were choosing. Reload the page and try again.")
    job_id = gmail_import_jobs.enqueue(mailbox_id, "import", body.label_id)
    gmail_sync.start()
    return {"imported": 0, "connection_state": "active", "import_job": job_id}


@router.post("/api/technical-queries/providers/gmail/mailboxes/{mailbox_id}/check-now", response_model=CheckNowOut)
def check_gmail_mailbox_now(mailbox_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    """"Check now": a waiting job runs at once; if the last import ended failed it is queued again; else ONE poll is queued (the failed messages of the last import are tried once more, then the new mail). Answers at once."""
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT 1 FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state IN ('active','error')", (mailbox_id, scope.user_id)
        ).fetchone()
    if mailbox is None:
        raise HTTPException(status_code=404, detail="mailbox is not active")
    return {"import_job": gmail_import_jobs.check_now(mailbox_id)}


@router.post(
    "/api/technical-queries/providers/gmail/mailboxes/{mailbox_id}/import-again",
    response_model=CheckNowOut,
)
def import_gmail_label_again(
    mailbox_id: str, scope: access.AccessScope = Depends(access.current_scope)
):
    """ "Import the label again" (lead-4, 26 Nov 2026): reads every message of the label again and stores only what is missing (a message held
    is counted "already stored", never a second query; our replies join their query; an attachment not yet taken in is taken in now)."""
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise HTTPException(status_code=403, detail="an administrator is required")
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT label_id FROM gmail_mailboxes WHERE id=? AND owner_user_id=? AND connection_state='active'",
            (mailbox_id, scope.user_id),
        ).fetchone()
    if mailbox is None or not mailbox["label_id"]:
        raise HTTPException(status_code=404, detail="mailbox is not active")
    return {
        "import_job": gmail_import_jobs.enqueue(
            mailbox_id, "import", mailbox["label_id"], run_now=True
        )
    }


class OauthCompleteIn(BaseModel):
    code: str | None = Field(default=None, max_length=2000)
    state: str | None = Field(default=None, max_length=500)
    error: str | None = Field(default=None, max_length=200)


class OauthCompleteOut(BaseModel):
    result: Literal["connected", "admin_must_allow"]
    mailbox_id: str | None = None


@router.post("/api/technical-queries/providers/gmail/oauth/complete", response_model=OauthCompleteOut)
def gmail_oauth_complete(body: OauthCompleteIn, scope: access.AccessScope = Depends(access.current_scope)):
    """The end of the Google connection. Google sends the person to a page of THIS APP (the registered return address is the app's own
    screen, not this server), and that page posts the code and state here as an ordinary same-site request: so the sign-in cookie
    (SameSite=Strict) is sent, the person must be the administrator who started the connection (the state names them), and the one-time
    code never sits in a server log or in the address bar after the page has cleared it."""
    _require_identity_to_write(scope)
    if body.error in gmail_auth.ADMIN_BLOCKS:  # the company's Google admin has not allowed the app: the screen says so in one line
        return {"result": "admin_must_allow"}
    if not body.code or not body.state:
        raise HTTPException(status_code=400, detail="Gmail OAuth callback requires code and state")
    if not scope.is_admin or not scope.user_id or gmail_auth.validate_state(body.state) != scope.user_id:
        raise _refuse(403, "this connection was started by another person; start it again from your own sign-in")
    try:
        mailbox = gmail_auth.complete(body.code, body.state)
        gmail_sync.start()
    except gmail_auth.CompanyAdminMustAllow:
        return {"result": "admin_must_allow"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _refuse(424, "Gmail connection could not be completed. Try again.") from exc
    return {"result": "connected", "mailbox_id": str((mailbox or {}).get("id") or "") or None}


@router.post("/api/technical-queries/providers/microsoft-graph/webhook", response_model=WebhookAckOut)
def graph_webhook(_payload: dict):
    # No subscription secret or signature validation has been configured.
    # A public endpoint must not claim to have accepted unverified events.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


@router.post("/api/technical-queries/providers/gmail/webhook", response_model=WebhookAckOut)
def gmail_webhook(_payload: dict):
    # Pub/Sub push authentication and durable queueing are prerequisites.
    raise HTTPException(status_code=503, detail="mailbox webhook is not configured")


class PrepareAllOut(BaseModel):
    unprepared: int
    minutes_each: int | None = None
    waiting_or_running: int
    queued_now: int | None = None


@router.get("/api/technical-queries/prepare-all", response_model=PrepareAllOut)
def prepare_all_plan(scope: access.AccessScope = Depends(access.current_scope)):
    """What "Prepare evidence for all unprepared queries" would do (counts only), and how far a started round has got."""
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    with connect() as conn:
        return technical_query_jobs.all_plan(conn)


@router.post("/api/technical-queries/prepare-all", response_model=PrepareAllOut)
def prepare_all_start(scope: access.AccessScope = Depends(access.current_scope)):
    """Queue every query not prepared yet; the one evidence thread prepares them one at a time in the background (prepared ones are skipped)."""
    _require_identity_to_write(scope)
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    return technical_query_jobs.queue_all(
        scope.readable_with_attachments,
        scope.user_id,
        scope.is_admin,
        scope.unrestricted,
    )


class StatusCountsOut(BaseModel):
    mailboxes: list[dict[str, Any]]
    boundary: str


@router.get("/api/technical-queries/status-counts", response_model=StatusCountsOut)
def technical_query_status_counts(
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Technical queries by COUNTS ONLY, per mailbox id (no subject, name, address, file name or body text): the planner's view."""
    if not scope.is_admin or not scope.user_id:
        raise _refuse(403, "an administrator is required")
    from .. import technical_query_status

    with connect() as conn:
        return technical_query_status.counts(conn)


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
    if not scope.unrestricted and not {
        a["document_id"] for a in message.get("attachments", []) if a.get("document_id")
    } <= set(scope.readable_with_attachments):
        # the stored message holds its attachments' bytes: a person who may not read one of them does not get the whole message
        raise _refuse(403, "the original email carries an attachment you may not read")
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
    if (item.get("evidence_question") or "") != (item.get("confirmed_question") or ""):  # confirmed another wording: refresh from it
        technical_query_auto.refresh(query_id, scope.readable_with_attachments, scope.user_id, scope.is_admin, scope.unrestricted)
        item = technical_queries.get(query_id, *_visible(scope)) or item
    return _safe_item(item, scope)


@router.post("/api/technical-queries/{query_id}/question", response_model=QueryOut)
def edit_query_question(
    query_id: str,
    body: QuestionIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """An engineer saves their own wording of the question WITHOUT confirming it; the evidence and the local draft refresh from it at once
    (owner, 26 Nov 2026 21:36: the proposed question stays editable, and evidence and draft follow it). Confirming stays a separate step."""
    _require_identity_to_write(scope)
    try:
        item = technical_query_auto.edit(query_id, body.question, scope.readable_with_attachments, scope.user_id, scope.is_admin,
                                         scope.unrestricted, scope.user_id)  # fmt: skip
    except ValueError as exc:
        raise _refuse(409, str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    return _safe_item(item, scope)


def _no_usable_evidence(current: dict, attachment_documents, scope) -> str:
    """Why no draft can be made yet, and what the engineer does about it (F's live check, 26 Nov 2026: the page never said that a kept
    passage counts as current only once its source document is confirmed)."""
    kept = [e for e in current.get("evidence", []) if e["evidence_state"] == "verified" and e["document_id"] not in attachment_documents
            and e["document_id"] in scope.allowed_document_ids]  # fmt: skip
    head = "verified, current evidence is required before drafting"
    if not kept:
        return f"{head}: keep at least one passage as evidence first"
    ids = sorted(
        {e["document_id"] for e in kept if e["supersession_state"] != "superseded"}
    )
    with connect() as conn:
        named = {r["id"]: r["filename"] for r in conn.execute(
            f"SELECT id, filename FROM documents WHERE id IN ({','.join('?' for _ in ids)})", tuple(ids)).fetchall()} if ids else {}  # fmt: skip
    names = [named.get(d) or d for d in ids]
    if not names:
        return f"{head}: every kept passage's source has been superseded"
    return f"{head}: a kept passage counts as current once its source document is confirmed (Documents, Details, Save metadata): {', '.join(names)}"


@router.post("/api/technical-queries/{query_id}/generate-draft", response_model=QueryOut)
def generate_query_draft(
    query_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    body: GenerateDraftIn | None = None,
):
    """Generate a grounded draft through the existing citation-checked answer lane. The engine is the local model unless the request asks
    for Claude: then only the documents the engineer chose (a consent record of this lane, stored first) and the query's own text are
    sent, through the ordinary Claude path under the spend caps, and only when the server's draft-engine setting says claude. Any other
    vendor is refused. Chat's per-request consent is chat's lane only and is never used here."""
    _require_identity_to_write(scope)
    engine = (body.engine if body else "local").strip().lower()
    if engine not in {"local", "claude"}:
        raise _refuse(409, f"The engine {engine!r} is not approved by the owner: only the local model and Claude can write a draft.")
    if engine == "claude" and settings.technical_query_draft_engine.strip().lower() != "claude":
        raise _refuse(409, technical_queries.CLAUDE_DRAFT_OFF_WORDS)
    current = technical_queries.get(query_id, *_visible(scope))
    if current is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    technical_query_auto.reopen(current)  # a new draft replaces a model-written one that is awaiting review
    with connect() as conn:
        attachment_documents = technical_queries.query_attachment_document_ids(conn)
    # the wording the system works from: confirmed, else the engineer's own, else the proposal (confirming is never needed first)
    question, _source = technical_query_auto.working(current)
    if not question:
        raise _refuse(409, technical_query_auto.NO_QUESTION)
    if engine == "claude":  # the Claude lane is unchanged: only kept, current passages, and only the contracts the engineer chooses
        usable_evidence = [
            item
            for item in current.get("evidence", [])
            if item["document_id"] not in attachment_documents
            and item["evidence_state"] == "verified"
            and item["supersession_state"] == "current"
            and item["document_id"] in scope.allowed_document_ids
        ]
    else:  # the local model: the kept passages, else the best the system found for this wording (each draft says which)
        usable_evidence = technical_query_auto.draft_passages(current, scope.allowed_document_ids, attachment_documents)
    if not usable_evidence:
        raise _refuse(409, _no_usable_evidence(current, attachment_documents, scope) if engine == "claude"
                      else technical_query_auto.NO_PASSAGE)  # fmt: skip
    scope_ids = frozenset(item["document_id"] for item in usable_evidence)
    chosen: frozenset[str] = frozenset()
    if engine == "claude":
        chosen = frozenset(body.document_ids if body else ())
        if not chosen:
            raise _refuse(409, "choose the contract documents Claude may read for this query before asking for a Claude draft")
        if not chosen <= scope_ids:
            raise _refuse(409, "a chosen document is not verified, current evidence of this query that you may read")
        not_contracts = chosen - frozenset(technical_query_contracts.contract_ids(chosen))
        if not_contracts:  # the owner approved CONTRACT documents only for this lane
            raise _refuse(409, f"not a contract: not sent ({', '.join(sorted(not_contracts))})")
        with connect() as conn:  # the choice is recorded BEFORE anything can be sent: ids only
            technical_query_claude.record(conn, query_id, chosen, scope.user_id)
    try:
        with claude_approved.technical_query_lane(chosen):
            result = verified_passages.answer(
                question,
                evidence=usable_evidence,
                tier="generated",
                allowed_document_ids=chosen if engine == "claude" else scope_ids,
                model="local" if engine == "local" else chat_model.TQ_DRAFT,
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
    citations = technical_query_auto.citations_of(result, usable_evidence)
    if citations is None:
        raise _refuse(
            409,
            "the generated answer cited passages outside the query's verified evidence",
        )
    unresolved = [result.get("reason")] if result.get("reason") else []
    unresolved += technical_query_auto.marks(current, {c["evidence_id"] for c in citations})
    if engine == "claude" and not str(result.get("model") or "").lower().startswith("claude"):
        unresolved.append("Claude did not write this draft (the lane was closed or refused); the local model did.")
    item = technical_queries.add_draft(
        query_id,
        result["answer"],
        [],
        unresolved,
        scope.user_id,
        *_visible(scope),
        citations=citations,
        model=result.get("model"),
        question=question,
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
    """Queue the preparation as a job and answer at once: it takes minutes (the local model reads the attachment pages and every contract
    is searched). The query carries `evidence_job` with its progress; the screen polls it."""
    _require_identity_to_write(scope)
    current = technical_queries.get(query_id, *_visible(scope))
    if current is None:
        raise HTTPException(status_code=404, detail="technical query not found")
    if not technical_query_auto.refresh(query_id, scope.readable_with_attachments, scope.user_id, scope.is_admin, scope.unrestricted):
        raise _refuse(422, "evidence cannot be prepared in the current query state")
    return _safe_item(technical_queries.get(query_id, *_visible(scope)) or current, scope)


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
    checked = attachment_safety.check_before_library(file.file)
    if checked["status"] != attachment_safety.CLEAN:
        # the file is NOT ingested: it never becomes a library document; the attachment row says why
        with connect() as conn:
            conn.execute(
                "UPDATE query_attachments SET scan_status=?,scan_detail=? WHERE id=?",
                (checked["status"], ", ".join(checked["findings"]) or None, attachment["id"]),
            )
        raise _refuse(
            422,
            "the attachment was not accepted: the static check "
            + ("found active content in it" if checked["status"] == attachment_safety.FLAGGED else "could not check it"),
        )
    with connect() as conn:
        flagged_before = technical_queries.unfiled_attachment_ids(conn)
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if (
        duplicate_of is not None
        and not scope.may_read_attachment(row["id"])
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
    if duplicate_of is not None and row["id"] not in flagged_before:
        with connect() as conn:  # a paper the library already held is not hidden by being attached to a query
            technical_queries.mark_filed(conn, row["id"], scope.user_id)
    return {
        "item": _safe_item(item, scope),
        "document_id": row["id"],
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
    }


@router.get(
    "/api/technical-queries/{query_id}/attachments/{attachment_id}/original",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The original bytes of the query's attachment"}},
)
def query_attachment_original(
    query_id: str,
    attachment_id: str,
    request: Request,
    download: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Open a query's attachment. An attachment nobody has filed into the library is out of the general document routes (they answer 404);
    the person who may see the query and may read the attachment opens it here, so the engineer can read the paper BEFORE deciding to file it."""
    from . import document_files

    reject_unknown_params(request, {"download"})
    attachment = technical_queries.attachment_for_query(query_id, attachment_id, *_visible(scope))
    if attachment is None or not attachment["document_id"]:
        raise HTTPException(status_code=404, detail="query attachment not found")
    if not scope.may_read_attachment(attachment["document_id"]):
        raise HTTPException(status_code=404, detail="query attachment not found")  # as if it were not there: no hint it exists
    with connect() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (attachment["document_id"],)).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="query attachment not found")
    return document_files.original_response(doc, attachment["document_id"], download)


class FileIntoLibraryIn(BaseModel):
    role: Literal["CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT", "SPECIFICATION", "SUPPORTING_DOCUMENT"]


@router.post("/api/technical-queries/{query_id}/attachments/{attachment_id}/file-into-library", response_model=QueryOut)
def file_attachment_into_library(
    query_id: str,
    attachment_id: str,
    body: FileIntoLibraryIn,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """An engineer files a query's attachment into the library ON PURPOSE, with a role. Until then the attachment is kept out of library
    search, Chat, the review picker and every automatic Claude-approval route; the query's own screens keep working. Then it is an ordinary
    library document: its role decides what the approval routes do with it, as for any upload."""
    _require_identity_to_write(scope)
    if not (_reviewer(scope) or scope.is_admin):
        raise _refuse(403, "a qualified technical-query reviewer or an administrator is required to file an attachment into the library")
    attachment = technical_queries.attachment_for_query(query_id, attachment_id, *_visible(scope))
    if attachment is None or not attachment["document_id"]:
        raise HTTPException(status_code=404, detail="query attachment not found")
    if not scope.may_read_attachment(attachment["document_id"]):
        raise _refuse(403, "you may not read this attachment")
    if not technical_queries.file_into_library(attachment["document_id"], body.role, scope.user_id):
        raise _refuse(409, "this attachment is already in the library")
    item = technical_queries.get(query_id, *_visible(scope))
    return _safe_item(item, scope)


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
    if not scope.unrestricted and _hide_unreadable_attachment_text(item, scope) is not item:
        raise HTTPException(
            status_code=403,
            detail="the response quotes an attachment you may not read",
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
    """Sending is NOT approved by the owner, and no code sends: this route only says so. Nothing is read, stored or sent."""
    _require_identity_to_write(scope)
    raise _refuse(409, technical_queries.SEND_OFF_WORDS)


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
