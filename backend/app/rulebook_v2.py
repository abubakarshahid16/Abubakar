"""#805 plan change 6, part A: the rulebook's version 2 tables. Behind RULEBOOK_V2_ENABLED, default off.

THE RECORD. `rulebook_rule` is one logical rule: its key outlives clause numbers, editions and readings.
`rulebook_version` is one reading of it, holding the requirement as field, comparator, value, unit; a rule with no
single figure holds none, and the table refuses one. Who it is for (`rulebook_applicability`) and when it does not
apply (`rulebook_exception`) are rows of their own, and `rulebook_provenance` is the page, verified quote hash, model
and prompt version behind it. `rulebook_approval` is a person's decision; `rulebook_event` is written by triggers.
`rulebook_snapshot` freezes the whole book once per compile, and `rulebook_run` says which snapshot a review run used.

NOTHING IS EVER REWRITTEN. Triggers refuse UPDATE and DELETE on all of it, and INSERT OR REPLACE, which would slip past
a delete trigger. A version's rows are sealed by the counts it was written with. A change appends a version, and an
approval belongs to one version: the next one is not in force until a person decides on it.

ONLY A PERSON APPROVES. No route, job or script calls `record_decision`, and the database refuses an approval whose
approver is not an active row of `users`. No rule is in force without one.

NOTHING READS THIS FOR A VERDICT. `rulebook_run` says so: used version 1, no snapshot, until a later change is approved.

A COPY ONLY. Only `ensure_schema` creates the tables; nothing at startup calls it, and it refuses a live-shaped file.
The tables grant nothing: read access stays with the grant tables (CLAUDE.md rule 5). `standard_requirements` is not
written here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from . import live_guard
from .config import settings
from .rulebook_v2_check import (
    ALTERNATIVES,
    CANNOT_TELL,
    COMPARATORS,
    DEFERS_TO,
    KINDS,
    LIMIT,
    NO_FIGURE,
    RANGE,
    Outcome,
    check_requirement,
)

APPROVE, REJECT, RETIRE = "approve", "reject", "retire"
DECISIONS = (APPROVE, REJECT, RETIRE)
KEY_TYPES = (
    "subject",
    "condition",
    "equipment_type",
    "service",
    "material_group",
    "pressure_class",
    "size_range",
)
CONTEXT_DEPENDENT = "context_dependent"
V1, V2 = 1, 2
TABLES = (
    "rulebook_rule",
    "rulebook_version",
    "rulebook_provenance",
    "rulebook_applicability",
    "rulebook_exception",
    "rulebook_approval",
    "rulebook_snapshot",
    "rulebook_snapshot_rule",
    "rulebook_run",
    "rulebook_event",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


_NO_FIGURE_KINDS = _in((ALTERNATIVES, NO_FIGURE, DEFERS_TO))
_TABLE_SQL = (
    """CREATE TABLE rulebook_rule (
        id TEXT PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, standard TEXT NOT NULL,
        created_by TEXT NOT NULL, created_at TEXT NOT NULL)""",
    f"""CREATE TABLE rulebook_version (
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES rulebook_rule(id),
        version_no INTEGER NOT NULL CHECK (version_no >= 1), supersedes_id TEXT REFERENCES rulebook_version(id),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        quote_sha256 TEXT NOT NULL CHECK (length(quote_sha256) = 64),
        kind TEXT NOT NULL CHECK (kind IN {_in(KINDS)}), field TEXT NOT NULL CHECK (length(trim(field)) > 0),
        comparator TEXT CHECK (comparator IN {_in(COMPARATORS)}), value REAL, value_low REAL, value_high REAL,
        value_text TEXT, unit TEXT, unit_dimension TEXT,
        strength TEXT, sentence_strength TEXT, context_flag TEXT,
        applicability_count INTEGER NOT NULL, exception_count INTEGER NOT NULL,
        recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        UNIQUE (rule_id, version_no),
        CHECK ((version_no = 1) = (supersedes_id IS NULL)),
        CHECK (kind <> '{LIMIT}' OR (value IS NOT NULL AND comparator IS NOT NULL AND unit IS NOT NULL
            AND value_low IS NULL AND value_high IS NULL)),
        CHECK (kind <> '{RANGE}' OR (value IS NULL AND comparator IS NULL AND unit IS NOT NULL
            AND value_low IS NOT NULL AND value_high IS NOT NULL AND value_low <= value_high)),
        CHECK (kind NOT IN {_NO_FIGURE_KINDS} OR (value IS NULL AND comparator IS NULL
            AND value_low IS NULL AND value_high IS NULL)),
        CHECK (kind <> '{ALTERNATIVES}' OR value_text IS NOT NULL))""",
    """CREATE TABLE rulebook_provenance (
        id TEXT PRIMARY KEY, rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        standard_document_id TEXT NOT NULL, edition TEXT, clause TEXT NOT NULL,
        page INTEGER NOT NULL CHECK (page >= 1), quote TEXT NOT NULL,
        quote_sha256 TEXT NOT NULL CHECK (length(quote_sha256) = 64), quote_start INTEGER, quote_end INTEGER,
        page_source TEXT, page_min_conf REAL, text_sha256 TEXT NOT NULL,
        model TEXT NOT NULL CHECK (length(model) > 0), prompt_version TEXT NOT NULL CHECK (length(prompt_version) > 0),
        batch_id TEXT, compile_run_id TEXT NOT NULL, verified_at TEXT NOT NULL,
        UNIQUE (rule_version_id, standard_document_id, page, text_sha256, prompt_version))""",
    f"""CREATE TABLE rulebook_applicability (
        id TEXT PRIMARY KEY, rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        key_type TEXT NOT NULL CHECK (key_type IN {_in(KEY_TYPES)}), value TEXT NOT NULL CHECK (length(trim(value)) > 0),
        on_page INTEGER, provenance_id TEXT NOT NULL REFERENCES rulebook_provenance(id))""",
    """CREATE TABLE rulebook_exception (
        id TEXT PRIMARY KEY, rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        condition_text TEXT NOT NULL CHECK (length(trim(condition_text)) > 0), structured_json TEXT,
        provenance_id TEXT NOT NULL REFERENCES rulebook_provenance(id))""",
    f"""CREATE TABLE rulebook_approval (
        id TEXT PRIMARY KEY, rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        decision TEXT NOT NULL CHECK (decision IN {_in(DECISIONS)}), approver_id TEXT NOT NULL,
        decided_at TEXT NOT NULL, note TEXT, provenance_viewed TEXT NOT NULL)""",
    """CREATE TABLE rulebook_snapshot (
        id TEXT PRIMARY KEY, compile_run_id TEXT NOT NULL UNIQUE, standard_document_id TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
        rules_total INTEGER NOT NULL, rules_in_force INTEGER NOT NULL, counts_json TEXT NOT NULL,
        created_by TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE rulebook_snapshot_rule (
        snapshot_id TEXT NOT NULL REFERENCES rulebook_snapshot(id),
        rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        approval_id TEXT REFERENCES rulebook_approval(id),
        PRIMARY KEY (snapshot_id, rule_version_id))""",
    f"""CREATE TABLE rulebook_run (
        review_run_id TEXT PRIMARY KEY, used_version INTEGER NOT NULL,
        snapshot_id TEXT REFERENCES rulebook_snapshot(id), latest_snapshot_id TEXT REFERENCES rulebook_snapshot(id),
        recorded_at TEXT NOT NULL,
        CHECK ((used_version = {V1} AND snapshot_id IS NULL) OR (used_version = {V2} AND snapshot_id IS NOT NULL)))""",
    """CREATE TABLE rulebook_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL, event_type TEXT NOT NULL,
        actor TEXT NOT NULL, at TEXT NOT NULL, detail_json TEXT NOT NULL)""",
    "CREATE INDEX idx_rulebook_version_rule ON rulebook_version(rule_id, version_no)",
    "CREATE INDEX idx_rulebook_provenance_doc ON rulebook_provenance(standard_document_id)",
    "CREATE INDEX idx_rulebook_provenance_version ON rulebook_provenance(rule_version_id)",
    "CREATE INDEX idx_rulebook_applicability_version ON rulebook_applicability(rule_version_id)",
    "CREATE INDEX idx_rulebook_exception_version ON rulebook_exception(rule_version_id)",
    "CREATE INDEX idx_rulebook_approval_version ON rulebook_approval(rule_version_id)",
)
#: What each table's rows are unique by: INSERT OR REPLACE on any of these would erase a row without a delete trigger.
_UNIQUE_BY = {
    "rulebook_rule": ("id", "rule_key"),
    "rulebook_version": ("id", "rule_id, version_no"),
    "rulebook_provenance": (
        "id",
        "rule_version_id, standard_document_id, page, text_sha256, prompt_version",
    ),
    "rulebook_applicability": ("id",),
    "rulebook_exception": ("id",),
    "rulebook_approval": ("id",),
    "rulebook_snapshot": ("id", "compile_run_id"),
    "rulebook_snapshot_rule": ("snapshot_id, rule_version_id",),
    "rulebook_run": ("review_run_id",),
    "rulebook_event": ("id",),
}
_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"
_VERSION_ACTOR = (
    "(SELECT recorded_by FROM rulebook_version WHERE id = NEW.rule_version_id)"
)
#: table -> (id column, who, what the diary keeps). A snapshot's member rows are held by the snapshot's hash.
_EVENTS = {
    "rulebook_rule": ("id", "NEW.created_by", "'rule_key', NEW.rule_key"),
    "rulebook_version": (
        "id",
        "NEW.recorded_by",
        "'rule_id', NEW.rule_id, 'version_no', NEW.version_no, 'content_hash', NEW.content_hash,"
        " 'supersedes_id', NEW.supersedes_id",
    ),
    "rulebook_provenance": (
        "id",
        "NEW.model",
        "'rule_version_id', NEW.rule_version_id, 'quote_sha256', NEW.quote_sha256, 'page', NEW.page,"
        " 'prompt_version', NEW.prompt_version",
    ),
    "rulebook_applicability": (
        "id",
        _VERSION_ACTOR,
        "'rule_version_id', NEW.rule_version_id, 'key_type', NEW.key_type",
    ),
    "rulebook_exception": (
        "id",
        _VERSION_ACTOR,
        "'rule_version_id', NEW.rule_version_id",
    ),
    "rulebook_approval": (
        "id",
        "NEW.approver_id",
        "'rule_version_id', NEW.rule_version_id, 'decision', NEW.decision",
    ),
    "rulebook_snapshot": (
        "id",
        "NEW.created_by",
        "'snapshot_hash', NEW.snapshot_hash, 'rules_total', NEW.rules_total, 'rules_in_force', NEW.rules_in_force",
    ),
    "rulebook_run": (
        "review_run_id",
        "'review_run'",
        "'used_version', NEW.used_version, 'snapshot_id', NEW.snapshot_id",
    ),
}
_GUARDS = (
    # A version's rows are sealed by the counts it was written with.
    """CREATE TRIGGER rulebook_applicability_sealed BEFORE INSERT ON rulebook_applicability
       WHEN (SELECT COUNT(*) FROM rulebook_applicability WHERE rule_version_id = NEW.rule_version_id)
            >= (SELECT applicability_count FROM rulebook_version WHERE id = NEW.rule_version_id)
       BEGIN SELECT RAISE(ABORT, 'rulebook: this version is sealed; append a version'); END""",
    """CREATE TRIGGER rulebook_exception_sealed BEFORE INSERT ON rulebook_exception
       WHEN (SELECT COUNT(*) FROM rulebook_exception WHERE rule_version_id = NEW.rule_version_id)
            >= (SELECT exception_count FROM rulebook_version WHERE id = NEW.rule_version_id)
       BEGIN SELECT RAISE(ABORT, 'rulebook: this version is sealed; append a version'); END""",
    # Another sentence is another reading. An edition may only link the same sentence.
    """CREATE TRIGGER rulebook_provenance_same_quote BEFORE INSERT ON rulebook_provenance
       WHEN NEW.quote_sha256 <> (SELECT quote_sha256 FROM rulebook_version WHERE id = NEW.rule_version_id)
       BEGIN SELECT RAISE(ABORT, 'rulebook: another quote needs a new version'); END""",
    # A decision is a person's, on the current reading.
    """CREATE TRIGGER rulebook_approval_a_person BEFORE INSERT ON rulebook_approval
       WHEN NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.approver_id AND is_active = 1)
       BEGIN SELECT RAISE(ABORT, 'rulebook: only an active person decides on a rule'); END""",
    """CREATE TRIGGER rulebook_approval_current BEFORE INSERT ON rulebook_approval
       WHEN EXISTS (SELECT 1 FROM rulebook_version old JOIN rulebook_version later
                    ON later.rule_id = old.rule_id AND later.version_no > old.version_no
                    WHERE old.id = NEW.rule_version_id)
       BEGIN SELECT RAISE(ABORT, 'rulebook: a superseded version cannot be decided on'); END""",
    f"""CREATE TRIGGER rulebook_approval_proof BEFORE INSERT ON rulebook_approval
       WHEN NEW.decision = '{APPROVE}' AND (
            json_array_length(NEW.provenance_viewed) < 1
            OR NOT EXISTS (SELECT 1 FROM rulebook_provenance WHERE rule_version_id = NEW.rule_version_id))
       BEGIN SELECT RAISE(ABORT, 'rulebook: an approval needs a quote that was read'); END""",
    f"""CREATE TRIGGER rulebook_approval_context BEFORE INSERT ON rulebook_approval
       WHEN NEW.decision = '{APPROVE}' AND length(trim(COALESCE(NEW.note, ''))) = 0
            AND (SELECT strength FROM rulebook_version WHERE id = NEW.rule_version_id) = '{CONTEXT_DEPENDENT}'
       BEGIN SELECT RAISE(ABORT, 'rulebook: a rule whose scope sits outside its sentence needs a note'); END""",
)


def _trigger_sql() -> list[str]:
    out = list(_GUARDS)
    for table in TABLES:
        for verb in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table}"
                f" BEGIN SELECT RAISE(ABORT, 'rulebook: {table} is append-only'); END"
            )
        for n, columns in enumerate(_UNIQUE_BY[table]):
            same = " AND ".join(f"t.{c} = NEW.{c}" for c in columns.split(", "))
            out.append(
                f"CREATE TRIGGER {table}_no_replace_{n} BEFORE INSERT ON {table}"
                f" WHEN EXISTS (SELECT 1 FROM {table} t WHERE {same})"
                f" BEGIN SELECT RAISE(ABORT, 'rulebook: {table} is never replaced'); END"
            )
    for table, (key, actor, detail) in _EVENTS.items():
        out.append(
            f"CREATE TRIGGER {table}_event AFTER INSERT ON {table} BEGIN"
            f" INSERT INTO rulebook_event (entity, entity_id, event_type, actor, at, detail_json)"
            f" VALUES ('{table}', NEW.{key}, 'insert', {actor}, {_NOW_SQL}, json_object({detail})); END"
        )
    return out


SCHEMA = (*_TABLE_SQL, *_trigger_sql())


class SwitchedOff(RuntimeError):
    """RULEBOOK_V2_ENABLED is off, so nothing was read or written."""


class RefusedLive(RuntimeError):
    """This file is shaped like a live database; version 2 tables go on a copy."""


class RuleRefused(ValueError):
    """A decision this module will not record. Says why, never in document words."""


def require_on() -> None:
    if not settings.rulebook_v2_enabled:
        raise SwitchedOff("RULEBOOK_V2_ENABLED is off; nothing was read or written")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def has_schema(conn) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'rulebook_event'"
    ).fetchone()
    return row[0] == 1


def ensure_schema(conn) -> None:
    """Create the tables, once, all or none, on a copy. Run twice it does nothing; no other table is touched."""
    require_on()
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise RefusedLive("this is a live-shaped database; run on a copy")
    if has_schema(conn):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in SCHEMA:
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


# ------------------------------------------------------------------------------------------------ appending


@dataclass(frozen=True)
class Reading:
    """One reading of one rule, ready to append."""

    rule_key: str
    standard: str
    requirement: Mapping
    strength: str | None
    sentence_strength: str | None
    context_flag: str | None
    applicability: tuple[tuple[str, str, int | None], ...]
    exceptions: tuple[str, ...]
    provenance: Mapping


_REQUIREMENT_FIELDS = (
    "kind",
    "field",
    "comparator",
    "value",
    "value_low",
    "value_high",
    "value_text",
    "unit",
    "unit_dimension",
)


def content_hash_of(
    requirement: Mapping,
    strength,
    sentence_strength,
    context_flag,
    applicability,
    exceptions,
    quote_sha256: str,
) -> str:
    """The same reading hashes the same: re-running on unchanged text makes no new version."""
    body = {
        "requirement": {k: requirement.get(k) for k in _REQUIREMENT_FIELDS},
        "strength": [strength, sentence_strength, context_flag],
        "applicability": sorted([kind, value] for kind, value, *_ in applicability),
        "exceptions": sorted(exceptions),
        "quote": quote_sha256,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def _content_hash(reading: Reading) -> str:
    return content_hash_of(
        reading.requirement,
        reading.strength,
        reading.sentence_strength,
        reading.context_flag,
        reading.applicability,
        reading.exceptions,
        reading.provenance["quote_sha256"],
    )


def _insert_provenance(conn, version_id: str, source: Mapping) -> str:
    provenance_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO rulebook_provenance (id, rule_version_id, standard_document_id, edition, clause, page, quote,"
        " quote_sha256, quote_start, quote_end, page_source, page_min_conf, text_sha256, model, prompt_version,"
        " batch_id, compile_run_id, verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            provenance_id,
            version_id,
            source["standard_document_id"],
            source["edition"],
            source["clause"],
            source["page"],
            source["quote"],
            source["quote_sha256"],
            source["quote_start"],
            source["quote_end"],
            source["page_source"],
            source["page_min_conf"],
            source["text_sha256"],
            source["model"],
            source["prompt_version"],
            source["batch_id"],
            source["compile_run_id"],
            _now(),
        ),
    )
    return provenance_id


def _insert_version(conn, reading: Reading, rule_id, number, previous, actor) -> str:
    version_id, need = uuid.uuid4().hex, reading.requirement
    conn.execute(
        "INSERT INTO rulebook_version (id, rule_id, version_no, supersedes_id, content_hash, quote_sha256, kind, field,"
        " comparator, value, value_low, value_high, value_text, unit, unit_dimension, strength, sentence_strength,"
        " context_flag, applicability_count, exception_count, recorded_by, recorded_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            version_id,
            rule_id,
            number,
            previous,
            _content_hash(reading),
            reading.provenance["quote_sha256"],
            need["kind"],
            need["field"],
            need.get("comparator"),
            need.get("value"),
            need.get("value_low"),
            need.get("value_high"),
            need.get("value_text"),
            need.get("unit"),
            need.get("unit_dimension"),
            reading.strength,
            reading.sentence_strength,
            reading.context_flag,
            len(reading.applicability),
            len(reading.exceptions),
            actor,
            _now(),
        ),
    )
    provenance_id = _insert_provenance(conn, version_id, reading.provenance)
    for key_type, value, on_page in reading.applicability:
        conn.execute(
            "INSERT INTO rulebook_applicability (id, rule_version_id, key_type, value, on_page, provenance_id)"
            " VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, version_id, key_type, value, on_page, provenance_id),
        )
    for words in reading.exceptions:
        conn.execute(
            "INSERT INTO rulebook_exception (id, rule_version_id, condition_text, provenance_id) VALUES (?,?,?,?)",
            (uuid.uuid4().hex, version_id, words, provenance_id),
        )
    return version_id


def append_reading(conn, reading: Reading, actor: str) -> str:
    """Write one reading inside the caller's transaction. Returns what happened: new_rule, new_version (the change
    waits for a person), new_source (the same reading on another text or edition) or unchanged."""
    rule = conn.execute(
        "SELECT id FROM rulebook_rule WHERE rule_key = ?", (reading.rule_key,)
    ).fetchone()
    if rule is None:
        rule_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO rulebook_rule (id, rule_key, standard, created_by, created_at) VALUES (?,?,?,?,?)",
            (rule_id, reading.rule_key, reading.standard, actor, _now()),
        )
        _insert_version(conn, reading, rule_id, 1, None, actor)
        return "new_rule"
    latest = conn.execute(
        "SELECT id, version_no, content_hash FROM rulebook_version WHERE rule_id = ?"
        " ORDER BY version_no DESC LIMIT 1",
        (rule[0],),
    ).fetchone()
    if latest[2] != _content_hash(reading):
        _insert_version(conn, reading, rule[0], latest[1] + 1, latest[0], actor)
        return "new_version"
    source = reading.provenance
    known = conn.execute(
        "SELECT 1 FROM rulebook_provenance WHERE rule_version_id = ? AND standard_document_id = ? AND page = ?"
        " AND text_sha256 = ? AND prompt_version = ?",
        (
            latest[0],
            source["standard_document_id"],
            source["page"],
            source["text_sha256"],
            source["prompt_version"],
        ),
    ).fetchone()
    if known:
        return "unchanged"
    _insert_provenance(conn, latest[0], source)
    return "new_source"


# --------------------------------------------------------------------------------------- a person's decision


def approval_in_force(conn, version_id: str) -> str | None:
    """The approval this version stands on: its LAST decision, and only if that is an approval."""
    row = conn.execute(
        "SELECT id, decision FROM rulebook_approval WHERE rule_version_id = ? ORDER BY rowid DESC LIMIT 1",
        (version_id,),
    ).fetchone()
    return row[0] if row is not None and row[1] == APPROVE else None


def record_decision(
    conn,
    version_id: str,
    *,
    decision: str,
    engineer_id: str,
    provenance_viewed: tuple[str, ...] = (),
    note: str | None = None,
) -> str:
    """One person's decision on one version. Nothing in the app calls this yet; a test holds that."""
    require_on()
    if decision == APPROVE:
        held = {
            r[0]
            for r in conn.execute(
                "SELECT id FROM rulebook_provenance WHERE rule_version_id = ?",
                (version_id,),
            )
        }
        if not provenance_viewed or not set(provenance_viewed) <= held:
            raise RuleRefused(
                "an approval names the quotes of this version that were read"
            )
    approval_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO rulebook_approval (id, rule_version_id, decision, approver_id, decided_at, note,"
            " provenance_viewed) VALUES (?,?,?,?,?,?,?)",
            (
                approval_id,
                version_id,
                decision,
                engineer_id,
                _now(),
                note,
                json.dumps(sorted(provenance_viewed)),
            ),
        )
    return approval_id


