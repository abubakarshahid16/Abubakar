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

import hashlib
import json

from .db import connect

RUNS = "aim_runs"
LINES = "aim_lines"
CHECKLISTS = "aim_checklists"
#: The only `built_from` a saved checklist may have: it was written from the rule books alone, never from a paper.
BUILT_FROM = "standards only, no paper"
#: A checklist that also holds engineering-knowledge items where a governing book is not held (still no paper).
BUILT_FROM_KNOWLEDGE = (
    "standards only, no paper; engineering knowledge where a book is not held"
)
#: The only ways a saved checklist may have been built: never from the paper.
BUILT_FROMS = (BUILT_FROM, BUILT_FROM_KNOWLEDGE)
#: The key `DbChecklistStore.get` adds to the body: the current row's sha256 (ASK A -> D).
SHA_KEY = "sha256"

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
        quote_unverified  TEXT,
        comment           TEXT,
        standard          TEXT,
        book_document_id  TEXT,
        clause            TEXT,
        source            TEXT,
        topic             TEXT,
        code_note         TEXT,
        numbers_json      TEXT,
        code_compare_json TEXT,
        named_books_json  TEXT,
        ask               TEXT,
        deferred          INTEGER,
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


def _unverified_text(value) -> str:
    """The words the model gave as a quote that code did NOT find on the page ("" when none). Kept as text so a person can see
    what was claimed; the page and the file show it apart from `quote` and never as a quote (ASK A -> D, decided in the join)."""
    return value if isinstance(value, str) else ""


def ensure_schema(conn=None) -> None:
    """The three tables exist afterwards. Wired into the app's schema start-up (`main.lifespan`)."""
    conn = conn or connect()
    _create(conn)
    conn.commit()


def _create(conn) -> None:
    """The tables, WITHOUT committing. A table made before a column was added gets it (additive, never a rewrite)."""
    from .db import add_column_if_missing

    for statement in _SCHEMA:
        conn.execute(statement)
    # the listed books an always-on line's words name (rule 5: the page hides a name a viewer may not read)
    add_column_if_missing(conn, LINES, "named_books_json", "TEXT")
    # what a Question asks and whether its value is left open (recorded 18 Nov 2026; an older line reads null: unknown)
    add_column_if_missing(conn, LINES, "ask", "TEXT")
    add_column_if_missing(conn, LINES, "deferred", "INTEGER")


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


def start_run(conn, run_id: str, paper_id: str, now: str) -> None:
    """The run's row, WITHOUT committing (it joins the transaction that makes the `review_runs` row and the job)."""
    _create(conn)
    conn.execute(
        f"INSERT INTO {RUNS} (run_id, paper_document_id, status, created_at) VALUES (?,?,?,?)",
        (run_id, paper_id, "queued", now),
    )


# ---- the run and its lines -------------------------------------------------------------------------------------------------

#: A run's stored status. `done` is the only one the page and the next plan treat as a finished review.
STATUSES = ("queued", "running", "done", "stopped", "failed", "cancelled")

# shown_label: what a PERSON sees as a line's verdict. ONE home (CONTRACT section 4). The stored `label` keeps the method's five
# words for the score; code's own comparison is the only thing that earns "compared by code".
FAIL_BY_CODE = "Fail, compared by code"
PASS_BY_CODE = "Pass, compared by code"
_SHOWN = {
    "Not met": "AI opinion: not met",
    "Met": "AI opinion: met",
    "Does not apply": "AI opinion: does not apply",
    "AI opinion": "AI opinion",
    "Question": "Question",
}


def _json_of(value):
    """A column's value as a python value: a json string is parsed, a python value is kept, anything unreadable is None."""
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


#: What a person sees for a line code decided does not apply because its rule book is a company standard this paper does not cite
#: (`aim_review.engine.NOT_CITED`): code's decision, so never "AI opinion" (the lead, 18 Nov 2026).
NOT_CITED_SHOWN = "Does not apply (rule book not cited by this paper)"


def _not_cited(code_note) -> bool:
    from .aim_review.engine import NOT_CITED

    return NOT_CITED in {part.strip() for part in str(code_note or "").split(";")}


