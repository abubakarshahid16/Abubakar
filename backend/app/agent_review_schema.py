"""The AI reviewer's tables (#1690): created only when the one switch is on, by CREATE ... IF NOT EXISTS, never an ALTER.

    agent_review_run          one row per AI review run (run id = the existing `review_runs.id`): paper kind and where it
                              came from, equipment type, USD spent (NULL until known), the models the answers named, the
                              stop reason (NULL when the run finished), counts per class, and `rule_set_changed_by`
                              (NULL: the rule set is chosen automatically; a person's change would write a name here).
    agent_review_rule         every rule of the run: asked, or left out with its ONE reason (rule book, clause, quote,
                              quote page, paper kind, field, equipment type, tier). Local only: it holds rule-book text.
    agent_review_line         one CRS line per item: class, word, page, clause, rule book, reason, tier, the stored line
                              (for resume and the xlsx) and its trace. The table itself refuses "Pass" or "Fail" on a line
                              whose class is not "Proven by code" and on a rule that is not AI approved or approved by a person.
    agent_review_missing_book a rule book the paper cites that the library does not hold (listed, never counted against).
    agent_review_general      one row per GENERAL review run (procedures and contracts, no rule book): the project papers the
                              request named, and the ones that were used (id and name). A run with no row is a rule review.

Switch off: `ensure_schema` does nothing and creates nothing; `create_tables` raises `FeatureOff`. A GET never creates a
table: `has_tables` says whether they exist.
"""

from __future__ import annotations

import sqlite3

from .agent_review_gate import enabled, require_on
from .db import schema_once