# ------------------------------------------------------------------------------------------------ snapshots


def _current_versions(conn) -> list:
    return conn.execute(
        "SELECT v.id, v.version_no, v.content_hash, r.rule_key FROM rulebook_version v"
        " JOIN rulebook_rule r ON r.id = v.rule_id"
        " WHERE v.version_no = (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
        " ORDER BY r.rule_key"
    ).fetchall()


def take_snapshot(
    conn, compile_run_id: str, document_id: str, counts: Mapping, actor: str
) -> str:
    """The whole book as it stands, once per compile, inside the caller's transaction. Each member names the approval
    it stood on then, or none: a member with none is held, not in force, whatever is decided later."""
    found = conn.execute(
        "SELECT id FROM rulebook_snapshot WHERE compile_run_id = ?", (compile_run_id,)
    ).fetchone()
    if found:
        return found[0]
    members = [
        (row, approval_in_force(conn, row[0])) for row in _current_versions(conn)
    ]
    digest = hashlib.sha256(
        json.dumps([[r[3], r[1], r[2], a or ""] for r, a in members]).encode("utf-8")
    ).hexdigest()
    snapshot_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO rulebook_snapshot (id, compile_run_id, standard_document_id, snapshot_hash, rules_total,"
        " rules_in_force, counts_json, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            compile_run_id,
            document_id,
            digest,
            len(members),
            sum(1 for _r, a in members if a),
            json.dumps(counts, sort_keys=True),
            actor,
            _now(),
        ),
    )
    conn.executemany(
        "INSERT INTO rulebook_snapshot_rule (snapshot_id, rule_version_id, approval_id) VALUES (?,?,?)",
        [(snapshot_id, r[0], a) for r, a in members],
    )
    return snapshot_id