def shown_label(
    label: str, code_compare=None, deferred: bool = False, code_note: str = ""
) -> str:
    """The words a person sees for a line. `Fail, compared by code` / `Pass, compared by code` ONLY when code compared a value
    (`code_compare.result` is fail / pass) AND the line's label agrees with that result; a vendor-deferred value is always a
    `Question`; everything else is an AI opinion or a question. An unknown label is a `Question` (never a verdict)."""
    if deferred:
        return "Question"
    if label == "Does not apply" and _not_cited(code_note):
        return NOT_CITED_SHOWN
    compare = _json_of(code_compare)
    result = (
        str(compare.get("result") or "").casefold() if isinstance(compare, dict) else ""
    )
    if result == "fail" and label == "Not met":
        return FAIL_BY_CODE
    if result == "pass" and label == "Met":
        return PASS_BY_CODE
    return _SHOWN.get(label, "Question")


def _dump(value) -> str | None:
    return (
        None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )


#: The stored columns of a line, in `_line_row`'s order (named, so a table that got a column later takes the same insert).
LINE_COLUMNS = (
    "run_id", "line_no", "item_id", "label", "shown_label", "field", "page", "quote", "quote_unverified", "comment", "standard",
    "book_document_id", "clause", "source", "topic", "code_note", "numbers_json", "code_compare_json", "named_books_json", "ask",
    "deferred",
)  # fmt: skip
#: What a Question line may record as its ask (`aim_review.steps._ask`); anything else is stored as null (unknown).
ASKS = ("concern", "confirm", "open")


def _line_row(run_id: str, n: int, line: dict) -> tuple:
    """One `aim_lines` row. The stored `label` must be one of the method's five words, so a bad line fails the whole finish."""
    label = line.get("label")
    if label not in _SHOWN:
        raise ValueError(f"line {n}: not one of the method's labels")
    compare = line.get("code_compare", line.get("code_compare_json"))
    numbers = _json_of(line.get("numbers", line.get("numbers_json")))
    deferred = bool(line.get("deferred")) or (
        isinstance(numbers, dict) and bool(numbers.get("deferred"))
    )
    page = line.get("page")
    return (
        run_id,
        n,
        line.get("item_id"),
        label,
        shown_label(
            label, compare, deferred, line.get("code_note", line.get("code")) or ""
        ),
        line.get("field") or "",
        page if isinstance(page, int) and not isinstance(page, bool) else None,
        line.get("quote") or "",
        _unverified_text(line.get("quote_unverified")),
        line.get("comment") or "",
        line.get("standard") or "",
        line.get("book_document_id"),
        line.get("clause") or "",
        line.get("source") or "",
        line.get("topic") or "",
        line.get("code_note", line.get("code")) or "",
        _dump(numbers),
        _dump(_json_of(compare)),
        _dump(_named(line)),
        line.get("ask") if line.get("ask") in ASKS else None,
        1 if deferred else 0,
    )


def _named(line: dict) -> list | None:
    """The [{id, name}] of the listed books the line's words name (an always-on line), or None."""
    named = _json_of(line.get("named_books", line.get("named_books_json")))
    return named if isinstance(named, list) and named else None


def finish_run(conn, run_id: str, result: dict, now: str) -> None:
    """Store a finished run: its lines AND its row, in ONE transaction. All or nothing: any failure (an unknown run, a line without
    a method label) leaves the database as it was and raises. Lines get `line_no` 1, 2, 3 ... in the order given."""
    status = str(result.get("status") or "")
    if status not in STATUSES:
        raise ValueError("unknown run status")
    rows = [
        _line_row(run_id, n, dict(line))
        for n, line in enumerate(result.get("lines") or [], start=1)
    ]
    conn.execute("SAVEPOINT aim_finish_run")
    try:
        conn.execute(f"DELETE FROM {LINES} WHERE run_id = ?", (run_id,))
        conn.executemany(
            f"INSERT INTO {LINES} ({', '.join(LINE_COLUMNS)}) VALUES ({','.join('?' * len(LINE_COLUMNS))})",
            rows,
        )
        cur = conn.execute(
            f"UPDATE {RUNS} SET status = ?, method_version = ?, identity_json = ?, checklist_key = ?, checklist_sha256 = ?,"
            " checklist_reused = ?, books_json = ?, not_held_json = ?, unlisted_json = ?, usd = ?, seconds = ?, calls_json = ?,"
            " stop_reason = ?, finished_at = ? WHERE run_id = ?",
            (
                status,
                result.get("method_version") or _method_version(),
                _dump(result.get("identity")),
                result.get("checklist_key"),
                result.get("checklist_sha256"),
                1 if result.get("checklist_reused") else 0,
                _dump(list(result.get("books") or [])),
                _dump(list(result.get("not_held") or [])),
                _dump(list(result.get("unlisted_books") or [])),
                result.get("usd"),
                result.get("seconds"),
                _dump(list(result.get("calls") or [])),
                result.get("stop_reason") or "",
                now,
                run_id,
            ),
        )
        if cur.rowcount != 1:
            raise LookupError("no such general run")
        conn.execute("RELEASE SAVEPOINT aim_finish_run")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT aim_finish_run")
        conn.execute("RELEASE SAVEPOINT aim_finish_run")
        conn.commit()
        raise
    conn.commit()


