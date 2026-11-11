"""Rule labels and the `ai_approved` tier: the tables, their guards, the words they allow (owner decision 1, 11 Nov 2026).

A rule is "AI approved" when two DIFFERENT Claude models agree on its paper kind, field and reading AND code finds its
quote word for word on the rule-book page. That is a state of `rule_label`, a table of its own: `rulebook_approval`
(a person's decision, owner or engineer tier, an active user as approver) is never written here and cannot hold this
tier.

BEHIND ONE SWITCH. `agent_review_enabled` (default off): off, no table is created and nothing here answers. On,
`ensure_schema` creates what is missing (CREATE ... IF NOT EXISTS only; no existing table is altered), once per
schema version through `db.schema_once`, the way every module's schema is made.

`rule_label` is keyed by (source, rule_ref): source 'requirement' (rule_ref = `standard_requirements.id`, the rule the
reviewer asks) or 'rulebook' (rule_ref = a `rulebook_version` id). `rule_version_id` is the rule-book version carrying
the same quote on the same page, else NULL (the rule book may not exist in a database at all).

NOTHING IS DELETED. A row cannot be deleted or replaced; a re-label is an UPDATE of the row and appends a
`rule_label_event` (the history, itself append-only). The database refuses a row in state `ai_approved` unless it holds
two answering models that differ, one prompt version shared by both passes, both answer hashes, a paper kind, a quote
hash and the page the quote stands on: the guard lives in the table as well as in the code that decides.
"""

from __future__ import annotations

from .config import settings
from .db import schema_once

PAPER_KINDS = ("datasheet", "procedure", "drawing", "calculation", "contract", "other")
SOURCES = ("requirement", "rulebook")
LABELLED_A, AI_APPROVED, NEEDS_HUMAN, QUOTE_NOT_FOUND = (
    "labelled_a",
    "ai_approved",
    "needs_human",
    "quote_not_found",
)
STATES = (LABELLED_A, AI_APPROVED, NEEDS_HUMAN, QUOTE_NOT_FOUND)
TABLES = ("rule_label", "rule_label_event")


class SwitchedOff(RuntimeError):
    """AGENT_REVIEW_ENABLED is off, so nothing was created, read or written."""


def switch_on() -> bool:
    """The one place this feature reads its switch (`settings.agent_review_enabled`, default off)."""
    return bool(settings.agent_review_enabled)


def require_on() -> None:
    if not switch_on():
        raise SwitchedOff(
            "AGENT_REVIEW_ENABLED is off; nothing was created, read or written"
        )


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


_HEX64 = "length({c}) = 64 AND {c} NOT GLOB '*[^0-9a-f]*'"

