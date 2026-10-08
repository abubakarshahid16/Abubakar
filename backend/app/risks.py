"""Typed EPC risk register, kept separate from evidence-backed findings."""
from __future__ import annotations
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta, timezone
from .config import settings
from .db import connect, schema_once

log = logging.getLogger("uvicorn.error")

RISK_TYPES = frozenset({"schedule", "review", "dependency", "compliance"})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

@schema_once
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
        # r2 S3: a risk raised about a deliverable follows that deliverable's
        # document, so a row written before `document_id` was carried (NULL)
        # still does not reach a caller who may not read the deliverable's
        # document.
        clauses.append(f"(deliverable_id IS NULL OR deliverable_id IN (SELECT id FROM deliverables WHERE org_wide = 1 OR document_id IN ({marks})))")
        args.extend(sorted(allowed_document_ids))
    sql="SELECT * FROM risks" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC"
    return [dict(row) for row in connect().execute(sql,args).fetchall()]


OPEN_REVIEW_STATUSES = ("open", "in_progress", "awaiting_response")

_COLUMNS = ("id", "risk_type", "title", "description", "severity", "status", "deliverable_id",
            "document_id", "owner_user_id", "due_date", "source_finding_id", "created_at", "updated_at")


def _new_item(payload: dict) -> dict:
    now = _now()
    return {"id": str(uuid.uuid4()), "severity": "medium", "status": "open",
            "deliverable_id": None, "document_id": None, "owner_user_id": None,
            "due_date": None, "source_finding_id": None,
            "created_at": now, "updated_at": now, **payload}


def _insert_many(items: list[dict]) -> None:
    """All new risks in ONE transaction (one commit, not one per risk)."""
    if not items:
        return
    with connect() as conn:
        conn.executemany(
            "INSERT INTO risks (" + ",".join(_COLUMNS) + ") VALUES ("
            + ",".join(":" + c for c in _COLUMNS) + ")", items)


def _open_risk_keys() -> tuple[set[tuple], set[tuple]]:
    """The open risks that already exist, read with ONE query:
    ({(risk_type, deliverable_id)}, {(risk_type, source_finding_id)}).

    Detection diffs against these sets. It used to ask the database one
    question per finding (`_open_exists`, about 133,000 of them).
    """
    ensure_schema()
    by_deliverable: set[tuple] = set()
    by_finding: set[tuple] = set()
    for row in connect().execute(
            "SELECT risk_type, deliverable_id, source_finding_id FROM risks WHERE status = 'open'"):
        if row["deliverable_id"] is not None:
            by_deliverable.add((row["risk_type"], row["deliverable_id"]))
        if row["source_finding_id"] is not None:
            by_finding.add((row["risk_type"], row["source_finding_id"]))
    return by_deliverable, by_finding


def _candidate_findings(allowed_document_ids: frozenset[str] | None) -> list[dict]:
    """Only the findings detection can act on, and only the columns it reads:
    an open-ish one (the seven-day rule) or a requirement deviation with
    unresolved evidence (the compliance rule). One query."""
    from . import review as review_mod
    review_mod.ensure_schema()
    where = ("(status IN (?,?,?) OR (category = 'requirement_deviation'"
             " AND unresolved_evidence NOT IN ('', '[]', 'null')))")
    args: list[str] = list(OPEN_REVIEW_STATUSES)
    if allowed_document_ids is not None:
        if not allowed_document_ids:
            return []
        where += " AND document_id IN (" + ",".join("?" for _ in allowed_document_ids) + ")"
        args.extend(sorted(allowed_document_ids))
    rows = connect().execute(
        "SELECT id, severity, document_id, owner_user_id, due_date, status, updated_at, category,"
        " unresolved_evidence FROM review_findings WHERE " + where, args).fetchall()
    return [dict(r) for r in rows]