def in_force(conn, snapshot_id: str) -> list[str]:
    """The versions a run on this snapshot may use: approved when it was taken. Nothing else, ever."""
    return [
        r[0]
        for r in conn.execute(
            "SELECT rule_version_id FROM rulebook_snapshot_rule WHERE snapshot_id = ? AND approval_id IS NOT NULL"
            " ORDER BY rule_version_id",
            (snapshot_id,),
        )
    ]


def record_run(
    conn, review_run_id: str, used_snapshot_id: str | None = None
) -> dict | None:
    """The run says which rulebook it used. Verdicts read version 1 today, so: version 1, no snapshot, and the newest
    snapshot named apart as not used. Off, or tables not created (a live database): nothing, and nothing is created.
    A run's record is written once."""
    if not settings.rulebook_v2_enabled or not has_schema(conn):
        return None
    done = conn.execute(
        "SELECT used_version, snapshot_id, latest_snapshot_id FROM rulebook_run WHERE review_run_id = ?",
        (review_run_id,),
    ).fetchone()
    if done is None:
        newest = conn.execute(
            "SELECT id FROM rulebook_snapshot ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        done = (
            V2 if used_snapshot_id else V1,
            used_snapshot_id,
            newest[0] if newest else None,
        )
        with conn:
            conn.execute(
                "INSERT INTO rulebook_run (review_run_id, used_version, snapshot_id, latest_snapshot_id, recorded_at)"
                " VALUES (?,?,?,?,?)",
                (review_run_id, *done, _now()),
            )
    return {
        "used_version": done[0],
        "snapshot_id": done[1],
        "latest_snapshot_id": done[2],
    }