CLASSES = (
    "Proven by code",
    "AI opinion, engineer to confirm",
    "AI opinion, rule not yet approved",
    "Query for the engineer",
    "Not applicable",
    "Not reviewed",
    # General review (no rule book; procedures and contracts): the two classes only that mode has (#1690, #781).
    "Not checked: rule book not held",
    "AI note, no rule book",
)
GENERAL_CLASSES = ("Not checked: rule book not held", "AI note, no rule book")
PARTS = (
    "not held",
    "checklist",
    "paper against itself",
    "against project papers",
    "engineering comment",
)
WORDS = (
    "Pass",
    "Fail",
    "AI thinks: met",
    "AI thinks: not met",
    "Query",
    "Not applicable",
    "Not reviewed",
    "Not checked",
    "AI note",
)
TIERS = ("Owner", "Engineer", "AI approved", "Not AI approved")
TABLES = (
    "agent_review_run",
    "agent_review_rule",
    "agent_review_line",
    "agent_review_missing_book",
    "agent_review_general",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS agent_review_run (
        run_id TEXT PRIMARY KEY,
        submittal_document_id TEXT NOT NULL,
        paper_kind TEXT NOT NULL,
        kind_source TEXT NOT NULL,
        equipment_type TEXT,
        usd REAL CHECK (usd IS NULL OR usd >= 0),
        models_json TEXT NOT NULL DEFAULT '[]',
        stop_reason TEXT,
        counts_json TEXT NOT NULL DEFAULT '{}',
        items_total INTEGER CHECK (items_total IS NULL OR items_total >= 0),
        partial INTEGER NOT NULL DEFAULT 0 CHECK (partial IN (0, 1)),
        rule_set_changed_by TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        equipment_json TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS agent_review_rule (
        run_id TEXT NOT NULL,
        rule_key TEXT NOT NULL CHECK (length(rule_key) > 0),
        asked INTEGER NOT NULL CHECK (asked IN (0, 1)),
        left_out_reason TEXT,
        rule_book TEXT,
        clause TEXT,
        quote TEXT,
        quote_page INTEGER,
        standard_document_id TEXT,
        read_from TEXT NOT NULL DEFAULT 'text' CHECK (read_from IN ('text', 'scan')),
        paper_kind TEXT,
        field TEXT,
        equipment TEXT,
        tier TEXT,
        PRIMARY KEY (run_id, rule_key),
        CHECK (asked = 1 OR left_out_reason IS NOT NULL),
        CHECK (asked = 0 OR left_out_reason IS NULL),
        CHECK (tier IS NULL OR tier IN """
    + _in(TIERS)
    + """)
    )""",
    f"""CREATE TABLE IF NOT EXISTS agent_review_line (
        run_id TEXT NOT NULL,
        item_id TEXT NOT NULL CHECK (length(item_id) > 0),
        verdict_class TEXT NOT NULL CHECK (verdict_class IN {_in(CLASSES)}),
        word TEXT NOT NULL CHECK (word IN {_in(WORDS)}),
        page INTEGER CHECK (page IS NULL OR page >= 1),
        clause TEXT,
        rule_book TEXT,
        reason TEXT,
        rule_tier TEXT CHECK (rule_tier IS NULL OR rule_tier IN {_in(TIERS)}),
        line_json TEXT NOT NULL,
        trace_json TEXT,
        decided_at TEXT NOT NULL,
        part TEXT CHECK (part IS NULL OR part IN {_in(PARTS)}),
        text_source TEXT CHECK (text_source IS NULL OR text_source IN ('quote', 'the model''s words')),
        PRIMARY KEY (run_id, item_id),
        CHECK (word NOT IN ('Pass', 'Fail') OR verdict_class = 'Proven by code'),
        CHECK (word NOT IN ('Pass', 'Fail') OR rule_tier IS NULL OR rule_tier <> 'Not AI approved'),
        CHECK (verdict_class NOT IN {_in(GENERAL_CLASSES)} OR (rule_tier IS NULL AND part IS NOT NULL)),
        CHECK (word NOT IN ('Not checked', 'AI note') OR verdict_class IN {_in(GENERAL_CLASSES)})
    )""",
    """CREATE TABLE IF NOT EXISTS agent_review_general (
        run_id TEXT PRIMARY KEY,
        requested_json TEXT NOT NULL DEFAULT '[]',
        project_json TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS agent_review_missing_book (
        run_id TEXT NOT NULL,
        name TEXT NOT NULL CHECK (length(name) > 0),
        why TEXT NOT NULL,
        PRIMARY KEY (run_id, name)
    )""",
    "CREATE INDEX IF NOT EXISTS agent_review_line_run ON agent_review_line (run_id, item_id)",
    "CREATE INDEX IF NOT EXISTS agent_review_rule_run ON agent_review_rule (run_id, asked)",
)


LINE_TABLE = "agent_review_line"
NEW_LINE_COLUMNS = frozenset({"part", "text_source"})
UPGRADE_ACTION = "agent_review_tables_upgraded"


class UpgradeFailed(RuntimeError):
    """The older `agent_review_line` table could not be upgraded: nothing was changed (the transaction rolled back), no run may
    start, no Claude call may be made."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"the AI review tables could not be upgraded: {reason}")


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def line_shape_is_old(conn) -> bool:
    """True when `agent_review_line` exists WITHOUT the general-review columns (the table as the first AI reviewer PR made it)."""
    cols = _columns(conn, LINE_TABLE)
    return bool(cols) and bool(NEW_LINE_COLUMNS - cols)


def has_tables(conn) -> bool:
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return set(TABLES) <= held and not line_shape_is_old(conn)


def shape_problem(conn) -> str | None:
    """Why no run may start before the first Claude call: the line table is still of the older shape (the upgrade did not
    happen or failed). None when the tables are usable or do not exist yet (they are made on the first run)."""
    if line_shape_is_old(conn):
        return "the AI review tables could not be upgraded: the older table shape is still in place"
    return None


def _rename_old_line_table(conn) -> str:
    """Move the older table out of the way under a dated name (nothing is deleted). Its indexes and triggers are dropped so the
    new table can have them again; they hold no data."""
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    old = f"{LINE_TABLE}_before_general_{stamp}"
    n = 1
    while conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (old,)).fetchone():
        n += 1
        old = f"{LINE_TABLE}_before_general_{stamp}_{n}"
    for name, kind in conn.execute(
        "SELECT name, type FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
        (LINE_TABLE,),
    ).fetchall():
        conn.execute(f'DROP {kind.upper()} "{name}"')
    conn.execute(f'ALTER TABLE {LINE_TABLE} RENAME TO "{old}"')
    return old


def _copy_old_rows(conn, old: str, old_columns: set[str]) -> int:
    """Every old row into the new table (new columns NULL); the counts must agree."""
    cols = ", ".join(sorted(_columns(conn, LINE_TABLE) & old_columns))
    conn.execute(f'INSERT INTO {LINE_TABLE} ({cols}) SELECT {cols} FROM "{old}"')
    n_old = conn.execute(f'SELECT COUNT(*) FROM "{old}"').fetchone()[0]
    if conn.execute(f"SELECT COUNT(*) FROM {LINE_TABLE}").fetchone()[0] != n_old:
        raise sqlite3.IntegrityError("the copy holds a different number of rows")
    return n_old


def _record_upgrade(conn, old: str, rows: int) -> None:
    from . import job_queue

    conn.execute(
        "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type, resource_id, outcome, detail)"
        " VALUES (?, NULL, 'system', ?, 'agent_review_line', ?, 'ok', ?)",
        (
            job_queue.now_iso(),
            UPGRADE_ACTION,
            old,
            f"rows copied: {rows}; the older table is kept under this name",
        ),
    )


def create_tables(conn) -> None:
    """Create what is missing, all or none. Switch off: raises `FeatureOff` and creates nothing. No existing table is touched,
    except that an `agent_review_line` of the OLDER shape is upgraded in ONE transaction: renamed to
    `agent_review_line_before_general_<time>` (kept, never dropped), the new table made, every row copied, the event recorded in
    `audit_events`. A failure rolls everything back and raises `UpgradeFailed`."""
    require_on()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        old = old_columns = None
        if line_shape_is_old(conn):
            old_columns = _columns(conn, LINE_TABLE)
            old = _rename_old_line_table(conn)
        for statement in _STATEMENTS:
            conn.execute(statement)
        if old is not None:
            _record_upgrade(conn, old, _copy_old_rows(conn, old, old_columns))
    except BaseException as exc:
        conn.rollback()
        if old is not None and isinstance(exc, sqlite3.Error):
            raise UpgradeFailed(str(exc)) from exc
        raise
    conn.commit()


@schema_once
def _ensure(conn=None) -> None:
    from .db import connect

    create_tables(conn if conn is not None else connect())


def ensure_schema(conn=None) -> None:
    """Switch off: does nothing, creates nothing, does not raise. On: the tables exist afterwards (an older line table is
    upgraded first; `UpgradeFailed` when that is not possible)."""
    if not enabled():
        return
    _ensure(conn)


def upgrade_if_old(quiet: bool = False) -> None:
    """Switch on only: upgrade an older line table where one exists. Creates nothing where no table exists (a GET never creates
    a table). Raises `UpgradeFailed`."""
    from .db import connect

    if enabled() and line_shape_is_old(connect()):
        from .db import reset_schema_memo

        reset_schema_memo()
        try:
            _ensure(None)
        except UpgradeFailed:
            if not quiet:
                raise
