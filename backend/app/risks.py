"""Typed EPC risk register, kept separate from evidence-backed findings."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from .db import connect

RISK_TYPES = frozenset({"schedule", "review", "dependency", "compliance"})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def ensure_schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS risks (
            id TEXT PRIMARY KEY, risk_type TEXT NOT NULL CHECK(risk_type IN ('schedule','review','dependency','compliance')),
            title TEXT NOT NULL, description TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open', deliverable_id TEXT, document_id TEXT,
            owner_user_id TEXT, due_date TEXT, source_finding_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

def create(payload: dict) -> dict:
    ensure_schema()
    if payload["risk_type"] not in RISK_TYPES: raise ValueError("unsupported risk type")
    now = _now(); item = {"id": str(uuid.uuid4()), "severity": "medium", "status": "open",
                           "deliverable_id": None, "document_id": None, "owner_user_id": None,
                           "due_date": None, "source_finding_id": None,
                           "created_at": now, "updated_at": now, **payload}
    with connect() as conn:
        conn.execute("""INSERT INTO risks (id,risk_type,title,description,severity,status,deliverable_id,document_id,owner_user_id,due_date,source_finding_id,created_at,updated_at)
            VALUES (:id,:risk_type,:title,:description,:severity,:status,:deliverable_id,:document_id,:owner_user_id,:due_date,:source_finding_id,:created_at,:updated_at)""", item)
    return item

def list_items(*, allowed_document_ids: frozenset[str] | None = None, risk_type: str | None = None) -> list[dict]:
    ensure_schema(); clauses=[]; args=[]
    if risk_type: clauses.append("risk_type = ?"); args.append(risk_type)
    if allowed_document_ids is not None:
        if not allowed_document_ids: return []
        marks=",".join("?" for _ in allowed_document_ids); clauses.append(f"(document_id IS NULL OR document_id IN ({marks}))"); args.extend(sorted(allowed_document_ids))
    sql="SELECT * FROM risks" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC"
    return [dict(row) for row in connect().execute(sql,args).fetchall()]


def _open_exists(*, risk_type: str, deliverable_id: str | None = None,
                 source_finding_id: str | None = None, document_id: str | None = None) -> bool:
    clauses = ["risk_type = ?", "status = 'open'"]
    args: list[str | None] = [risk_type]
    if deliverable_id is not None:
        clauses.append("deliverable_id = ?"); args.append(deliverable_id)
    if source_finding_id is not None:
        clauses.append("source_finding_id = ?"); args.append(source_finding_id)
    if document_id is not None:
        clauses.append("document_id = ?"); args.append(document_id)
    return connect().execute("SELECT 1 FROM risks WHERE " + " AND ".join(clauses) + " LIMIT 1", args).fetchone() is not None


def detect_automatic_risks(*, allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    """Create idempotent risks from already-tracked EPC workflow state."""
    ensure_schema()
    from . import deliverables as deliverables_mod, review as review_mod, notifications
    created: list[dict] = []
    visible_deliverables = deliverables_mod.list_items(allowed_document_ids=allowed_document_ids)
    visible_ids = {item["id"] for item in visible_deliverables}
    for alert in deliverables_mod.alerts(allowed_document_ids=allowed_document_ids):
        if not _open_exists(risk_type="schedule", deliverable_id=alert["deliverable_id"]):
            item = create({"risk_type": "schedule", "title": f"Overdue deliverable: {alert['title']}",
                           "description": f"{alert['days_overdue']} days overdue; escalation level {alert['escalation_level']}.",
                           "severity": alert["severity"], "deliverable_id": alert["deliverable_id"], "due_date": alert["due_date"]})
            created.append(item)
            notifications.send_email(subject=f"EPC schedule risk: {alert['title']}", body=item["description"],
                                      trigger="automatic_risk", resource_type="risk", resource_id=item["id"])
    now = datetime.now(timezone.utc)
    for finding in review_mod.list_findings(allowed_document_ids=allowed_document_ids):
        try:
            updated = datetime.fromisoformat(finding["updated_at"].replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if finding["status"] in {"open", "in_progress", "awaiting_response"} and now - updated > timedelta(days=7):
            if not _open_exists(risk_type="review", source_finding_id=finding["id"]):
                item = create({"risk_type": "review", "title": "Review response overdue",
                               "description": "This finding has remained open beyond the seven-day review target.",
                               "severity": finding["severity"], "document_id": finding["document_id"],
                               "source_finding_id": finding["id"], "owner_user_id": finding.get("owner_user_id"),
                               "due_date": finding.get("due_date")})
                created.append(item)
                notifications.send_email(subject="EPC review risk", body=item["description"], trigger="automatic_risk",
                                          resource_type="risk", resource_id=item["id"])
        if finding["category"] == "requirement_deviation" and finding.get("unresolved_evidence"):
            if not _open_exists(risk_type="compliance", source_finding_id=finding["id"]):
                item = create({"risk_type": "compliance", "title": "Requirement lacks supporting evidence",
                               "description": "Gap analysis found unresolved evidence for this requirement.",
                               "severity": finding["severity"], "document_id": finding["document_id"],
                               "source_finding_id": finding["id"], "owner_user_id": finding.get("owner_user_id")})
                created.append(item)
                notifications.send_email(subject="EPC compliance risk", body=item["description"], trigger="automatic_risk",
                                          resource_type="risk", resource_id=item["id"])
    for item in visible_deliverables:
        parent_id = item.get("parent_id")
        if not parent_id or parent_id not in visible_ids or item["status"] in {"approved", "superseded"}:
            continue
        parent = next((candidate for candidate in visible_deliverables if candidate["id"] == parent_id), None)
        if not parent or parent["status"] in {"approved", "superseded"} or not parent.get("due_date"):
            continue
        try:
            overdue = (now.date() - datetime.fromisoformat(parent["due_date"].replace("Z", "+00:00")).date()).days >= 0
        except ValueError:
            overdue = False
        if overdue and not _open_exists(risk_type="dependency", deliverable_id=item["id"]):
            item_risk = create({"risk_type": "dependency", "title": f"Dependency overdue: {item['title']}",
                                "description": f"Parent deliverable {parent['title']} is overdue.",
                                "severity": "major", "deliverable_id": item["id"], "due_date": item.get("due_date")})
            created.append(item_risk)
            notifications.send_email(subject="EPC dependency risk", body=item_risk["description"], trigger="automatic_risk",
                                      resource_type="risk", resource_id=item_risk["id"])
    return created
