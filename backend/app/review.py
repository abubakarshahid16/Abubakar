"""Persistent workflow records for AI-assisted engineering reviews.

Analysis remains evidence-first and read-only. A review finding is the
workflow record created from that evidence and then managed by people.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz

from .db import connect
from .config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_schema() -> None:
    conn = connect()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                discipline TEXT,
                deliverable_type TEXT,
                governing_sources TEXT NOT NULL DEFAULT '[]',
                categories TEXT NOT NULL DEFAULT '[]',
                severity_levels TEXT NOT NULL DEFAULT '[]',
                approval_terms TEXT NOT NULL DEFAULT '[]',
                required_sections TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, version)
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_templates_active "
                     "ON review_templates(active, discipline, deliverable_type)")
        conn.execute("""CREATE TABLE IF NOT EXISTS review_baseline_rules (
            id TEXT PRIMARY KEY, submittal_doc_type TEXT, submittal_discipline TEXT,
            baseline_doc_type TEXT NOT NULL, baseline_discipline TEXT,
            priority INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL)""")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_findings (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                baseline_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
                template_id TEXT REFERENCES review_templates(id) ON DELETE SET NULL,
                discipline TEXT,
                confidence TEXT,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                requirement TEXT NOT NULL,
                finding TEXT NOT NULL,
                required_action TEXT NOT NULL,
                governing_sources TEXT NOT NULL DEFAULT '[]',
                unresolved_evidence TEXT NOT NULL DEFAULT '[]',
                response_text TEXT,
                disposition TEXT,
                citation_ids TEXT NOT NULL DEFAULT '[]',
                owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                approval_status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                escalation_level INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)")}
        for name, definition in {
            "template_id": "TEXT",
            "discipline": "TEXT",
            "confidence": "TEXT",
            "governing_sources": "TEXT NOT NULL DEFAULT '[]'",
            "unresolved_evidence": "TEXT NOT NULL DEFAULT '[]'",
            "response_text": "TEXT",
            "disposition": "TEXT",
            "approved_by": "TEXT",
            "approved_at": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE review_findings ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_document "
                     "ON review_findings(document_id, status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_due "
                     "ON review_findings(due_date, status)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_finding_events (
                id TEXT PRIMARY KEY,
                finding_id TEXT NOT NULL REFERENCES review_findings(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                changes TEXT NOT NULL DEFAULT '{}',
                actor_user_id TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_finding_events_finding "
                     "ON review_finding_events(finding_id, created_at DESC)")


def _row(row) -> dict:
    result = dict(row)
    try:
        result["citation_ids"] = json.loads(result.get("citation_ids") or "[]")
    except (TypeError, ValueError):
        result["citation_ids"] = []
    try:
        result["governing_sources"] = json.loads(result.get("governing_sources") or "[]")
    except (TypeError, ValueError):
        result["governing_sources"] = []
    try:
        result["unresolved_evidence"] = json.loads(result.get("unresolved_evidence") or "[]")
    except (TypeError, ValueError):
        result["unresolved_evidence"] = []
    return result


_TEMPLATE_LIST_FIELDS = (
    "governing_sources", "categories", "severity_levels", "approval_terms",
    "required_sections",
)


def _template_row(row) -> dict:
    result = dict(row)
    for field in _TEMPLATE_LIST_FIELDS:
        try:
            result[field] = json.loads(result.get(field) or "[]")
        except (TypeError, ValueError):
            result[field] = []
    result["active"] = bool(result.get("active"))
    return result


def list_templates(*, active_only: bool = True, discipline: str | None = None,
                   deliverable_type: str | None = None) -> list[dict]:
    ensure_schema()
    clauses: list[str] = []
    args: list[str | int] = []
    if active_only:
        clauses.append("active = 1")
    if discipline:
        clauses.append("(discipline = ? OR discipline IS NULL)")
        args.append(discipline)
    if deliverable_type:
        clauses.append("(deliverable_type = ? OR deliverable_type IS NULL)")
        args.append(deliverable_type)
    sql = "SELECT * FROM review_templates"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name, version DESC"
    return [_template_row(row) for row in connect().execute(sql, args).fetchall()]


def create_baseline_rule(payload: dict) -> dict:
    ensure_schema()
    item = {"id": str(uuid.uuid4()), "created_at": _now(), **payload}
    with connect() as conn:
        conn.execute("""INSERT INTO review_baseline_rules
            (id,submittal_doc_type,submittal_discipline,baseline_doc_type,
             baseline_discipline,priority,active,created_at)
            VALUES (:id,:submittal_doc_type,:submittal_discipline,:baseline_doc_type,
                    :baseline_discipline,:priority,:active,:created_at)""", item)
    return item


def list_baseline_rules() -> list[dict]:
    ensure_schema()
    return [dict(row) for row in connect().execute(
        "SELECT * FROM review_baseline_rules ORDER BY priority DESC, created_at DESC").fetchall()]


def update_baseline_rule(rule_id: str, payload: dict) -> dict | None:
    ensure_schema()
    allowed = {"submittal_doc_type", "submittal_discipline", "baseline_doc_type", "baseline_discipline", "priority", "active"}
    changes = {key: value for key, value in payload.items() if key in allowed}
    if changes:
        with connect() as conn:
            conn.execute(f"UPDATE review_baseline_rules SET {', '.join(f'{key} = ?' for key in changes)} WHERE id = ?", [*changes.values(), rule_id])
    row = connect().execute("SELECT * FROM review_baseline_rules WHERE id = ?", (rule_id,)).fetchone()
    return dict(row) if row else None


def auto_select_baseline(document_id: str, *, allowed_document_ids: frozenset[str] | None = None) -> dict | None:
    ensure_schema()
    source = connect().execute(
        "SELECT doc_type, discipline FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    if source is None:
        return None
    rules = connect().execute("""SELECT * FROM review_baseline_rules WHERE active = 1
        AND (submittal_doc_type IS NULL OR submittal_doc_type = ?)
        AND (submittal_discipline IS NULL OR submittal_discipline = ?)
        ORDER BY priority DESC, created_at DESC""",
        (source["doc_type"], source["discipline"])).fetchall()
    for rule in rules:
        sql = """SELECT d.id FROM documents d JOIN document_classification c ON c.document_id = d.id
                 WHERE d.id != ? AND d.status IN ('ready','partially_searchable') AND c.doc_type = ?"""
        args: list[object] = [document_id, rule["baseline_doc_type"]]
        if rule["baseline_discipline"]:
            sql += " AND c.discipline = ?"; args.append(rule["baseline_discipline"])
        if allowed_document_ids is not None:
            if not allowed_document_ids: continue
            marks = ",".join("?" for _ in allowed_document_ids)
            sql += f" AND d.id IN ({marks})"; args.extend(sorted(allowed_document_ids))
        candidate = connect().execute(sql + " ORDER BY d.uploaded_at DESC LIMIT 1", args).fetchone()
        if candidate:
            return {"document_id": candidate["id"], "rule_id": rule["id"], "automatic": True}
    return None


def resolve_baseline(document_id: str, override_document_id: str | None = None,
                     *, allowed_document_ids: frozenset[str] | None = None) -> dict | None:
    """Manual choice wins; automatic mapping is only the default."""
    if override_document_id:
        if allowed_document_ids is not None and override_document_id not in allowed_document_ids:
            return None
        return {"document_id": override_document_id, "rule_id": None, "automatic": False}
    return auto_select_baseline(document_id, allowed_document_ids=allowed_document_ids)


def traceability(finding_id: str, *, allowed_document_ids: frozenset[str] | None = None) -> dict | None:
    """Return the evidence/workflow chain for one finding."""
    ensure_schema()
    from . import deliverables as deliverables_mod
    deliverables_mod.ensure_schema()
    row = connect().execute("""SELECT rf.*, d.filename, b.filename AS baseline_filename
        FROM review_findings rf JOIN documents d ON d.id=rf.document_id
        LEFT JOIN documents b ON b.id=rf.baseline_document_id WHERE rf.id=?""", (finding_id,)).fetchone()
    if row is None or (allowed_document_ids is not None and row["document_id"] not in allowed_document_ids):
        return None
    events = [dict(item) for item in connect().execute(
        "SELECT * FROM review_finding_events WHERE finding_id=? ORDER BY created_at", (finding_id,)).fetchall()]
    deliverables = [dict(item) for item in connect().execute(
        "SELECT id,wbs_code,title,status,revision FROM deliverables WHERE document_id=? ORDER BY wbs_code",
        (row["document_id"],)).fetchall()]
    owner = None
    if deliverables:
        owner = connect().execute(
            """SELECT ds.user_id, u.email, u.display_name
               FROM deliverable_stakeholders ds JOIN users u ON u.id=ds.user_id
               WHERE ds.deliverable_id IN ({}) AND ds.role='owner'
               ORDER BY ds.created_at LIMIT 1""".format(",".join("?" for _ in deliverables)),
            [item["id"] for item in deliverables]).fetchone()
    if owner is None and row["owner_user_id"]:
        owner = connect().execute(
            "SELECT id AS user_id, email, display_name FROM users WHERE id=?",
            (row["owner_user_id"],)).fetchone()
    return {"finding": _row(row), "document": {"id": row["document_id"], "filename": row["filename"]},
            "baseline": ({"filename": row["baseline_filename"]} if row["baseline_filename"] else None),
            "citations": json.loads(row["citation_ids"] or "[]"), "events": events,
            "deliverables": deliverables, "owner": (dict(owner) if owner else None),
            "action": row["required_action"]}


def create_template(payload: dict, *, created_by: str | None) -> dict:
    ensure_schema()
    now = _now()
    template_id = str(uuid.uuid4())
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO review_templates
               (id, name, version, description, discipline, deliverable_type,
                governing_sources, categories, severity_levels, approval_terms,
                required_sections, active, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                template_id, payload["name"], payload["version"],
                payload.get("description", ""), payload.get("discipline"),
                payload.get("deliverable_type"),
                *(json.dumps(payload.get(field, [])) for field in _TEMPLATE_LIST_FIELDS),
                1 if payload.get("active", True) else 0, created_by, now, now,
            ),
        )
    row = connect().execute("SELECT * FROM review_templates WHERE id = ?", (template_id,)).fetchone()
    return _template_row(row)  # type: ignore[arg-type]


def _event(conn, finding_id: str, event_type: str, changes: dict,
           actor_user_id: str | None, created_at: str) -> None:
    conn.execute(
        """INSERT INTO review_finding_events
           (id, finding_id, event_type, changes, actor_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), finding_id, event_type, json.dumps(changes),
         actor_user_id, created_at),
    )