def _method_version() -> str:
    from .aim_review import METHOD_VERSION

    return METHOD_VERSION


def set_completeness(conn, run_id: str, report: dict) -> None:
    """Piece C's completeness report (`aim_review_completeness.record_after_run`) is kept with the run."""
    conn.execute(
        f"UPDATE {RUNS} SET completeness_json = ? WHERE run_id = ?",
        (_dump(report), run_id),
    )
    conn.commit()


_RUN_JSON = {
    "identity": "identity_json",
    "books": "books_json",
    "not_held": "not_held_json",
    "unlisted": "unlisted_json",
    "calls": "calls_json",
    "completeness": "completeness_json",
}


def _run_dict(row) -> dict:
    """The stored row as is, plus each `*_json` column read as a python value under its plain name."""
    out = dict(row)
    for plain, column in _RUN_JSON.items():
        out[plain] = _json_of(out.get(column))
    out["checklist_reused"] = bool(out.get("checklist_reused"))
    return out


def run(conn, run_id: str) -> dict | None:
    if not has_tables(conn):
        return None
    row = conn.execute(f"SELECT * FROM {RUNS} WHERE run_id = ?", (run_id,)).fetchone()
    return _run_dict(row) if row else None


def lines(conn, run_id: str) -> list[dict]:
    """Every line of the run, in order, as stored; `numbers` and `code_compare` are also given read back (None when absent)."""
    if not has_tables(conn):
        return []
    out = []
    for r in conn.execute(
        f"SELECT * FROM {LINES} WHERE run_id = ? ORDER BY line_no", (run_id,)
    ):
        d = dict(r)
        d["numbers"] = _json_of(d.get("numbers_json"))
        d["code_compare"] = _json_of(d.get("code_compare_json"))
        named = _json_of(d.get("named_books_json"))
        d["named_books"] = named if isinstance(named, list) else []
        d["quote_unverified"] = (
            d.get("quote_unverified")
            if isinstance(d.get("quote_unverified"), str)
            else ""
        )
        out.append(d)
    return out


#: The states of a run that ENDED with lines to show: finished, or stopped early (run cap, lane closed, a fault).
ENDED = ("done", "stopped")


def latest_run(
    conn, paper_id: str, done_only: bool = True, *, ended: bool = False
) -> dict | None:
    """The paper's newest general run: `done_only` a finished one; `ended` a finished OR stopped one (what the page shows: a run
    that stopped early is shown as stopped, never hidden behind an older finished one); neither, any state."""
    if not has_tables(conn):
        return None
    where = (
        f" AND status IN ({','.join(repr(s) for s in ENDED)})"
        if ended
        else (" AND status = 'done'" if done_only else "")
    )
    row = conn.execute(
        f"SELECT * FROM {RUNS} WHERE paper_document_id = ?{where} ORDER BY created_at DESC, run_id DESC LIMIT 1",
        (paper_id,),
    ).fetchone()
    return _run_dict(row) if row else None


def unlisted_of_last(conn, paper_id: str) -> frozenset[str]:
    """The ids of the held rule books the paper's last finished general review wanted but were not on the list shown."""
    last = latest_run(conn, paper_id)
    if not last or not isinstance(last.get("unlisted"), list):
        return frozenset()
    return frozenset(str(d) for d in last["unlisted"])


# ---- saved checklists ----------------------------------------------------------------------------------------------------


