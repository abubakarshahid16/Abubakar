"""Persistent workflow records for AI-assisted engineering reviews.

Analysis remains evidence-first and read-only. A review finding is the
workflow record created from that evidence and then managed by people.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from .db import add_column_if_missing, connect, schema_once
from .config import settings


#: A FINDING NO ENGINEER HAS DECIDED - the only kind a re-run may delete.
#:
#: Audit 2026-09-30: every re-run path deleted `confirmed_by IS NULL`, and an
#: engineer's rejection or acceptance is written to `approval_status` /
#: `approved_by`, not `confirmed_by`. So a rejected comment was deleted by the
#: next run and came back as a fresh draft, and the rejection was lost. Any
#: human act on a finding - confirmation, approval decision, disposition or
#: re-worded comment - now keeps it. Used by every path that clears a run's
#: machine rows (`comparison._write_run_findings`, `review_jobs` cancel,
#: `ai_engineering_check`, `web_standards`).
UNDECIDED_SQL = ("(confirmed_by IS NULL AND approved_by IS NULL"
                 " AND COALESCE(approval_status, 'pending') = 'pending'"
                 " AND disposition IS NULL AND engineer_comment IS NULL)")


def rejected_in_run(review_run_id: str, origin: str | None = None) -> list[dict]:
    """The findings of one run an engineer REJECTED (optionally of one origin).

    A re-run keeps them (`UNDECIDED_SQL`) and must not propose the same comment
    again beside them - that is the rejected comment returning as a new draft.
    Each caller compares on its own identity of "the same comment"."""
    ensure_schema()
    sql = ("SELECT * FROM review_findings WHERE review_run_id = ?"
           " AND approval_status = 'rejected'")
    args: list = [review_run_id]
    if origin is not None:
        sql += " AND origin = ?"
        args.append(origin)
    return [dict(r) for r in connect().execute(sql, args)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


#: The same stamp the API layer writes on a confirmation, so a finding's
#: timestamps all come from one place and read alike.
now_iso = _now


@schema_once
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
                updated_at TEXT NOT NULL,
                -- ------------------------------- AI submittal review, phase 1
                -- A SECOND vocabulary beside `status`/`disposition`, never a
                -- reuse of them. `status` ('open'...) is where a finding is in
                -- the guided-review workflow and `disposition` is what a human
                -- decided about it; existing rows depend on both and existing
                -- code reads both. `compliance_status` answers a different
                -- question - does the submittal MEET the standard - and
                -- overloading either column would have made the two answers
                -- indistinguishable on every row written before today.
                --
                -- Plain TEXT, no CHECK, for the reason document_classification
                -- gives: the six legal values live in `schemas.ComplianceStatus`.
                review_run_id TEXT,
                compliance_status TEXT,
                contractor_page INTEGER,
                contractor_section TEXT,
                contractor_evidence_text TEXT,
                -- NO FOREIGN KEY, the report_documents precedent: deleting a
                -- standard must not erase the finding that cited it. The
                -- finding is the record that the citation was made.
                standard_document_id TEXT,
                standard_clause TEXT,
                standard_page INTEGER,
                requirement_source_text TEXT,
                ai_rationale TEXT
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
            # AI submittal review, phase 1. Nullable with no default: an
            # existing finding was written by the guided-review workflow and
            # has no compliance verdict, and NULL says exactly that. A default
            # of 'COMPLIANT' would be the "not mentioned is never compliant"
            # honesty invariant broken in a migration.
            "review_run_id": "TEXT",
            "compliance_status": "TEXT",
            "contractor_page": "INTEGER",
            "contractor_section": "TEXT",
            "contractor_evidence_text": "TEXT",
            "standard_document_id": "TEXT",
            "standard_clause": "TEXT",
            "standard_page": "INTEGER",
            "requirement_source_text": "TEXT",
            "ai_rationale": "TEXT",
            # HOW THE REQUIREMENT AND THE VALUE WERE PAIRED, on the finding
            # itself. A finding says a contractor's number does or does not
            # meet a clause; if the pairing was wrong, the finding is wrong,
            # and a reader has to be able to see WHICH field was matched and by
            # WHAT RULE without re-running anything.
            #
            # `unresolved_evidence` already exists for a citation that does not
            # resolve; this is the sibling fact for a match that did.
            "requirement_id": "TEXT",
            "fact_id": "TEXT",
            "matched_phrase": "TEXT",
            "match_method": "TEXT",
            # A HUMAN'S DECISION ABOUT THIS FINDING, and the reason re-running
            # a comparison cannot destroy it.
            #
            # `run_comparison(replace=True)` deletes the run's findings before
            # writing new ones, and every fix to the engine reaches the corpus
            # BY re-running it. Without this an engineer's confirmation would
            # last exactly until the next maintenance action, silently. The
            # same rule `standard_requirements` already follows.
            #
            # No REFERENCES clause: SQLite cannot add a foreign key by ALTER,
            # so a migrated database has none to lean on. `standard_requirements.
            # confirmed_by` carries the same note.
            # WHICH EQUIPMENT THIS FINDING IS ABOUT, copied from the fact.
            # NULL where the datasheet does not say, and NULL renders as
            # nothing - never as a guess at which valve was meant.
            "equipment_tag": "TEXT",
            "confirmed_by": "TEXT",
            "confirmed_at": "TEXT",
            # WHERE THE FINDING CAME FROM when it was not the comparison:
            # 'chat' is an engineer's comment filed from the Chat screen
            # (chat_actions.file_comment). NULL for everything else, so every
            # existing row reads exactly as before.
            "origin": "TEXT",
            # Owner order section 3: THE ENGINEER'S WORDING of the comment,
            # when they edited it. NULL means the comment is printed as the
            # review wrote it. The machine's own text (finding, rationale) is
            # never overwritten, so both stay on record.
            "engineer_comment": "TEXT",
        }.items():
            # RACE-SAFE, because this runs on read paths. See
            # `db.add_column_if_missing`.
            add_column_if_missing(conn, "review_findings", name, definition)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_document "
                     "ON review_findings(document_id, status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_due "
                     "ON review_findings(due_date, status)")
        # Created here rather than in the CREATE TABLE above, because on a
        # database written by an earlier build the column does not exist until
        # the ALTER block above has run.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_run "
                     "ON review_findings(review_run_id, compliance_status, "
                     "updated_at DESC)")
        # THE DUPLICATE GATE'S INDEX. `comparison.create_finding` asks for an
        # unconfirmed finding with this run AND this requirement; with only
        # the index above, SQLite read every earlier finding of the run to
        # answer, so writing a run of N findings cost O(N^2) row reads.
        # Idempotent, so an existing database gains it on the next start.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_run_requirement "
                     "ON review_findings(review_run_id, requirement_id)")
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


#: What a finding says where the standard it was decided against is one the
#: caller holds no grant for (r2 security S2, CLAUDE.md rule 5). The verdict
#: (compliance_status, severity, category, status) stays; everything that
#: quotes or names the standard goes.
STANDARD_WITHHELD = "standard not available to you"

_STANDARD_NULLED = ("standard_document_id", "standard_clause", "standard_page",
                    "requirement_source_text", "requirement_id", "matched_phrase",
                    "standard_name")
_STANDARD_LABELLED = ("requirement", "finding", "ai_rationale")
_STANDARD_EMPTIED = ("governing_sources", "citation_ids", "unresolved_evidence")


def withhold_unreadable_standards(
        findings: list[dict],
        allowed_document_ids: frozenset[str] | None) -> list[dict]:
    """Withhold the standard-derived fields of every finding whose STANDARD the
    caller may not read. In place; returns the same list.

    A grant on the SUBMITTAL is not a grant on the standard it was compared
    against: the finding row carries the clause, page, requirement wording and
    the standard's id, and reading the submittal's findings must not become a
    way to read the standard. This only ever REMOVES - it is an intersection
    with the caller's grants, never a union.

    A standard that no longer exists as a document is left alone: the finding
    is the record that the citation was made, and there is no grant to test.
    `allowed_document_ids=None` means the caller asked for no scoping at all.
    """
    if allowed_document_ids is None:
        return findings
    candidates = {f.get("standard_document_id") for f in findings
                  if f.get("standard_document_id")
                  and f["standard_document_id"] not in allowed_document_ids}
    if not candidates:
        return findings
    marks = ",".join("?" for _ in candidates)
    existing = {r["id"] for r in connect().execute(
        f"SELECT id FROM documents WHERE id IN ({marks})", sorted(candidates))}
    for f in findings:
        if f.get("standard_document_id") not in existing:
            continue
        for key in _STANDARD_NULLED:
            if key in f:
                f[key] = None
        for key in _STANDARD_LABELLED:
            if key in f:
                f[key] = STANDARD_WITHHELD
        for key in _STANDARD_EMPTIED:
            if key in f:
                f[key] = []
        f["standard_withheld"] = True
    return findings


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
    events = []
    for item in connect().execute(
        "SELECT * FROM review_finding_events WHERE finding_id=? ORDER BY created_at", (finding_id,)
    ).fetchall():
        event = dict(item)
        try:
            event["changes"] = json.loads(event.get("changes") or "{}")
        except (TypeError, ValueError):
            event["changes"] = {}
        events.append(event)
    deliverables = [item for item in deliverables_mod.list_items(
        allowed_document_ids=frozenset({row["document_id"]})
    ) if item.get("document_id") == row["document_id"]]
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
    finding = _row(row)
    if allowed_document_ids is not None:
        withhold_unreadable_standards([finding], allowed_document_ids)
    return {"finding": finding, "document": {"id": row["document_id"], "filename": row["filename"]},
            "baseline": ({"filename": row["baseline_filename"]} if row["baseline_filename"] else None),
            "citations": finding["citation_ids"], "events": events,
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
                  review_run_id: str | None = None,
                  allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    ensure_schema()
    clauses: list[str] = []
    args: list[str] = []
    if document_id:
        clauses.append("document_id = ?")
        args.append(document_id)
    if review_run_id:
        # ONE RUN'S FINDINGS. A comparison run produces one finding per
        # requirement - 1,580 on this corpus - so without this the only way to
        # see a run's output through the API is to fetch every finding ever
        # written and filter in the client.
        #
        # FILTERED IN THE QUERY, never after it. `metrics._where` carries the
        # reason: post-filtering works until someone adds a LIMIT, and then it
        # silently returns the wrong page.
        clauses.append("review_run_id = ?")
        args.append(review_run_id)
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
    return withhold_unreadable_standards(
        [_row(row) for row in connect().execute(sql, args).fetchall()],
        allowed_document_ids)


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
               # Owner order section 3: Edit. The engineer's wording of the
               # comment; the machine's text stays as it was.
               "engineer_comment",
               "disposition", "approved_by", "approved_at",
               # NOT REACHABLE FROM A REQUEST BODY. `ReviewFindingUpdate` has
               # no `confirmed_by` field, so the only thing that can put one
               # here is the route, which sets it to the authenticated caller.
               "confirmed_by", "confirmed_at"}
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
        # An edited comment keeps its earlier wording in the audit trail:
        # the event says what the engineer changed FROM, not only to.
        detail = ({**changed, "engineer_comment_before": current.get("engineer_comment")}
                  if "engineer_comment" in changed else changed)
        _event(conn, finding_id, "updated", detail, actor_user_id, now)
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
    pdf = pymupdf.open()
    page = pdf.new_page()
    y = 48
    page.insert_text((48, y), "ENGINEERING SUBMITTAL REVIEW", fontsize=18, fontname="hebo", color=(0.07, 0.23, 0.32))
    y += 24
    page.insert_text((48, y), f"Document: {doc['filename']}", fontsize=10, fontname="helv")
    y += 15
    page.insert_text((48, y), f"Generated: {_now()}  ·  Findings: {len(findings)}", fontsize=9, fontname="helv", color=(0.3, 0.35, 0.4))
    y += 24
    page.draw_rect(pymupdf.Rect(48, y, 548, y + 34), color=(0.7, 0.32, 0.04), fill=(1, 0.97, 0.91), width=0.8)
    page.insert_textbox(pymupdf.Rect(58, y + 7, 538, y + 28),
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
        page.draw_rect(pymupdf.Rect(48, y, 548, y + height), color=(0.65, 0.72, 0.75), fill=(0.96, 0.98, 0.98), width=0.5)
        page.insert_textbox(pymupdf.Rect(58, y + 8, 538, y + height - 8), block, fontsize=8.5, fontname="helv", lineheight=1.25)
        y += height + 12
    if not findings:
        page.insert_text((48, y), "No review findings have been recorded for this document.", fontsize=10, fontname="helv")
    pdf.save(str(path))
    pdf.close()
    return path