def create(payload: dict, *, created_by: str | None) -> dict:
    ensure_schema()
    now = _now()
    finding_id = str(uuid.uuid4())
    governing_sources = list(payload.get("governing_sources", []))
    template_id = payload.get("template_id")
    discipline = payload.get("discipline")
    if template_id and not governing_sources:
        template = connect().execute(
            "SELECT governing_sources, discipline FROM review_templates WHERE id = ? AND active = 1",
            (template_id,),
        ).fetchone()
        if template:
            try:
                governing_sources = json.loads(template["governing_sources"] or "[]")
            except (TypeError, ValueError):
                governing_sources = []
            discipline = discipline or template["discipline"]
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO review_findings
               (id, document_id, baseline_document_id, template_id, discipline, confidence, category, severity,
               requirement, finding, required_action, governing_sources, unresolved_evidence, response_text, disposition, citation_ids,
               owner_user_id, due_date, status, approval_status, approved_by, approved_at,
               escalation_level, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding_id, payload["document_id"], payload.get("baseline_document_id"), template_id,
                discipline, payload.get("confidence"),
                payload["category"], payload["severity"], payload["requirement"],
                payload["finding"], payload["required_action"], json.dumps(governing_sources),
                json.dumps(payload.get("unresolved_evidence", [])),
                payload.get("response_text"), payload.get("disposition"),
                json.dumps(payload.get("citation_ids", [])), payload.get("owner_user_id"),
                payload.get("due_date"), payload.get("status", "open"),
                payload.get("approval_status", "pending"), payload.get("approved_by"),
                payload.get("approved_at"), payload.get("escalation_level", 0),
                created_by, now, now,
            ),
        )
        _event(conn, finding_id, "created", {
            "severity": payload["severity"],
            "status": payload.get("status", "open"),
            "approval_status": payload.get("approval_status", "pending"),
        }, created_by, now)
    return get(finding_id)  # type: ignore[return-value]


