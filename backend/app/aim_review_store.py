"""The general review's storage (order 14, piece D): its runs, its lines, its saved checklists.

BASE BRANCH VERSION (integrator): the real schema, `EXCLUDE_SQL` and `exclude`, and simple working stand-ins of the readers and
writers so the other pieces can run against them. Piece D replaces the stand-ins (and owns `shown_label`'s one home).

Tables (CREATE ... IF NOT EXISTS, additive only; nothing old is altered):
  aim_runs        one row per general review run; `run_id` is the run's `review_runs.id`.
  aim_lines       one row per checklist item judged in a run.
  aim_checklists  saved checklists; a new build never overwrites: the older row stays with `current = 0`.

THE OLD READERS. A general run is a `review_runs` row like any other, so every old reader that takes "not an AI run" to mean
"a rule check" (the latest rule-check run of a paper, the run list, the latest cancelled run, ...) adds `exclude(conn, alias)`:
the general run is invisible to it. Ids and counts only: this module holds no rule of what a line says.
"""

from __future__ import annotations

import json

from .db import connect

RUNS = "aim_runs"
LINES = "aim_lines"
CHECKLISTS = "aim_checklists"
#: The only `built_from` a saved checklist may have: it was written from the rule books alone, never from a paper.
BUILT_FROM = "standards only, no paper"

#: For every old reader of `review_runs` (alias `r`): a general run is not one of its runs.
EXCLUDE_SQL = "r.id NOT IN (SELECT run_id FROM aim_runs)"

_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS {RUNS} (
        run_id            TEXT PRIMARY KEY,
        paper_document_id TEXT NOT NULL,
        status            TEXT NOT NULL,
        method_version    TEXT,
        identity_json     TEXT,
        checklist_key     TEXT,
        checklist_sha256  TEXT,
        checklist_reused  INTEGER,
        books_json        TEXT,
        not_held_json     TEXT,
        unlisted_json     TEXT,
        usd               REAL,
        seconds           REAL,
        calls_json        TEXT,
        completeness_json TEXT,
        stop_reason       TEXT,
        created_at        TEXT NOT NULL,
        finished_at       TEXT
    )""",
    f"CREATE INDEX IF NOT EXISTS ix_{RUNS}_paper ON {RUNS} (paper_document_id, created_at)",
    f"""CREATE TABLE IF NOT EXISTS {LINES} (
        run_id            TEXT NOT NULL,
        line_no           INTEGER NOT NULL,
        item_id           TEXT,
        label             TEXT NOT NULL,
        shown_label       TEXT NOT NULL,
        field             TEXT,
        page              INTEGER,
        quote             TEXT,
        quote_unverified  INTEGER,
        comment           TEXT,
        standard          TEXT,
        book_document_id  TEXT,
        clause            TEXT,
        source            TEXT,
        topic             TEXT,
        code_note         TEXT,
        numbers_json      TEXT,
        code_compare_json TEXT,
        PRIMARY KEY (run_id, line_no)
    )""",
    f"""CREATE TABLE IF NOT EXISTS {CHECKLISTS} (
        key            TEXT NOT NULL,
        sha256         TEXT NOT NULL,
        current        INTEGER NOT NULL DEFAULT 1,
        kind           TEXT,
        equipment_type TEXT,
        subject_key    TEXT,
        built_from     TEXT NOT NULL,
        body_json      TEXT NOT NULL,
        books_json     TEXT,
        items          INTEGER,
        made_at        TEXT NOT NULL,
        made_by_run    TEXT,
        usd            REAL,
        PRIMARY KEY (key, sha256)
    )""",
)


def ensure_schema(conn=None) -> None:
    """The three tables exist afterwards. Wired into the app's schema start-up (`main.lifespan`)."""
    conn = conn or connect()
    _create(conn)
    conn.commit()


def _create(conn) -> None:
    """The tables, WITHOUT committing."""
    for statement in _SCHEMA:
        conn.execute(statement)


def has_tables(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (RUNS,)
        ).fetchone()
        is not None
    )


def exclude(conn, alias: str = "r") -> str:
    """` AND <alias>.id NOT IN (SELECT run_id FROM aim_runs)` for an old reader's WHERE, or "" when the table does not exist
    yet (a database made before the general review holds no general run)."""
    if not has_tables(conn):
        return ""
    return " AND " + EXCLUDE_SQL.replace("r.id", f"{alias}.id", 1)


def is_general(conn, run_id: str) -> bool:
    if not run_id or not has_tables(conn):
        return False
    return (
        conn.execute(f"SELECT 1 FROM {RUNS} WHERE run_id = ?", (run_id,)).fetchone()
        is not None
    )


# ---- stand-ins below: piece D replaces them ------------------------------------------------------------------------------


def start_run(conn, run_id: str, paper_id: str, now: str) -> None:
    """The run's row, WITHOUT committing (it joins the transaction that makes the `review_runs` row and the job)."""
    _create(conn)
    conn.execute(
        f"INSERT INTO {RUNS} (run_id, paper_document_id, status, created_at) VALUES (?,?,?,?)",
        (run_id, paper_id, "queued", now),
    )


def finish_run(conn, run_id: str, result: dict, now: str) -> None:
    raise NotImplementedError("piece D: finish_run")


def run(conn, run_id: str) -> dict | None:
    if not has_tables(conn):
        return None
    row = conn.execute(f"SELECT * FROM {RUNS} WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def lines(conn, run_id: str) -> list[dict]:
    if not has_tables(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM {LINES} WHERE run_id = ? ORDER BY line_no", (run_id,)
        )
    ]


def latest_run(conn, paper_id: str, done_only: bool = True) -> dict | None:
    if not has_tables(conn):
        return None
    where = " AND status = 'done'" if done_only else ""
    row = conn.execute(
        f"SELECT * FROM {RUNS} WHERE paper_document_id = ?{where} ORDER BY created_at DESC, run_id DESC LIMIT 1",
        (paper_id,),
    ).fetchone()
    return dict(row) if row else None


def unlisted_of_last(conn, paper_id: str) -> frozenset[str]:
    last = latest_run(conn, paper_id)
    if not last or not last.get("unlisted_json"):
        return frozenset()
    try:
        return frozenset(str(d) for d in json.loads(last["unlisted_json"]) or [])
    except ValueError:
        return frozenset()


class DbChecklistStore:
    """Implements `aim_review.ChecklistStore` on `aim_checklists`."""

    def __init__(self, conn=None):
        self.conn = conn

    def get(self, key: str) -> dict | None:
        raise NotImplementedError("piece D: DbChecklistStore.get")

    def put(self, key: str, checklist: dict, *, run_id: str, usd: float) -> str:
        raise NotImplementedError("piece D: DbChecklistStore.put")


def checklists(conn) -> list[dict]:
    raise NotImplementedError("piece D: checklists")
