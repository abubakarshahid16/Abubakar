"""Deliverables and the management view: the deliverables register, expected
deliverables, history, stakeholders, the workspace and alerts; management
reminders, the summary and its schedule, escalation rules and the report.

Moved out of main.py with no logic change (planner order 79a, #692; system map target structure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import access, errors, schemas
from .. import admin as admin_mod
from .. import deliverables as deliverables_mod
from .. import notifications as notifications_mod
from .. import review as review_mod
from ..api_utils import (
    _deliverable_visible,
    _require_identity_to_write,
    require_document,
)
from ..config import settings
from ..paging import limit_param, offset_param, page_body

router = APIRouter()


@router.get("/api/deliverables", response_model=schemas.DeliverableList,
            responses=schemas.ERRORS_422)
def list_deliverables(
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    return page_body(
        "deliverables",
        deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids),
        limit,
        offset,
    )


@router.get("/api/deliverables/expected", response_model=schemas.ExpectedDeliverableList)
def expected_deliverables(
    wbs_code: str | None = None,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    deliverables_mod.infer_expectations(allowed_document_ids=scope.allowed_document_ids)
    return page_body(
        "deliverables",
        deliverables_mod.expected_missing(
            wbs_code=wbs_code, allowed_document_ids=scope.allowed_document_ids
        ),
        limit,
        offset,
    )


@router.post("/api/deliverables", response_model=schemas.Deliverable,
             responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def create_deliverable(body: schemas.DeliverableCreate,
                       scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    if body.document_id:
        require_document(body.document_id, scope)
    if body.parent_id and deliverables_mod.get(body.parent_id) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "parent WBS node not found"))
    return deliverables_mod.create(body.model_dump(), created_by=scope.user_id)


@router.patch("/api/deliverables/{deliverable_id}", response_model=schemas.Deliverable,
              responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def update_deliverable(deliverable_id: str, body: schemas.DeliverableUpdate,
                       scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    # AUTHORISE BEFORE WRITING. The read check used to run on the row
    # `update` RETURNED, so a caller without a grant on the deliverable's
    # document got a 404 while their change had already been committed
    # (audit 2026-09-30). The existing row is checked first, then written.
    existing = deliverables_mod.get(deliverable_id)
    if existing is None or not _deliverable_visible(existing, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    changes = body.model_dump(exclude_unset=True)
    if changes.get("document_id"):
        require_document(changes["document_id"], scope)
    if changes.get("parent_id") and deliverables_mod.get(changes["parent_id"]) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "parent WBS node not found"))
    try:
        item = deliverables_mod.update(deliverable_id, changes, actor_user_id=scope.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return item


@router.get("/api/deliverables/{deliverable_id}/history", response_model=schemas.DeliverableEventList,
            responses=schemas.ERRORS_404)
def deliverable_history(
    deliverable_id: str,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return page_body("events", deliverables_mod.history(deliverable_id), limit, offset)


@router.get("/api/deliverables/{deliverable_id}/stakeholders",
            response_model=schemas.DeliverableStakeholderList,
            responses=schemas.ERRORS_404)
def deliverable_stakeholders(
    deliverable_id: str,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return page_body(
        "stakeholders", deliverables_mod.stakeholders(deliverable_id), limit, offset
    )


@router.put("/api/deliverables/{deliverable_id}/stakeholders",
            response_model=schemas.DeliverableStakeholderList,
            responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def replace_deliverable_stakeholders(
    deliverable_id: str, body: schemas.DeliverableStakeholderUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    # The same body as the list: every assignment now held, with its total.
    stakeholders = deliverables_mod.replace_stakeholders(
        deliverable_id, [a.model_dump() for a in body.assignments], actor_user_id=scope.user_id)
    return page_body("stakeholders", stakeholders, None, 0)


@router.get("/api/deliverables/{deliverable_id}/workspace",
            response_model=schemas.WbsWorkspace, responses=schemas.ERRORS_404)
def deliverable_workspace(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.workspace(
        deliverable_id, allowed_document_ids=scope.allowed_document_ids)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return item


@router.get("/api/deliverables/alerts", response_model=schemas.DeliverableAlertList)
def deliverable_alerts(
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    return page_body(
        "alerts",
        deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids),
        limit,
        offset,
    )


@router.get("/api/management/reminders", response_model=schemas.ReminderEventList)
def management_reminders(
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    return page_body(
        "reminders",
        deliverables_mod.reminder_events(
            allowed_document_ids=scope.allowed_document_ids
        ),
        limit,
        offset,
    )


@router.post("/api/management/reminders/{reminder_id}/ack", response_model=schemas.ReminderEvent,
             responses=schemas.ERRORS_404)
def acknowledge_management_reminder(reminder_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    reminder = next((item for item in deliverables_mod.reminder_events(allowed_document_ids=scope.allowed_document_ids)
                     if item["id"] == reminder_id), None)
    if reminder is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no reminder with that id"))
    item = deliverables_mod.acknowledge_reminder(reminder_id)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no reminder with that id"))
    return item


@router.get("/api/management/summary", response_model=schemas.ManagementSummary)
def management_summary(scope: access.AccessScope = Depends(access.current_scope)):
    items = deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids)
    alerts = deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids)
    findings = review_mod.list_findings(allowed_document_ids=scope.allowed_document_ids)
    by_status = {status: sum(1 for item in items if item["status"] == status)
                 for status in {item["status"] for item in items}}
    by_severity = {severity: sum(1 for item in findings if item["severity"] == severity)
                   for severity in {item["severity"] for item in findings}}
    by_review_status = {status: sum(1 for item in findings if item["status"] == status)
                        for status in {item["status"] for item in findings}}
    escalated = sum(1 for item in findings if item["escalation_level"] > 0)
    return {"deliverables_total": len(items), "deliverables_by_status": by_status,
            "review_findings_total": len(findings), "findings_by_severity": by_severity,
            "findings_by_status": by_review_status, "escalated_findings": escalated,
            "overdue_alerts": len(alerts), "alerts": alerts}


@router.post("/api/management/summary/email", response_model=schemas.NotificationSendResponse,
             responses=schemas.ERRORS_401)
def email_management_summary(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    items = deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids)
    alerts = deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids)
    findings = review_mod.list_findings(allowed_document_ids=scope.allowed_document_ids)
    summary = {"deliverables_total": len(items), "overdue_alerts": len(alerts),
               "escalated_findings": sum(1 for item in findings if item["escalation_level"] > 0)}
    sent = notifications_mod.send_daily_summary(summary, actor_user_id=scope.user_id)
    return {"sent": sent}


@router.get("/api/management/summary/schedule", response_model=schemas.SummarySchedule)
def get_summary_schedule(scope: access.AccessScope = Depends(access.current_scope)):
    return {"schedule": settings.summary_schedule, "weekday_utc": settings.summary_weekday_utc, "hour_utc": settings.summary_hour_utc}


@router.put("/api/management/summary/schedule", response_model=schemas.SummarySchedule)
def set_summary_schedule(body: schemas.SummarySchedule,
                         scope: access.AccessScope = Depends(access.current_scope),
                         _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    settings.summary_schedule = body.schedule
    settings.summary_weekday_utc = body.weekday_utc
    settings.summary_hour_utc = body.hour_utc
    return body


@router.get("/api/management/escalation-rules", response_model=schemas.EscalationRuleList)
def list_escalation_rules(
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    scope: access.AccessScope = Depends(access.current_scope),
):
    return page_body("rules", deliverables_mod.escalation_rules(), limit, offset)


@router.get("/api/management/report", response_class=FileResponse,
            responses={200: {"content": {"application/pdf": {}}, "description": "Management PDF"}})
def management_report(scope: access.AccessScope = Depends(access.current_scope)):
    path = deliverables_mod.render_management_report(allowed_document_ids=scope.allowed_document_ids)
    return FileResponse(path, media_type="application/pdf", filename="epc-management-report.pdf",
                        headers={"Cache-Control": "private, no-store"})


@router.put("/api/management/escalation-rules/{level}", response_model=schemas.EscalationRule,
            responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def update_escalation_rule(level: int, body: schemas.EscalationRule,
                           scope: access.AccessScope = Depends(access.current_scope),
                           _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    item = deliverables_mod.update_escalation_rule(level, body.model_dump(exclude={"level"}))
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no escalation rule with that level"))
    return item