def checklist_sha256(checklist: dict) -> str:
    """The checklist's fingerprint: sha256 of its canonical json (sorted keys, no spaces)."""
    body = json.dumps(
        checklist, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _book_ids(books) -> list[str]:
    ids = []
    for b in books or []:
        got = (
            b
            if isinstance(b, str)
            else (
                b.get("book") or b.get("id") or b.get("document_id")
            )  # the checklist names its books by `book` (A)
            if isinstance(b, dict)
            else None
        )
        if got:
            ids.append(str(got))
    return ids


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


class DbChecklistStore:
    """Implements `aim_review.ChecklistStore` on `aim_checklists`. A new build never overwrites: the older row stays, `current = 0`."""

    def __init__(self, conn=None):
        self.conn = conn

    def _conn(self):
        if self.conn is None:
            self.conn = connect()
        return self.conn

    def get(self, key: str) -> dict | None:
        """The current checklist for the key, WITH a "sha256" key (the current row's fingerprint, so a reusing run records it), or
        None (also when the stored body cannot be read, or was not built from the standards alone)."""
        conn = self._conn()
        if not has_tables(conn):
            return None
        row = conn.execute(
            f"SELECT sha256, body_json, built_from FROM {CHECKLISTS} WHERE key = ? AND current = 1",
            (key,),
        ).fetchone()
        if row is None or row["built_from"] not in BUILT_FROMS:
            return None
        body = _json_of(row["body_json"])
        return {**body, SHA_KEY: row["sha256"]} if isinstance(body, dict) else None

    def keys(self) -> list[str]:
        """The keys that have a current checklist built from the standards alone, sorted."""
        conn = self._conn()
        if not has_tables(conn):
            return []
        return [
            r["key"]
            for r in conn.execute(
                f"SELECT key FROM {CHECKLISTS} WHERE current = 1 AND built_from IN (?, ?) ORDER BY key",
                BUILT_FROMS,
            )
        ]

    def put(self, key: str, checklist: dict, *, run_id: str, usd: float) -> str:
        """Save a checklist as the current one for the key; returns its sha256. Refused (ValueError) unless it was built from the
        standards alone: `built_from` must be one of BUILT_FROMS (never the paper)."""
        if (
            not isinstance(checklist, dict)
            or checklist.get("built_from") not in BUILT_FROMS
        ):
            raise ValueError(
                'a saved checklist must be built from "'
                + '" or "'.join(BUILT_FROMS)
                + '"'
            )
        # the "sha256" that `get` adds is not part of the body: a body put back unchanged keeps its fingerprint
        checklist = {k: v for k, v in checklist.items() if k != SHA_KEY}
        digest = checklist_sha256(checklist)
        conn = self._conn()
        _create(conn)
        ident = (
            checklist.get("identity")
            if isinstance(checklist.get("identity"), dict)
            else {}
        )
        items = checklist.get("items")
        conn.execute("SAVEPOINT aim_put_checklist")
        try:
            conn.execute(
                f"UPDATE {CHECKLISTS} SET current = 0 WHERE key = ? AND sha256 != ?",
                (key, digest),
            )
            if conn.execute(
                f"SELECT 1 FROM {CHECKLISTS} WHERE key = ? AND sha256 = ?",
                (key, digest),
            ).fetchone():
                conn.execute(
                    f"UPDATE {CHECKLISTS} SET current = 1 WHERE key = ? AND sha256 = ?",
                    (key, digest),
                )
            else:
                conn.execute(
                    f"INSERT INTO {CHECKLISTS} (key, sha256, current, kind, equipment_type, subject_key, built_from, body_json,"
                    " books_json, items, made_at, made_by_run, usd) VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        digest,
                        ident.get("kind") or checklist.get("kind"),
                        ident.get("equipment_type") or checklist.get("equipment_type"),
                        ident.get("subject_key") or checklist.get("subject_key"),
                        checklist["built_from"],
                        json.dumps(checklist, ensure_ascii=False, sort_keys=True),
                        _dump(_book_ids(checklist.get("books"))),
                        len(items) if isinstance(items, list) else None,
                        _now(),
                        run_id,
                        usd,
                    ),
                )
            conn.execute("RELEASE SAVEPOINT aim_put_checklist")
        except BaseException:
            conn.execute("ROLLBACK TO SAVEPOINT aim_put_checklist")
            conn.execute("RELEASE SAVEPOINT aim_put_checklist")
            conn.commit()
            raise
        conn.commit()
        return digest


def checklists(conn) -> list[dict]:
    """The saved checklists, the current ones first then the older ones, newest first: key, kind, type, items, books (ids), built
    from, made at, sha256, current. No body (the body is the rule books' own text)."""
    if not has_tables(conn):
        return []
    out = []
    for r in conn.execute(
        f"SELECT * FROM {CHECKLISTS} ORDER BY current DESC, made_at DESC, key"
    ):
        out.append(
            {
                "key": r["key"],
                "kind": r["kind"],
                "equipment_type": r["equipment_type"],
                "items": r["items"],
                "books": _json_of(r["books_json"]) or [],
                "built_from": r["built_from"],
                "made_at": r["made_at"],
                "made_by_run": r["made_by_run"],
                "usd": r["usd"],
                "sha256": r["sha256"],
                "current": bool(r["current"]),
            }
        )
    return out