_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS rule_label (
        source TEXT NOT NULL CHECK (source IN {_in(SOURCES)}),
        rule_ref TEXT NOT NULL CHECK (length(rule_ref) > 0),
        rule_version_id TEXT,
        paper_kind TEXT CHECK (paper_kind IS NULL OR paper_kind IN {_in(PAPER_KINDS)}),
        field TEXT,
        state TEXT NOT NULL CHECK (state IN {_in(STATES)}),
        disagreement TEXT,
        a_model TEXT, a_prompt TEXT, a_answer_sha256 TEXT, a_answer_json TEXT,
        b_model TEXT, b_prompt TEXT, b_answer_sha256 TEXT, b_answer_json TEXT,
        reading_json TEXT,
        quote_page INTEGER,
        quote_sha256 TEXT,
        quote_recovery TEXT,
        labelled_at TEXT NOT NULL,
        PRIMARY KEY (source, rule_ref),
        CHECK (state <> '{AI_APPROVED}' OR (
            a_model IS NOT NULL AND b_model IS NOT NULL AND lower(trim(a_model)) <> lower(trim(b_model))
            AND length(trim(a_model)) > 0 AND length(trim(b_model)) > 0
            AND a_prompt IS NOT NULL AND length(trim(a_prompt)) > 0 AND a_prompt = b_prompt
            AND a_answer_sha256 IS NOT NULL AND b_answer_sha256 IS NOT NULL
            AND {_HEX64.format(c="a_answer_sha256")} AND {_HEX64.format(c="b_answer_sha256")}
            AND paper_kind IS NOT NULL AND (field IS NULL OR paper_kind = 'datasheet')
            AND quote_sha256 IS NOT NULL AND {_HEX64.format(c="quote_sha256")}
            AND quote_page IS NOT NULL AND reading_json IS NOT NULL AND disagreement IS NULL)),
        CHECK (state <> '{LABELLED_A}' OR (a_model IS NOT NULL AND b_model IS NULL)),
        CHECK (state <> '{QUOTE_NOT_FOUND}' OR (paper_kind IS NULL AND field IS NULL)),
        CHECK (state <> '{NEEDS_HUMAN}' OR disagreement IS NOT NULL)
    )""",
    "CREATE INDEX IF NOT EXISTS rule_label_version ON rule_label (rule_version_id)",
    """CREATE TABLE IF NOT EXISTS rule_label_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL, rule_ref TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK (event_type IN ('insert', 'relabel')),
        state TEXT NOT NULL, previous_state TEXT,
        at TEXT NOT NULL, detail_json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS rule_label_event_rule ON rule_label_event (source, rule_ref)",
    # Guards: a row is never deleted or replaced, its key never changes, the history is append-only.
    """CREATE TRIGGER IF NOT EXISTS rule_label_no_delete BEFORE DELETE ON rule_label
        BEGIN SELECT RAISE(ABORT, 'rule_label: rows are never deleted'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_no_replace BEFORE INSERT ON rule_label
        WHEN EXISTS (SELECT 1 FROM rule_label t WHERE t.source = NEW.source AND t.rule_ref = NEW.rule_ref)
        BEGIN SELECT RAISE(ABORT, 'rule_label: a row is never replaced; update it'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_key_fixed BEFORE UPDATE ON rule_label
        WHEN NEW.source <> OLD.source OR NEW.rule_ref <> OLD.rule_ref
        BEGIN SELECT RAISE(ABORT, 'rule_label: the key of a row never changes'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_event_insert AFTER INSERT ON rule_label BEGIN
        INSERT INTO rule_label_event (source, rule_ref, event_type, state, previous_state, at, detail_json)
        VALUES (NEW.source, NEW.rule_ref, 'insert', NEW.state, NULL, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                json_object('a_model', NEW.a_model, 'b_model', NEW.b_model, 'prompt', NEW.a_prompt,
                            'quote_sha256', NEW.quote_sha256, 'disagreement', NEW.disagreement));
        END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_event_update AFTER UPDATE ON rule_label BEGIN
        INSERT INTO rule_label_event (source, rule_ref, event_type, state, previous_state, at, detail_json)
        VALUES (NEW.source, NEW.rule_ref, 'relabel', NEW.state, OLD.state, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                json_object('a_model', NEW.a_model, 'b_model', NEW.b_model, 'prompt', NEW.a_prompt,
                            'quote_sha256', NEW.quote_sha256, 'disagreement', NEW.disagreement));
        END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_event_no_update BEFORE UPDATE ON rule_label_event
        BEGIN SELECT RAISE(ABORT, 'rule_label_event is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_event_no_delete BEFORE DELETE ON rule_label_event
        BEGIN SELECT RAISE(ABORT, 'rule_label_event is append-only'); END""",
)


def has_tables(conn) -> bool:
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return set(TABLES) <= held


def create_tables(conn) -> None:
    """Create what is missing, all or none, on this connection's database. Switch off: raises `SwitchedOff` and creates
    nothing. Run twice it does nothing. No existing table is touched. WHICH database is the caller's business: the
    server's own (through `ensure_schema`) or a copy a tool opened (the label job refuses a live-shaped one first)."""
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
    """The app's schema walk calls this for every module. Switch off: does nothing, creates nothing, does not raise."""
    if not switch_on():
        return
    _ensure(conn)
