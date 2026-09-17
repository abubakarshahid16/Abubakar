"""Revision-aware EPC deliverable and WBS records."""
from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

import fitz

from .db import connect
from .config import settings
from . import notifications


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS deliverables (
            id TEXT PRIMARY KEY,
            wbs_code TEXT NOT NULL,
            parent_id TEXT REFERENCES deliverables(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            deliverable_type TEXT NOT NULL,
            revision TEXT NOT NULL DEFAULT '0',
            status TEXT NOT NULL DEFAULT 'planned',
            document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
            owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            planned_date TEXT,
            due_date TEXT,
            submitted_at TEXT,
            approved_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(deliverables)")}
        if "parent_id" not in columns:
            conn.execute("ALTER TABLE deliverables ADD COLUMN parent_id TEXT REFERENCES deliverables(id) ON DELETE SET NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deliverables_wbs ON deliverables(wbs_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deliverables_parent ON deliverables(parent_id, wbs_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deliverables_due ON deliverables(due_date, status)")
        conn.execute("""CREATE TABLE IF NOT EXISTS deliverable_expectations (
            id TEXT PRIMARY KEY, wbs_code TEXT NOT NULL, deliverable_type TEXT NOT NULL,
            title TEXT NOT NULL, required INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            UNIQUE(wbs_code, deliverable_type)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS deliverable_events (
            id TEXT PRIMARY KEY,
            deliverable_id TEXT NOT NULL REFERENCES deliverables(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            changes TEXT NOT NULL DEFAULT '{}',
            actor_user_id TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deliverable_events_item ON deliverable_events(deliverable_id, created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS deliverable_stakeholders (
            deliverable_id TEXT NOT NULL REFERENCES deliverables(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('owner','reviewer','approver','informed')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (deliverable_id, user_id, role)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deliverable_stakeholders_role ON deliverable_stakeholders(deliverable_id, role)")
        # Preserve the pre-stakeholder schema's single owner during migration.
        conn.execute("""INSERT OR IGNORE INTO deliverable_stakeholders
            (deliverable_id, user_id, role, created_at)
            SELECT id, owner_user_id, 'owner', updated_at
            FROM deliverables WHERE owner_user_id IS NOT NULL""")
        conn.execute("""CREATE TABLE IF NOT EXISTS reminder_events (
            id TEXT PRIMARY KEY,
            deliverable_id TEXT NOT NULL REFERENCES deliverables(id) ON DELETE CASCADE,
            level INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            recipient_role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            acknowledged_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(deliverable_id, level, due_date)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS escalation_rules (
            level INTEGER PRIMARY KEY, trigger_days INTEGER NOT NULL,
            recipient_role TEXT NOT NULL, action TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
        )""")
        defaults = [
            (1, 0, "Deliverable owner", "Send due-date reminder and request status update."),
            (2, 7, "Project manager", "Escalate overdue deliverable for recovery plan."),
            (3, 14, "Engineering manager", "Require formal review and corrective action."),
            (4, 30, "Project controls / contract admin", "Flag contractual delivery risk to management."),
        ]
        for level, days, role, action in defaults:
            conn.execute("INSERT OR IGNORE INTO escalation_rules(level, trigger_days, recipient_role, action) VALUES (?,?,?,?)", (level, days, role, action))


def escalation_rules() -> list[dict]:
    ensure_schema()
    return [dict(row) for row in connect().execute("SELECT level, trigger_days, recipient_role, action, enabled FROM escalation_rules ORDER BY level").fetchall()]


def update_escalation_rule(level: int, changes: dict) -> dict | None:
    ensure_schema()
    allowed = {"trigger_days", "recipient_role", "action", "enabled"}
    pairs = [(k, changes[k]) for k in allowed if k in changes]
    if pairs:
        with connect() as conn:
            conn.execute(f"UPDATE escalation_rules SET {', '.join(f'{k} = ?' for k, _ in pairs)} WHERE level = ?", [v for _, v in pairs] + [level])
    row = connect().execute("SELECT level, trigger_days, recipient_role, action, enabled FROM escalation_rules WHERE level = ?", (level,)).fetchone()
    return dict(row) if row else None


def create(payload: dict, *, created_by: str | None) -> dict:
    ensure_schema()
    now = _now()
    item = {
        "id": str(uuid.uuid4()), "wbs_code": payload["wbs_code"],
        "parent_id": payload.get("parent_id"),
        "title": payload["title"], "deliverable_type": payload["deliverable_type"],
        "revision": payload.get("revision", "0"), "status": payload.get("status", "planned"),
        "document_id": payload.get("document_id"), "owner_user_id": payload.get("owner_user_id"),
        "planned_date": payload.get("planned_date"), "due_date": payload.get("due_date"),
        "submitted_at": payload.get("submitted_at"), "approved_at": payload.get("approved_at"),
        "created_by": created_by, "created_at": now, "updated_at": now,
    }
    with connect() as conn:
        conn.execute("""INSERT INTO deliverables
            (id,wbs_code,parent_id,title,deliverable_type,revision,status,document_id,owner_user_id,
             planned_date,due_date,submitted_at,approved_at,created_by,created_at,updated_at)
            VALUES (:id,:wbs_code,:parent_id,:title,:deliverable_type,:revision,:status,:document_id,:owner_user_id,
                    :planned_date,:due_date,:submitted_at,:approved_at,:created_by,:created_at,:updated_at)""", item)
        conn.execute("INSERT INTO deliverable_events (id, deliverable_id, event_type, changes, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), item["id"], "created", json.dumps({"revision": item["revision"], "status": item["status"]}), created_by, now))
    return item


def list_items(*, allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    ensure_schema()
    sql = "SELECT * FROM deliverables"
    args: list[str] = []
    if allowed_document_ids is not None:
        if not allowed_document_ids:
            return []
        marks = ",".join("?" for _ in allowed_document_ids)
        sql += f" WHERE document_id IS NULL OR document_id IN ({marks})"
        args.extend(sorted(allowed_document_ids))
    sql += " ORDER BY wbs_code, due_date, revision"
    return [dict(row) for row in connect().execute(sql, args).fetchall()]


def expected_missing(*, wbs_code: str | None = None,
                     allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    """Return configured expected deliverables and their registered status."""
    ensure_schema()
    sql = "SELECT e.*, d.id AS deliverable_id, d.status FROM deliverable_expectations e " \
          "LEFT JOIN deliverables d ON d.wbs_code=e.wbs_code AND d.deliverable_type=e.deliverable_type"
    args: list[str] = []
    if wbs_code:
        sql += " WHERE e.wbs_code = ?"; args.append(wbs_code)
    rows = connect().execute(sql, args).fetchall()
    return [dict(row) | {"state": "registered" if row["deliverable_id"] else "missing"}
            for row in rows]


def configure_expectation(payload: dict) -> dict:
    ensure_schema()
    item = {"id": str(uuid.uuid4()), "created_at": _now(), **payload}
    with connect() as conn:
        conn.execute("""INSERT INTO deliverable_expectations
            (id,wbs_code,deliverable_type,title,required,created_at)
            VALUES (:id,:wbs_code,:deliverable_type,:title,:required,:created_at)
            ON CONFLICT(wbs_code,deliverable_type) DO UPDATE SET title=excluded.title, required=excluded.required""", item)
    return item


def get(item_id: str) -> dict | None:
    ensure_schema()
    row = connect().execute("SELECT * FROM deliverables WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def _would_cycle(item_id: str, parent_id: str | None) -> bool:
    seen: set[str] = set()
    current = parent_id
    while current:
        if current == item_id or current in seen:
            return True
        seen.add(current)
        row = connect().execute("SELECT parent_id FROM deliverables WHERE id = ?", (current,)).fetchone()
        current = row["parent_id"] if row else None
    return False


def workspace(item_id: str, *, allowed_document_ids: frozenset[str] | None = None) -> dict | None:
    """One WBS node view: hierarchy links plus document/review/risk context."""
    ensure_schema()
    item = get(item_id)
    if item is None:
        return None
    if item.get("document_id") and allowed_document_ids is not None and item["document_id"] not in allowed_document_ids:
        return None
    children = [dict(row) for row in connect().execute(
        "SELECT * FROM deliverables WHERE parent_id = ? ORDER BY wbs_code", (item_id,)
    ).fetchall()]
    document_ids = [item["document_id"]] if item.get("document_id") else []
    document_ids.extend(child["document_id"] for child in children if child.get("document_id"))
    if allowed_document_ids is not None:
        document_ids = [doc_id for doc_id in document_ids if doc_id in allowed_document_ids]
    from . import review as review_mod
    findings = review_mod.list_findings(allowed_document_ids=frozenset(document_ids)) if document_ids else []
    return {"node": item, "children": children,
            "documents": [{"id": doc_id} for doc_id in document_ids],
            "reviews": findings,
            "escalations": alerts(allowed_document_ids=allowed_document_ids)}


STAKEHOLDER_ROLES = frozenset({"owner", "reviewer", "approver", "informed"})


def stakeholders(item_id: str) -> list[dict]:
    ensure_schema()
    rows = connect().execute(
        """SELECT ds.deliverable_id, ds.user_id, ds.role, u.email, u.display_name
           FROM deliverable_stakeholders ds JOIN users u ON u.id = ds.user_id
           WHERE ds.deliverable_id = ? ORDER BY ds.role, u.email""", (item_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def stakeholder_emails(item_id: str, role: str) -> list[str]:
    return [row["email"] for row in stakeholders(item_id) if row["role"] == role]


def replace_stakeholders(item_id: str, assignments: list[dict], *, actor_user_id: str | None) -> list[dict] | None:
    ensure_schema()
    if get(item_id) is None:
        return None
    cleaned: list[tuple[str, str]] = []
    for assignment in assignments:
        user_id = str(assignment.get("user_id") or "")
        role = str(assignment.get("role") or "")
        if user_id and role in STAKEHOLDER_ROLES:
            cleaned.append((user_id, role))
    now = _now()
    with connect() as conn:
        conn.execute("DELETE FROM deliverable_stakeholders WHERE deliverable_id = ?", (item_id,))
        for user_id, role in sorted(set(cleaned)):
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                conn.execute("""INSERT INTO deliverable_stakeholders
                    (deliverable_id, user_id, role, created_at) VALUES (?, ?, ?, ?)""",
                    (item_id, user_id, role, now))
        conn.execute("""INSERT INTO deliverable_events
            (id, deliverable_id, event_type, changes, actor_user_id, created_at)
            VALUES (?, ?, 'stakeholders_replaced', ?, ?, ?)""",
            (str(uuid.uuid4()), item_id, json.dumps({"count": len(cleaned)}), actor_user_id, now))
    return stakeholders(item_id)


def update(item_id: str, changes: dict, *, actor_user_id: str | None = None) -> dict | None:
    ensure_schema()
    allowed = {"wbs_code", "parent_id", "title", "deliverable_type", "revision", "status", "document_id",
               "owner_user_id", "planned_date", "due_date", "submitted_at", "approved_at"}
    changed = {k: changes[k] for k in changes if k in allowed and changes[k] is not None}
    if "parent_id" in changed and _would_cycle(item_id, changed["parent_id"]):
        raise ValueError("WBS parent would create a cycle")
    sets = [f"{k} = ?" for k in changed]
    if not sets:
        row = connect().execute("SELECT * FROM deliverables WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None
    args = [changed[k] for k in changed]
    now = _now()
    sets.append("updated_at = ?"); args.extend([now, item_id])
    with connect() as conn:
        if conn.execute(f"UPDATE deliverables SET {', '.join(sets)} WHERE id = ?", args).rowcount == 0:
            return None
        conn.execute("INSERT INTO deliverable_events (id, deliverable_id, event_type, changes, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), item_id, "updated", json.dumps(changed), actor_user_id, now))
    row = connect().execute("SELECT * FROM deliverables WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def history(item_id: str) -> list[dict]:
    ensure_schema()
    rows = connect().execute("SELECT * FROM deliverable_events WHERE deliverable_id = ? ORDER BY rowid", (item_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["changes"] = json.loads(item.get("changes") or "{}")
        except (TypeError, ValueError):
            item["changes"] = {}
        result.append(item)
    return result


def alerts(*, allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    """Return deterministic reminder/escalation facts; sending is separate."""
    today = datetime.now(timezone.utc).date()
    rows = list_items(allowed_document_ids=allowed_document_ids)
    result: list[dict] = []
    for row in rows:
        if row["status"] in {"approved", "superseded"} or not row.get("due_date"):
            continue
        try:
            due = datetime.fromisoformat(row["due_date"].replace("Z", "+00:00")).date()
        except ValueError:
            continue
        days = (today - due).days
        if days < 0:
            continue
        result.append({
            "deliverable_id": row["id"], "wbs_code": row["wbs_code"],
            "title": row["title"], "due_date": row["due_date"],
            "days_overdue": days, "escalation_level": min(5, 1 + days // 7),
            "severity": "critical" if days >= 14 else "major" if days >= 7 else "minor",
        })
    return result


def reminder_events(*, allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    ensure_schema()
    items = list_items(allowed_document_ids=allowed_document_ids)
    rules = {r["level"]: r for r in escalation_rules()}
    now = _now()
    conn = connect()
    for alert in alerts(allowed_document_ids=allowed_document_ids):
        rule = rules.get(alert["escalation_level"]) or rules.get(1)
        if rule is None:
            continue
        with conn:
            inserted = conn.execute(
                """INSERT OR IGNORE INTO reminder_events
                   (id, deliverable_id, level, due_date, recipient_role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), alert["deliverable_id"], alert["escalation_level"],
                 alert["due_date"], rule["recipient_role"], now),
            ).rowcount
        if inserted:
            stakeholder_role = "owner"
            role_name = str(rule["recipient_role"]).lower()
            for candidate in STAKEHOLDER_ROLES:
                if candidate in role_name:
                    stakeholder_role = candidate
                    break
            recipients = stakeholder_emails(alert["deliverable_id"], stakeholder_role)
            if alert["days_overdue"] == 0:
                notifications.send_reminder(deliverable_id=alert["deliverable_id"], title=alert["title"], due_date=alert["due_date"], recipients=recipients or None)
            else:
                notifications.send_escalation(deliverable_id=alert["deliverable_id"], title=alert["title"], level=alert["escalation_level"], recipients=recipients or None)
    allowed_ids = {item["id"] for item in items}
    rows = connect().execute(
        "SELECT * FROM reminder_events ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows if row["deliverable_id"] in allowed_ids]


def acknowledge_reminder(reminder_id: str) -> dict | None:
    ensure_schema()
    now = _now()
    with connect() as conn:
        conn.execute("UPDATE reminder_events SET status = 'acknowledged', acknowledged_at = ? WHERE id = ?", (now, reminder_id))
    row = connect().execute("SELECT * FROM reminder_events WHERE id = ?", (reminder_id,)).fetchone()
    return dict(row) if row else None


def render_management_report(*, allowed_document_ids: frozenset[str] | None = None) -> Path:
    """Export current WBS, overdue, and reminder controls as a PDF."""
    items = list_items(allowed_document_ids=allowed_document_ids)
    alerts_now = alerts(allowed_document_ids=allowed_document_ids)
    reminders = reminder_events(allowed_document_ids=allowed_document_ids)
    report_dir = settings.data_dir / "management_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"management-report-{uuid.uuid4()}.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((48, 52), "EPC MANAGEMENT REPORT", fontsize=18, fontname="hebo", color=(0.07, 0.23, 0.32))
    page.insert_text((48, 74), f"Generated: {_now()}", fontsize=9, fontname="helv", color=(0.3, 0.35, 0.4))
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    lines = [
        f"Deliverables: {len(items)}",
        "Deliverable status: " + (", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "none"),
        f"Overdue alerts: {len(alerts_now)}",
        f"Reminder events: {len(reminders)} (pending={sum(r['status'] == 'pending' for r in reminders)}, acknowledged={sum(r['status'] == 'acknowledged' for r in reminders)})",
        "",
        "Management control summary. Engineering findings remain evidence-linked in the submittal review report.",
    ]
    page.insert_textbox(fitz.Rect(48, 105, 548, 220), "\n".join(lines), fontsize=11, fontname="helv", lineheight=1.45)
    y = 250
    for alert in alerts_now:
        if y > 760:
            page = pdf.new_page(); y = 48
        page.insert_textbox(fitz.Rect(48, y, 548, y + 32),
                            f"{alert['wbs_code']} · {alert['title']} · {alert['days_overdue']} days overdue · escalation {alert['escalation_level']}",
                            fontsize=9, fontname="helv", color=(0.55, 0.18, 0.02))
        y += 38
    pdf.save(str(path))
    pdf.close()
    return path
