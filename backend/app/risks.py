"""Typed EPC risk register, kept separate from evidence-backed findings."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
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
