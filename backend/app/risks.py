"""Typed EPC risk register, kept separate from evidence-backed findings."""
from __future__ import annotations
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pydantic import BaseModel

from . import deliverables, severity_rule
from .config import settings
from .db import connect, schema_once
from .schemas import RiskType

log = logging.getLogger("uvicorn.error")

RISK_TYPES = frozenset({"schedule", "review", "dependency", "compliance"})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

@schema_once
def ensure_schema() -> None:
    # A scoped read joins `deliverables` (`_scope_where`), so that table is ensured too.
    deliverables.ensure_schema()
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
    _page_cache.clear()  # after the commit: a read in between re-caches nothing stale
    return item

def _scope_where(allowed_document_ids: frozenset[str] | None, risk_type: str | None) -> tuple[list[str], list] | None:
    """The WHERE clauses every risk read uses; None when the caller may read nothing."""
    clauses: list[str] = []; args: list = []
    if risk_type: clauses.append("risk_type = ?"); args.append(risk_type)
    if allowed_document_ids is not None:
        if not allowed_document_ids: return None
        marks=",".join("?" for _ in allowed_document_ids); clauses.append(f"(document_id IS NULL OR document_id IN ({marks}))"); args.extend(sorted(allowed_document_ids))
        # r2 S3: a risk raised about a deliverable follows that deliverable's
        # document, so a row written before `document_id` was carried (NULL)
        # still does not reach a caller who may not read the deliverable's
        # document.
        clauses.append(f"(deliverable_id IS NULL OR deliverable_id IN (SELECT id FROM deliverables WHERE org_wide = 1 OR document_id IN ({marks})))")
        args.extend(sorted(allowed_document_ids))
    return clauses, args


def list_items(*, allowed_document_ids: frozenset[str] | None = None, risk_type: str | None = None) -> list[dict]:
    """Every risk row, ungrouped (detection and tests). The screen reads `list_page`."""
    ensure_schema()
    scoped = _scope_where(allowed_document_ids, risk_type)
    if scoped is None:
        return []
    clauses, args = scoped
    sql="SELECT * FROM risks" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC"
    return [dict(row) for row in connect().execute(sql,args).fetchall()]


#: Rows of the register one request returns (order 88a): the screen shows a
#: page and the total, never the whole table.
PAGE_SIZE, MAX_PAGE_SIZE = 50, 200

#: Before A10/#924 detection wrote ONE "review"/"compliance" risk PER FINDING
#: (147,770 open rows in the owner's register). Those rows stay as stored; a
#: read shows them as one row per document and status, with the count.
_PER_FINDING = "(source_finding_id IS NOT NULL AND risk_type IN ('review','compliance'))"
_SEVERITY_RANK = "CASE lower(severity) WHEN 'critical' THEN 0 WHEN 'major' THEN 1 WHEN 'minor' THEN 2 ELSE 3 END"


def list_page(*, allowed_document_ids: frozenset[str] | None = None, risk_type: str | None = None,
              limit: int = PAGE_SIZE, offset: int = 0) -> dict:
    """One page of the register, newest first, with the total it is a page of.

    READ ONLY (#478, #608): GET /api/risks used to run detection on every
    call, looping over every finding and emailing per risk. Detection runs in
    the background (`start_background_detection`) and from POST /api/risks/detect.

    A per-finding row from before #924 is grouped with its document's others
    (same type and status) into one row carrying `finding_count`; every other
    row is itself (`finding_count` 1). SQL does the grouping and the paging, so
    a request builds at most `limit` rows however large the table is.

    CACHED for `PAGE_CACHE_SECONDS` per (caller's grants, type, page), and
    cleared by every write in this module (`create`, detection). A document
    delete changes the caller's grants, so it never serves a stale row of a
    document the caller can no longer read."""
    ensure_schema()
    limit = max(1, min(int(limit), MAX_PAGE_SIZE)); offset = max(0, int(offset))
    key = (allowed_document_ids, risk_type, limit, offset)
    hit = _page_cache.get(key)
    if hit and time.monotonic() - hit[0] < PAGE_CACHE_SECONDS:
        return hit[1]
    found = _read_page(allowed_document_ids, risk_type, limit, offset)
    if len(_page_cache) > 256:
        _page_cache.clear()
    _page_cache[key] = (time.monotonic(), found)
    return found


