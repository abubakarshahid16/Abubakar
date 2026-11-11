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

Switch off: `ensure_schema` does nothing and creates nothing; `create_tables` raises `FeatureOff`. A GET never creates a
table: `has_tables` says whether they exist.
"""

from __future__ import annotations

from .agent_review_gate import enabled, require_on
from .db import schema_once

CLASSES = (
    "Proven by code",
    "AI opinion, engineer to confirm",
    "AI opinion, rule not yet approved",
    "Query for the engineer",
    "Not applicable",
    "Not reviewed",
)
WORDS = (
    "Pass",
    "Fail",
    "AI thinks: met",
    "AI thinks: not met",
    "Query",
    "Not applicable",
    "Not reviewed",
)
TIERS = ("Owner", "Engineer", "AI approved", "Not AI approved")
TABLES = (
    "agent_review_run",
    "agent_review_rule",
    "agent_review_line",
    "agent_review_missing_book",
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
        PRIMARY KEY (run_id, item_id),
        CHECK (word NOT IN ('Pass', 'Fail') OR verdict_class = 'Proven by code'),
        CHECK (word NOT IN ('Pass', 'Fail') OR rule_tier IS NULL OR rule_tier <> 'Not AI approved')
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


def has_tables(conn) -> bool:
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return set(TABLES) <= held


def create_tables(conn) -> None:
    """Create what is missing, all or none. Switch off: raises `FeatureOff` and creates nothing. No existing table is touched."""
    require_on()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _STATEMENTS:
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


@schema_once
def _ensure(conn=None) -> None:
    from .db import connect

    create_tables(conn if conn is not None else connect())


def ensure_schema(conn=None) -> None:
    """Switch off: does nothing, creates nothing, does not raise. On: the tables exist afterwards."""
    if not enabled():
        return
    _ensure(conn)