# ------------------------------------------------------------------------------------------------ one check


def check_version(
    conn,
    version_id: str,
    value: object,
    unit: str | None = None,
    *,
    applies: Mapping[str, bool] | None = None,
    excepted: Mapping[str, bool] | None = None,
) -> Outcome:
    """One rule's outcome, in the order a rule is read: approved, who it is for, unless, what it demands. `applies`
    and `excepted` answer by row id; a row with no answer is unknown, so "cannot tell". A rule found not to bind has no
    outcome (`outcome` None) and says why. No verdict code calls this; a test holds that."""
    require_on()
    if approval_in_force(conn, version_id) is None:
        return Outcome(CANNOT_TELL, "not_approved")
    rows = conn.execute(
        "SELECT id FROM rulebook_applicability WHERE rule_version_id = ?", (version_id,)
    ).fetchall()
    answers = [(applies or {}).get(r[0]) for r in rows]
    if False in answers:
        return Outcome(None, "does_not_apply")
    if None in answers:
        return Outcome(CANNOT_TELL, "applicability_unknown")
    rows = conn.execute(
        "SELECT id FROM rulebook_exception WHERE rule_version_id = ?", (version_id,)
    ).fetchall()
    answers = [(excepted or {}).get(r[0]) for r in rows]
    if True in answers:
        return Outcome(None, "excepted")
    if None in answers:
        return Outcome(CANNOT_TELL, "exception_unknown")
    names = ("kind", "comparator", "value", "value_low", "value_high", "unit")
    row = conn.execute(
        f"SELECT {', '.join(names)} FROM rulebook_version WHERE id = ?", (version_id,)
    ).fetchone()
    return check_requirement(dict(zip(names, row, strict=True)), value, unit)


