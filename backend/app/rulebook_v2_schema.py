"""#805 plan change 6, part A: the rulebook's version 2 schema: its tables, its guards, the words they allow.

Statements only; `rulebook_v2.ensure_schema` runs what a copy is missing. What the guards mean is in `rulebook_v2`.
"""

from __future__ import annotations

from .rulebook_v2_check import (
    ALTERNATIVES,
    COMPARATORS,
    DEFERS_TO,
    KINDS,
    LIMIT,
    NO_FIGURE,
    RANGE,
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
OWNER, ENGINEER = "owner", "engineer"
TIERS = (OWNER, ENGINEER)
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
    "rulebook_restore",
    "rulebook_compiled_row",
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
    # STEP 5: a restore of an earlier book version, or the release of one. Append-only like the rest.
    """CREATE TABLE rulebook_restore (
        id TEXT PRIMARY KEY, action TEXT NOT NULL CHECK (action IN ('restore', 'release')),
        snapshot_id TEXT REFERENCES rulebook_snapshot(id), source_snapshot_id TEXT REFERENCES rulebook_snapshot(id),
        book_no INTEGER, restored_book_no INTEGER, source_hash TEXT,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0), actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        at TEXT NOT NULL, CHECK ((action = 'restore') = (snapshot_id IS NOT NULL)))""",
    """CREATE TABLE rulebook_snapshot_rule (
        snapshot_id TEXT NOT NULL REFERENCES rulebook_snapshot(id),
        rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        approval_id TEXT REFERENCES rulebook_approval(id),
        PRIMARY KEY (snapshot_id, rule_version_id))""",
    # Which version a compile's row became. A checklist file carries this; a re-proof makes a new compile, so new rows.
    """CREATE TABLE rulebook_compiled_row (
        compile_run_id TEXT NOT NULL, compiled_row_id TEXT NOT NULL,
        rule_version_id TEXT NOT NULL REFERENCES rulebook_version(id),
        PRIMARY KEY (compile_run_id, compiled_row_id))""",
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
    # Columns added after the first copies had the table: on those copies only the ALTER runs.
    f"ALTER TABLE rulebook_approval ADD COLUMN tier TEXT CHECK (tier IN {_in(TIERS)})",
    "ALTER TABLE rulebook_approval ADD COLUMN equipment_type TEXT",
    "ALTER TABLE rulebook_approval ADD COLUMN approver_name TEXT",
    "ALTER TABLE rulebook_approval ADD COLUMN source_sha256 TEXT",
    "ALTER TABLE rulebook_approval ADD COLUMN signed_content TEXT",
    "ALTER TABLE rulebook_snapshot ADD COLUMN standard TEXT",
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
    "rulebook_restore": ("id",),
    "rulebook_compiled_row": ("compile_run_id, compiled_row_id",),
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
        "'rule_version_id', NEW.rule_version_id, 'decision', NEW.decision, 'tier', NEW.tier,"
        " 'equipment_type', NEW.equipment_type, 'source_sha256', NEW.source_sha256",
    ),
    "rulebook_snapshot": (
        "id",
        "NEW.created_by",
        "'snapshot_hash', NEW.snapshot_hash, 'rules_total', NEW.rules_total, 'rules_in_force', NEW.rules_in_force",
    ),
    "rulebook_restore": (
        "id",
        "NEW.actor",
        "'action', NEW.action, 'restored_book_no', NEW.restored_book_no, 'source_hash', NEW.source_hash",
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
    # A decision is a person's, on the current reading, and says in what capacity and for what.
    f"""CREATE TRIGGER rulebook_approval_signed BEFORE INSERT ON rulebook_approval
       WHEN NEW.tier IS NULL OR (NEW.decision = '{APPROVE}' AND length(trim(COALESCE(NEW.equipment_type, ''))) = 0)
       BEGIN SELECT RAISE(ABORT, 'rulebook: a decision names its tier, and an approval its equipment type'); END""",
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


def trigger_sql() -> list[str]:
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


SCHEMA = (*_TABLE_SQL, *trigger_sql())


# Reads for `run_record`'s counts, through `compiled_rule_report`.


def _table_exists(conn, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return found is not None


def run_used(conn, review_run_id: str) -> tuple[int, str | None] | None:
    """(version, snapshot hash) a run recorded, for `run_record`. None: no table, or no record. Reads only."""
    if not _table_exists(conn, "rulebook_run"):
        return None
    row = conn.execute(
        "SELECT used_version, snapshot_id FROM rulebook_run WHERE review_run_id = ?",
        (review_run_id,),
    ).fetchone()
    if row is None:
        return None
    found = conn.execute(
        "SELECT snapshot_hash FROM rulebook_snapshot WHERE id = ?", (row[1],)
    ).fetchone()
    return row[0], found[0] if found else None


def decisions_on(conn, documents: list[str]) -> list[tuple[str, str, str]]:
    """(decision id, decision, standard document) for a rule read in one of `documents`, for `run_record`'s counts. A
    rule read in two gives two rows. No table: nothing. Reads only; nothing here decides."""
    if not documents or not _table_exists(conn, "rulebook_approval"):
        return []
    marks = ",".join("?" for _ in documents)
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT a.id, a.decision, p.standard_document_id FROM rulebook_approval a"
            " JOIN rulebook_provenance p ON p.rule_version_id = a.rule_version_id"
            f" WHERE p.standard_document_id IN ({marks})",
            documents,
        )
    ]