def get(finding_id: str) -> dict | None:
    ensure_schema()
    row = connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    return _row(row) if row else None


def list_findings(*, document_id: str | None = None, status: str | None = None,
                  allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    ensure_schema()
    clauses: list[str] = []
    args: list[str] = []
    if document_id:
        clauses.append("document_id = ?")
        args.append(document_id)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if allowed_document_ids is not None:
        if not allowed_document_ids:
            return []
        marks = ",".join("?" for _ in allowed_document_ids)
        clauses.append(f"document_id IN ({marks})")
        args.extend(sorted(allowed_document_ids))
    sql = "SELECT * FROM review_findings"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += (" ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 "
            "WHEN 'minor' THEN 2 ELSE 3 END, updated_at DESC")
    return [_row(row) for row in connect().execute(sql, args).fetchall()]


def history(finding_id: str) -> list[dict]:
    ensure_schema()
    rows = connect().execute(
        "SELECT * FROM review_finding_events WHERE finding_id = ? "
        "ORDER BY rowid ASC", (finding_id,)
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["changes"] = json.loads(item.get("changes") or "{}")
        except (TypeError, ValueError):
            item["changes"] = {}
        out.append(item)
    return out


def update(finding_id: str, changes: dict, *, actor_user_id: str | None = None) -> dict | None:
    ensure_schema()
    allowed = {"owner_user_id", "due_date", "status", "approval_status",
               "escalation_level", "required_action", "severity", "response_text",
               "disposition", "approved_by", "approved_at"}
    current = get(finding_id)
    if current is None:
        return None
    changed = {key: value for key, value in changes.items()
               if key in allowed and value is not None
               and value != current.get(key)}
    if not changed:
        return current
    sets: list[str] = []
    args: list[object] = []
    for key, value in changed.items():
        sets.append(f"{key} = ?")
        args.append(value)
    now = _now()
    sets.append("updated_at = ?")
    args.extend([now, finding_id])
    conn = connect()
    with conn:
        if conn.execute(f"UPDATE review_findings SET {', '.join(sets)} WHERE id = ?", args).rowcount == 0:
            return None
        _event(conn, finding_id, "updated", changed, actor_user_id, now)
    return get(finding_id)


def render_report(document_id: str) -> Path:
    """Freeze the current review findings into a readable PDF export."""
    ensure_schema()
    doc = connect().execute(
        "SELECT filename FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if doc is None:
        raise FileNotFoundError(document_id)
    findings = list_findings(document_id=document_id)
    report_dir = settings.data_dir / "review_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"engineering-review-{uuid.uuid4()}.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    y = 48
    page.insert_text((48, y), "ENGINEERING SUBMITTAL REVIEW", fontsize=18, fontname="hebo", color=(0.07, 0.23, 0.32))
    y += 24
    page.insert_text((48, y), f"Document: {doc['filename']}", fontsize=10, fontname="helv")
    y += 15
    page.insert_text((48, y), f"Generated: {_now()}  ·  Findings: {len(findings)}", fontsize=9, fontname="helv", color=(0.3, 0.35, 0.4))
    y += 24
    page.draw_rect(fitz.Rect(48, y, 548, y + 34), color=(0.7, 0.32, 0.04), fill=(1, 0.97, 0.91), width=0.8)
    page.insert_textbox(fitz.Rect(58, y + 7, 538, y + 28),
                        "AI-assisted record. A qualified engineer must review and approve before use.",
                        fontsize=9, fontname="helv", color=(0.45, 0.2, 0.02))
    y += 52
    for index, finding in enumerate(findings, 1):
        block = (
            f"{index}. [{finding['severity'].upper()}] {finding['category'].replace('_', ' ')}\n"
            f"Requirement: {finding['requirement']}\n"
            f"Finding: {finding['finding']}\n"
            f"Required action: {finding['required_action']}\n"
            f"Discipline: {finding.get('discipline') or 'not specified'}  |  Confidence: {finding.get('confidence') or 'not recorded'}\n"
            f"Governing sources: {', '.join(finding.get('governing_sources') or []) or 'not recorded'}\n"
            f"Evidence IDs: {', '.join(finding.get('citation_ids') or []) or 'none'}\n"
            f"Owner: {finding.get('owner_user_id') or 'unassigned'}  |  Due: {finding.get('due_date') or 'not set'}\n"
            f"Response: {finding.get('response_text') or 'not provided'}\n"
            f"Disposition: {finding.get('disposition') or 'not recorded'}  |  Approval: {finding.get('approval_status') or 'pending'}\n"
            f"Status: {finding['status']}  |  Escalation level: {finding['escalation_level']}"
        )
        height = 150 if len(block) < 900 else 190
        if y + height > 770:
            page = pdf.new_page()
            y = 48
        page.draw_rect(fitz.Rect(48, y, 548, y + height), color=(0.65, 0.72, 0.75), fill=(0.96, 0.98, 0.98), width=0.5)
        page.insert_textbox(fitz.Rect(58, y + 8, 538, y + height - 8), block, fontsize=8.5, fontname="helv", lineheight=1.25)
        y += height + 12
    if not findings:
        page.insert_text((48, y), "No review findings have been recorded for this document.", fontsize=10, fontname="helv")
    pdf.save(str(path))
    pdf.close()
    return path