# ------------------------------------------------------------------------------------------------- the checks


#: SQL that must return zero: what the tables' own constraints cannot hold.
_ZERO_ROWS = {
    "version_without_provenance": "SELECT v.id FROM rulebook_version v WHERE NOT EXISTS"
    " (SELECT 1 FROM rulebook_provenance p WHERE p.rule_version_id = v.id)",
    "version_short_of_applicability": "SELECT v.id FROM rulebook_version v WHERE v.applicability_count <>"
    " (SELECT COUNT(*) FROM rulebook_applicability a WHERE a.rule_version_id = v.id)",
    "version_short_of_exceptions": "SELECT v.id FROM rulebook_version v WHERE v.exception_count <>"
    " (SELECT COUNT(*) FROM rulebook_exception e WHERE e.rule_version_id = v.id)",
    "snapshot_member_unapproved": "SELECT s.rule_version_id FROM rulebook_snapshot_rule s JOIN rulebook_approval a"
    f" ON a.id = s.approval_id WHERE a.decision <> '{APPROVE}' OR a.rule_version_id <> s.rule_version_id",
    "version_without_event": "SELECT v.id FROM rulebook_version v WHERE NOT EXISTS (SELECT 1 FROM rulebook_event e"
    " WHERE e.entity = 'rulebook_version' AND e.entity_id = v.id)",
}


def integrity_problems(conn) -> dict[str, int]:
    """{check: rows that break it}; empty when the book holds. Counts only. A dropped trigger is one of them."""
    out = {
        name: count
        for name, sql in _ZERO_ROWS.items()
        if (count := len(conn.execute(sql).fetchall()))
    }
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }
    wanted = {statement.split()[2] for statement in _trigger_sql()}
    if wanted - held:
        out["trigger_missing"] = len(wanted - held)
    return out