PAGE_CACHE_SECONDS = 15.0
_page_cache: dict[tuple, tuple[float, dict]] = {}


def _read_page(allowed_document_ids: frozenset[str] | None, risk_type: str | None,
               limit: int, offset: int) -> dict:
    scoped = _scope_where(allowed_document_ids, risk_type)
    if scoped is None:
        return {"risks": [], "total": 0, "limit": limit, "offset": offset}
    clauses, args = scoped
    where = " AND ".join(clauses) if clauses else "1=1"
    rows_sql = (
        "SELECT id, risk_type, title, description, severity, status, deliverable_id, document_id,"
        " owner_user_id, due_date, source_finding_id, created_at, updated_at, 1 AS finding_count"
        f" FROM risks WHERE {where} AND NOT {_PER_FINDING}"
        " UNION ALL"
        " SELECT MIN(id), risk_type, MIN(title), '', "
        f" CASE MIN({_SEVERITY_RANK}) WHEN 0 THEN 'critical' WHEN 1 THEN 'major' WHEN 2 THEN 'minor' ELSE 'medium' END,"
        " status, NULL, document_id, NULL, MIN(due_date), NULL, MIN(created_at), MAX(updated_at), COUNT(*)"
        f" FROM risks WHERE {where} AND {_PER_FINDING} GROUP BY risk_type, document_id, status")
    conn = connect()
    total = conn.execute(f"SELECT COUNT(*) AS n FROM ({rows_sql})", args + args).fetchone()["n"]
    page = [dict(r) for r in conn.execute(
        f"SELECT * FROM ({rows_sql}) ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
        [*args, *args, limit, offset]).fetchall()]
    for row in page:
        if row["finding_count"] > 1 or (row["source_finding_id"] is None and row["description"] == ""):
            n = row["finding_count"]
            row["description"] = (f"{n} finding{'s' if n != 1 else ''} on this document, each recorded as its own risk"
                                  " before risks were grouped per document (#924); shown as one row.")
    return {"risks": page, "total": total, "limit": limit, "offset": offset}


class Risk(BaseModel):
    id: str
    risk_type: RiskType
    title: str
    description: str
    severity: str
    status: str
    deliverable_id: str | None
    document_id: str | None
    owner_user_id: str | None
    due_date: str | None
    source_finding_id: str | None
    created_at: str
    updated_at: str
    #: How many stored rows this row stands for: 1, or the per-finding rows of
    #: one document grouped by `list_page` (order 88a).
    finding_count: int = 1


class RiskList(BaseModel):
    """One page of the register and the total it is a page of (order 88a)."""
    risks: list[Risk]
    total: int
    limit: int
    offset: int

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
    _page_cache.clear()