def detect_automatic_risks(*, allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    """Create idempotent risks from already-tracked EPC workflow state.

    NOT A REQUEST HANDLER (#478, #608). It reads the whole register and writes,
    so it runs from `run_detection` (the background job and the admin
    trigger), never from a GET. It asks the database a fixed number of
    questions however many findings there are: the existing open risks are
    read once and diffed, the candidate findings come from one filtered query,
    and the new risks are inserted in one transaction. It sends NO email: the
    caller sends one digest for the whole run.
    """
    ensure_schema()
    from . import deliverables as deliverables_mod
    by_deliverable, by_finding = _open_risk_keys()
    new_items: list[dict] = []
    visible_deliverables = deliverables_mod.list_items(allowed_document_ids=allowed_document_ids)
    by_id = {item["id"]: item for item in visible_deliverables}
    for alert in deliverables_mod.alerts(allowed_document_ids=allowed_document_ids):
        if ("schedule", alert["deliverable_id"]) in by_deliverable:
            continue
        by_deliverable.add(("schedule", alert["deliverable_id"]))
        new_items.append(_new_item({
            "risk_type": "schedule", "title": f"Overdue deliverable: {alert['title']}",
            "description": f"{alert['days_overdue']} days overdue; escalation level {alert['escalation_level']}.",
            "severity": alert["severity"], "deliverable_id": alert["deliverable_id"], "due_date": alert["due_date"],
            # r2 S3: carry the SOURCE document so the scope filter can apply.
            "document_id": (by_id.get(alert["deliverable_id"]) or {}).get("document_id")}))
    now = datetime.now(UTC)
    for finding in _candidate_findings(allowed_document_ids):
        try:
            updated = datetime.fromisoformat(finding["updated_at"].replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
        except (KeyError, ValueError, AttributeError):
            continue
        if (finding["status"] in OPEN_REVIEW_STATUSES and now - updated > timedelta(days=7)
                and ("review", finding["id"]) not in by_finding):
            by_finding.add(("review", finding["id"]))
            new_items.append(_new_item({
                "risk_type": "review", "title": "Review response overdue",
                "description": "This finding has remained open beyond the seven-day review target.",
                "severity": finding["severity"], "document_id": finding["document_id"],
                "source_finding_id": finding["id"], "owner_user_id": finding.get("owner_user_id"),
                "due_date": finding.get("due_date")}))
        if (finding["category"] == "requirement_deviation"
                and finding.get("unresolved_evidence") not in (None, "", "[]", "null")
                and ("compliance", finding["id"]) not in by_finding):
            by_finding.add(("compliance", finding["id"]))
            new_items.append(_new_item({
                "risk_type": "compliance", "title": "Requirement lacks supporting evidence",
                "description": "Gap analysis found unresolved evidence for this requirement.",
                "severity": finding["severity"], "document_id": finding["document_id"],
                "source_finding_id": finding["id"], "owner_user_id": finding.get("owner_user_id")}))
    for item in visible_deliverables:
        parent_id = item.get("parent_id")
        if not parent_id or parent_id not in by_id or item["status"] in {"approved", "superseded"}:
            continue
        parent = by_id.get(parent_id)
        if not parent or parent["status"] in {"approved", "superseded"} or not parent.get("due_date"):
            continue
        try:
            overdue = (now.date() - datetime.fromisoformat(parent["due_date"].replace("Z", "+00:00")).date()).days >= 0
        except ValueError:
            overdue = False
        if overdue and ("dependency", item["id"]) not in by_deliverable:
            by_deliverable.add(("dependency", item["id"]))
            new_items.append(_new_item({
                "risk_type": "dependency", "title": f"Dependency overdue: {item['title']}",
                "description": f"Parent deliverable {parent['title']} is overdue.",
                "severity": "major", "deliverable_id": item["id"], "due_date": item.get("due_date"),
                "document_id": item.get("document_id")}))
    _insert_many(new_items)
    return new_items


_detect_lock = threading.Lock()


def run_detection(*, allowed_document_ids: frozenset[str] | None = None) -> dict:
    """One detection run: single-flight, then ONE digest email.

    Returns {"status": "ok" | "already_running", "created": n, "by_type": {...},
    "digest": "sent" | "disabled" | "rate_limited" | "none" | "failed"}.
    Counts and a status word only: no finding text in the result or the log.
    """
    from . import notifications
    if not _detect_lock.acquire(blocking=False):
        return {"status": "already_running", "created": 0, "by_type": {}, "digest": "none"}
    try:
        from . import deliverables as deliverables_mod
        reminders = deliverables_mod.generate_reminders(allowed_document_ids=allowed_document_ids)
        created = detect_automatic_risks(allowed_document_ids=allowed_document_ids)
        by_type: dict[str, int] = {}
        for item in created:
            by_type[item["risk_type"]] = by_type.get(item["risk_type"], 0) + 1
        try:
            digest = notifications.send_risk_digest(created)
        except Exception:  # a mail failure must not undo the detection
            log.exception("risk digest email failed")
            digest = "failed"
        log.info("risk detection created=%d reminders=%d by_type=%s digest=%s",
                 len(created), reminders, by_type, digest)
        return {"status": "ok", "created": len(created), "by_type": by_type, "digest": digest,
                "reminders_created": reminders}
    finally:
        _detect_lock.release()


# --------------------------------------------------------------- the schedule

_stop = threading.Event()
_thread: threading.Thread | None = None


def start_background_detection() -> threading.Thread | None:
    """Run `run_detection` every `risk_detection_interval_seconds`, in a daemon
    thread. Off when the interval is 0 or the background jobs are off (the
    test suite pins `startup_warmup` off). The first run waits one interval
    after start so booting is never slowed by it."""
    global _thread
    interval = int(settings.risk_detection_interval_seconds)
    if interval <= 0 or not settings.startup_warmup:
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()

    def loop() -> None:
        from . import db
        try:
            while not _stop.wait(interval):
                try:
                    run_detection()
                except Exception:  # logged; the next tick retries
                    log.exception("scheduled risk detection failed")
        finally:
            db.close_thread_connection()

    _thread = threading.Thread(target=loop, name="risk-detection", daemon=True)
    _thread.start()
    return _thread


def stop_background_detection() -> None:
    _stop.set()