def _open_risk_keys() -> tuple[set[tuple], set[tuple]]:
    """The open risks that already exist, read with ONE query:
    ({(risk_type, deliverable_id)}, {(risk_type, document_id)} for the
    review/compliance types).

    Detection diffs against these sets. It used to ask the database one
    question per finding (`_open_exists`, about 133,000 of them).

    A10/#924: the second set used to key on `source_finding_id` (one open
    risk per FINDING). With 143,558 live findings that grew the risks table
    to 147,770 rows, all open, unreadable to an engineer. It now keys on
    `document_id`: one open "review"/"compliance" risk per document is
    enough to tell the engineer that document needs attention; the
    aggregate's own description names how many findings are behind it as of
    its creation. A document that already has one open of that type is left
    alone - closing it is the engineer's call, not a re-run's.
    """
    ensure_schema()
    by_deliverable: set[tuple] = set()
    by_document_type: set[tuple] = set()
    for row in connect().execute(
            "SELECT risk_type, deliverable_id, document_id FROM risks WHERE status = 'open'"):
        if row["deliverable_id"] is not None:
            by_deliverable.add((row["risk_type"], row["deliverable_id"]))
        if row["risk_type"] in ("review", "compliance") and row["document_id"] is not None:
            by_document_type.add((row["risk_type"], row["document_id"]))
    return by_deliverable, by_document_type


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
        "SELECT id, severity, compliance_status, document_id, owner_user_id, due_date, status,"
        " updated_at, category, unresolved_evidence FROM review_findings WHERE " + where,
        args).fetchall()
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

    A10/#924: the "review" and "compliance" types are ONE RISK PER DOCUMENT,
    not one per finding - see `_open_risk_keys`.
    """
    ensure_schema()
    from . import deliverables as deliverables_mod
    by_deliverable, by_document_type = _open_risk_keys()
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
    candidates = _candidate_findings(allowed_document_ids)
    review_groups: dict[str, list[dict]] = {}
    compliance_groups: dict[str, list[dict]] = {}
    for start in range(0, len(candidates), RISK_BATCH_SIZE):
        # #626 GENTLE: a run over ~133,000 findings used to be one unbroken
        # loop that held the CPU (and the GIL) for as long as it took. A short
        # pause between batches lets the request threads run.
        if start:
            _pause_between_batches()
        _scan_findings(candidates[start:start + RISK_BATCH_SIZE], now, by_document_type,
                      review_groups, compliance_groups)
    for risk_type, groups in (("review", review_groups), ("compliance", compliance_groups)):
        for document_id, group in groups.items():
            new_items.append(_aggregate_item(risk_type, document_id, group, now))
            by_document_type.add((risk_type, document_id))
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


#: Findings examined per batch, and the pause between batches (#626).
RISK_BATCH_SIZE = 1000
RISK_BATCH_PAUSE_SECONDS = 0.05


def _pause_between_batches() -> None:
    time.sleep(RISK_BATCH_PAUSE_SECONDS)


#: Worst first, for the one severity an aggregated risk can honestly carry.
_SEVERITY_ORDER = ("critical", "major", "minor")


def _worst_severity(group: list[dict]) -> str:
    found = {severity_rule.effective_severity(f) for f in group}
    return next((s for s in _SEVERITY_ORDER if s in found), "medium")


def _aggregate_item(risk_type: str, document_id: str, group: list[dict], now: datetime) -> dict:
    """A10/#924: one risk for a whole document, not one per finding. The
    count is stated with the date it was counted on (honesty rule 4: a
    boundary, not a live number this un-updated row keeps claiming)."""
    n = len(group)
    today = now.date().isoformat()
    if risk_type == "review":
        title = "Review responses overdue"
        description = (f"{n} finding{'s' if n != 1 else ''} on this document had remained open "
                       f"beyond the seven-day review target, as counted on {today}.")
    else:
        title = "Requirements lack supporting evidence"
        description = (f"{n} requirement{'s' if n != 1 else ''} on this document had unresolved "
                       f"evidence from gap analysis, as counted on {today}.")
    return _new_item({"risk_type": risk_type, "title": title, "description": description,
                      "severity": _worst_severity(group), "document_id": document_id})


def _scan_findings(findings: list[dict], now: datetime, open_document_types: set,
                   review_groups: dict[str, list[dict]],
                   compliance_groups: dict[str, list[dict]]) -> None:
    """One batch of candidate findings: the overdue-review and the
    unsupported-requirement rules, grouped by document into `review_groups`
    and `compliance_groups`. A document already in `open_document_types`
    (an open risk of that kind exists) is skipped - its findings do not grow
    an aggregate that already stands."""
    for finding in findings:
        try:
            updated = datetime.fromisoformat(finding["updated_at"].replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
        except (KeyError, ValueError, AttributeError):
            continue
        document_id = finding.get("document_id")
        if not document_id:
            continue
        if (finding["status"] in OPEN_REVIEW_STATUSES and now - updated > timedelta(days=7)
                and ("review", document_id) not in open_document_types):
            review_groups.setdefault(document_id, []).append(finding)
        if (finding["category"] == "requirement_deviation"
                and finding.get("unresolved_evidence") not in (None, "", "[]", "null")
                and ("compliance", document_id) not in open_document_types):
            compliance_groups.setdefault(document_id, []).append(finding)


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
    started = time.monotonic()
    log.info("risk detection started")
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
        log.info("risk detection finished in %.1fs created=%d reminders=%d by_type=%s digest=%s",
                 time.monotonic() - started, len(created), reminders, by_type, digest)
        return {"status": "ok", "created": len(created), "by_type": by_type, "digest": digest,
                "reminders_created": reminders}
    except BaseException:
        log.warning("risk detection stopped after %.1fs", time.monotonic() - started)
        raise
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
