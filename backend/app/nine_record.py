"""The stored record of a nine-role review (owner order, 15 Nov 2026, STATE section 60; SPEC section B): what each role READ and PRODUCED.

Four tables, owned by this module (its own `ensure_schema`; `agent_review_schema.py` is not touched):

    agent_review_role        one row per run and role (nine, written at the run's start, all "not run: not reached"); each role
                             updates its own row at its start and its end
    agent_review_role_call   one row per model call of a nine-role request: step, engine, model, the request's digest, the state,
                             the error code and the cost (NULL = not known, never 0)
    agent_review_role_read   one row per document block of that request: document id and kind, pages, chapter, part, size, checksum
    agent_review_role_cell   one row per cell of a derived block sent to Claude: its kind (a typed token, or "source": which document and
                             page it was found on, and where) and its checksum, so the checker can re-read the span (no cell text)

IDS, NUMBERS, CODES AND CHECKSUMS ONLY. Never a title, a file name or any text of a document, and no model output: the rows are
written by CODE from the block list a request was built from (`nine_call.ask`), so the record cannot say something else than what
was sent. A role's "sent" row is written in the function that hands the body to the transport, BEFORE it leaves; the end state after.

This module opens no socket, calls no model and reads no document text.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from .db import connect
from .nine_contract import (
    ROLE_NAMES,
    CallEntry,
    ReadEntry,
    ReviewRecord,
    RoleRecord,
)

ROLES_TABLE, CALLS_TABLE, READS_TABLE, CELLS_TABLE = (
    "agent_review_role",
    "agent_review_role_call",
    "agent_review_role_read",
    "agent_review_role_cell",
)
#: the kinds of a derived cell: a typed token, or text found in one of the block's own sources
CELL_KINDS = ("number", "clause", "standard", "enum", "vocab", "id", "unit", "source")
#: a typed cell is at most this long (a source cell may be longer: it is checked against the stored text instead)
MAX_TYPED_CELL = 64
HELD_MIN_CHARS = (
    12  # a string this long that occurs in a refused document's stored text is refused
)


@dataclass(frozen=True)
class CellEntry:
    """One cell of a derived block, as the seam classified it. No cell text: a checksum of the folded cell and, for a source cell, where
    it was found (`fold` of the page text, character offset and length)."""

    block_name: str
    row_no: int
    col_no: int
    kind: str
    chars: int
    cell_sha256: str
    source_document_id: str | None = None
    source_page: int | None = None
    span_start: int | None = None
    span_len: int | None = None


_WS = re.compile(r"\s+")


def fold(text: str) -> str:
    """The one way text is compared by the seam and the checker: lower case, runs of white space as one space, trimmed."""
    return _WS.sub(" ", str(text)).strip().lower()


NOT_REACHED = "not reached"
CALL_STATES = ("sent", "answered", "failed", "refused", "reused")
ROLE_STATES = ("ran", "ran_partly", "not_run")
ENGINES = ("claude", "local", "code")
KINDS = ("paper", "rule_book", "project_document", "earlier_revision", "review_record")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {ROLES_TABLE} (
            run_id        TEXT NOT NULL,
            role_no       INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9),
            role          TEXT NOT NULL,
            state         TEXT NOT NULL CHECK (state IN ('ran', 'ran_partly', 'not_run')),
            why           TEXT,
            engine        TEXT CHECK (engine IS NULL OR engine IN ('claude', 'local', 'code')),
            models_json   TEXT NOT NULL DEFAULT '[]',
            calls         INTEGER NOT NULL DEFAULT 0,
            usd           REAL CHECK (usd IS NULL OR usd >= 0),
            started_at    TEXT,
            finished_at   TEXT,
            produced_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (run_id, role_no),
            CHECK (state = 'ran' OR (why IS NOT NULL AND length(trim(why)) > 0)),
            CHECK (why IS NULL OR (length(why) <= 120 AND instr(why, char(10)) = 0))
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {CALLS_TABLE} (
            run_id         TEXT NOT NULL,
            role_no        INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9),
            call_id        TEXT NOT NULL,
            step           TEXT NOT NULL,
            engine         TEXT NOT NULL CHECK (engine IN ('claude', 'local', 'code')),
            model          TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            state          TEXT NOT NULL CHECK (state IN ('sent', 'answered', 'failed', 'refused', 'reused')),
            error_code     TEXT,
            usd            REAL CHECK (usd IS NULL OR usd >= 0),
            usd_reserved   REAL CHECK (usd_reserved IS NULL OR usd_reserved >= 0),
            question_id    TEXT,
            system_id      TEXT,
            params_sha256  TEXT,
            sent_at        TEXT NOT NULL,
            PRIMARY KEY (run_id, call_id)
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {READS_TABLE} (
            run_id        TEXT NOT NULL,
            role_no       INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9),
            call_id       TEXT NOT NULL,
            seq           INTEGER NOT NULL,
            document_id   TEXT NOT NULL,
            document_kind TEXT NOT NULL CHECK (document_kind IN
                ('paper', 'rule_book', 'project_document', 'earlier_revision', 'review_record')),
            pages_json    TEXT NOT NULL DEFAULT '[]',
            chapter_id    TEXT,
            part_no       INTEGER,
            part_of       INTEGER,
            chars         INTEGER NOT NULL DEFAULT 0,
            text_sha256   TEXT NOT NULL,
            pictures      INTEGER NOT NULL DEFAULT 0,
            char_from     INTEGER,
            char_to       INTEGER,
            PRIMARY KEY (run_id, call_id, seq)
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {CELLS_TABLE} (
            run_id             TEXT NOT NULL,
            role_no            INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9),
            call_id            TEXT NOT NULL,
            block_name         TEXT NOT NULL,
            row_no             INTEGER NOT NULL,
            col_no             INTEGER NOT NULL,
            kind               TEXT NOT NULL CHECK (kind IN ('number','clause','standard','enum','vocab','id','unit','source')),
            chars              INTEGER NOT NULL,
            cell_sha256        TEXT NOT NULL,
            source_document_id TEXT,
            source_page        INTEGER,
            span_start         INTEGER,
            span_len           INTEGER,
            PRIMARY KEY (run_id, call_id, block_name, row_no, col_no),
            CHECK (kind <> 'source' OR (source_document_id IS NOT NULL AND source_page IS NOT NULL
                                        AND span_start IS NOT NULL AND span_len IS NOT NULL))
        )"""
    )


# ------------------------------------------------------------------------------------------------------ the nine rows


def start_run(run_id: str, conn=None) -> None:
    """Nine rows, all "not run: not reached" (idempotent: a restart keeps a row a role already finished)."""
    conn = conn or connect()
    ensure_schema(conn)
    with conn:
        for no, name in ROLE_NAMES.items():
            conn.execute(
                f"INSERT OR IGNORE INTO {ROLES_TABLE} (run_id, role_no, role, state, why) VALUES (?,?,?,'not_run',?)",
                (run_id, no, name, NOT_REACHED),
            )


def role_start(run_id: str, role_no: int, engine: str, conn=None) -> None:
    conn = conn or connect()
    ensure_schema(conn)
    _check_role(role_no)
    _check(engine, ENGINES, "engine")
    start_run(run_id, conn)
    with conn:
        conn.execute(
            f"UPDATE {ROLES_TABLE} SET engine = ?, started_at = ?, finished_at = NULL WHERE run_id = ? AND role_no = ?",
            (engine, now(), run_id, role_no),
        )


def role_end(
    run_id: str,
    role_no: int,
    state: str,
    *,
    why: str | None = None,
    produced: dict | None = None,
    models: tuple[str, ...] | list[str] = (),
    engine: str | None = None,
    conn=None,
) -> None:
    """A role's end. `why` is required unless it ran in full. `calls`, `usd` and `models` follow the call rows (a NULL cost stays NULL:
    never 0 for "not known"); `produced` is counts and ids only (checked: no long text, no nested document text)."""
    conn = conn or connect()
    ensure_schema(conn)
    _check_role(role_no)
    _check(state, ROLE_STATES, "state")
    why = _short_why(why, conn, run_id)
    if state != "ran" and not why:
        raise ValueError(f"role {role_no} did not run in full and gives no reason")
    if engine is not None:
        _check(engine, ENGINES, "engine")
    produced = _counts_only(produced or {})
    calls, usd, seen = role_calls(run_id, role_no, conn)
    models_all = sorted({*models, *seen})
    start_run(run_id, conn)
    with conn:
        conn.execute(
            f"UPDATE {ROLES_TABLE} SET state = ?, why = ?, engine = COALESCE(?, engine), models_json = ?, calls = ?, usd = ?,"
            f" finished_at = ?, produced_json = ? WHERE run_id = ? AND role_no = ?",
            (
                state,
                None if state == "ran" else why,
                engine,
                json.dumps(models_all),
                calls,
                usd,
                now(),
                json.dumps(produced, sort_keys=True),
                run_id,
                role_no,
            ),
        )


def role_calls(
    run_id: str, role_no: int, conn=None
) -> tuple[int, float | None, list[str]]:
    """(calls made, USD known so far or None when no call's cost is known, the models that answered). A call that was refused or
    failed before it was sent is not a call made."""
    conn = conn or connect()
    ensure_schema(conn)
    rows = conn.execute(
        f"SELECT state, usd, model FROM {CALLS_TABLE} WHERE run_id = ? AND role_no = ?",
        (run_id, role_no),
    ).fetchall()
    made = [r for r in rows if r["state"] in ("sent", "answered", "failed", "reused")]
    known = [r["usd"] for r in rows if r["usd"] is not None]
    return (
        len(made),
        (round(sum(known), 6) if known else None),
        sorted({r["model"] for r in made if r["model"]}),
    )


def role_spend(run_id: str, role_no: int, conn=None) -> float:
    """What the role's budget gate counts: known costs, and for a call of unknown cost (a failure after the body was sent) the amount
    that was RESERVED for it: conservative, never 0. A refused call counts nothing (it never left)."""
    conn = conn or connect()
    ensure_schema(conn)
    row = conn.execute(
        f"SELECT COALESCE(SUM(COALESCE(usd, usd_reserved, 0)), 0) FROM {CALLS_TABLE}"
        " WHERE run_id = ? AND role_no = ? AND state != 'refused'",
        (run_id, role_no),
    ).fetchone()
    return float(row[0])


def role_usd(run_id: str, role_no: int, conn=None) -> float:
    """What this role has cost in this run so far (known costs only): the role gate's own meter."""
    return role_calls(run_id, role_no, conn)[1] or 0.0


# ----------------------------------------------------------------------------------------------------------- calls


def call_sent(
    run_id: str,
    role_no: int,
    call_id: str,
    *,
    step: str,
    engine: str,
    model: str,
    request_sha256: str,
    reads: list[ReadEntry],
    question_id: str | None = None,
    system_id: str | None = None,
    params_sha256: str | None = None,
    cells: list[CellEntry] | tuple[CellEntry, ...] = (),
    ranges: list | tuple = (),
    conn=None,
) -> None:
    """The `sent` row, one read row per document block of the request and one cell row per cell of a derived block, in ONE transaction. Written when the body is about to be
    handed to the transport, AFTER the spend reservation succeeded: a call refused at the reservation never has these rows."""
    conn = conn or connect()
    ensure_schema(conn)
    _check_role(role_no)
    _check(engine, ENGINES, "engine")
    for r in reads:
        _check(r.document_kind, KINDS, "document_kind")
        if r.role_no != role_no or r.call_id != call_id:
            raise ValueError("a read entry names another role or call")
    with conn:
        conn.execute(
            f"INSERT INTO {CALLS_TABLE} (run_id, role_no, call_id, step, engine, model, request_sha256, state, question_id, system_id,"
            " params_sha256, sent_at) VALUES (?,?,?,?,?,?,?,'sent',?,?,?,?)",
            (
                run_id,
                role_no,
                call_id,
                step,
                engine,
                model,
                request_sha256,
                question_id,
                system_id,
                params_sha256,
                now(),
            ),
        )
        for c in cells:
            _check(c.kind, CELL_KINDS, "cell kind")
            conn.execute(
                f"INSERT INTO {CELLS_TABLE} (run_id, role_no, call_id, block_name, row_no, col_no, kind, chars, cell_sha256,"
                " source_document_id, source_page, span_start, span_len) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    role_no,
                    call_id,
                    c.block_name,
                    c.row_no,
                    c.col_no,
                    c.kind,
                    c.chars,
                    c.cell_sha256,
                    c.source_document_id,
                    c.source_page,
                    c.span_start,
                    c.span_len,
                ),
            )
        for seq, r in enumerate(reads):
            conn.execute(
                f"INSERT INTO {READS_TABLE} (run_id, role_no, call_id, seq, document_id, document_kind, pages_json, chapter_id,"
                " part_no, part_of, chars, text_sha256, pictures, char_from, char_to) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    role_no,
                    call_id,
                    seq,
                    r.document_id,
                    r.document_kind,
                    json.dumps(list(r.pages)),
                    r.chapter_id,
                    r.part_no,
                    r.part_of,
                    r.chars,
                    r.text_sha256,
                    r.pictures,
                    (ranges[seq] or (None, None))[0] if seq < len(ranges) else None,
                    (ranges[seq] or (None, None))[1] if seq < len(ranges) else None,
                ),
            )


def call_refused(
    run_id: str,
    role_no: int,
    call_id: str,
    *,
    step: str,
    engine: str,
    model: str,
    error_code: str,
    conn=None,
) -> None:
    """A call that never left (a gate, a budget, no block left): state `refused`, no digest, no cost, no read row, no ledger line."""
    conn = conn or connect()
    ensure_schema(conn)
    _check_role(role_no)
    with conn:
        conn.execute(
            f"INSERT INTO {CALLS_TABLE} (run_id, role_no, call_id, step, engine, model, request_sha256, state, error_code, sent_at)"
            " VALUES (?,?,?,?,?,?,?,'refused',?,?)",
            (run_id, role_no, call_id, step, engine, model, "", error_code, now()),
        )


def call_end(
    run_id: str,
    call_id: str,
    state: str,
    *,
    error_code: str | None = None,
    usd: float | None = None,
    usd_reserved: float | None = None,
    model: str | None = None,
    conn=None,
) -> None:
    """The end state of a call. `model` is the model that ANSWERED (from the reply), when it is known. `usd_reserved`: the amount held
    for a call whose cost is not known (a failure after the body was sent); the role budget counts it, the role's `usd` does not."""
    conn = conn or connect()
    ensure_schema(conn)
    _check(state, CALL_STATES, "state")
    if state == "sent":
        raise ValueError("a call ends answered, failed, refused or reused")
    if usd is not None and usd < 0:
        raise ValueError("a cost is never negative")
    with conn:
        conn.execute(
            f"UPDATE {CALLS_TABLE} SET state = ?, error_code = ?, usd = ?, usd_reserved = ?,"
            " model = COALESCE(?, model) WHERE run_id = ? AND call_id = ?",
            (state, error_code, usd, usd_reserved, model, run_id, call_id),
        )


# ---------------------------------------------------------------------------------------------------------- reading


def load_record(run_id: str, conn=None) -> ReviewRecord | None:
    """The whole record of a run as the shared shapes, or None for a run that has no role rows (every review before this)."""
    conn = conn or connect()
    if not _has(conn, ROLES_TABLE):
        return None
    rows = conn.execute(
        f"SELECT * FROM {ROLES_TABLE} WHERE run_id = ? ORDER BY role_no", (run_id,)
    ).fetchall()
    if not rows:
        return None
    reads = _reads(conn, run_id)
    roles = tuple(
        RoleRecord(
            role_no=r["role_no"],
            role=r["role"],
            state=r["state"],
            why=r["why"],
            engine=r["engine"],
            models=tuple(json.loads(r["models_json"] or "[]")),
            calls=r["calls"],
            usd=r["usd"],
            produced=json.loads(r["produced_json"] or "{}"),
            reads=tuple(e for e in reads if e.role_no == r["role_no"]),
            started_at=r["started_at"],
            finished_at=r["finished_at"],
        )
        for r in rows
    )
    calls = (
        tuple(
            CallEntry(
                role_no=c["role_no"],
                call_id=c["call_id"],
                step=c["step"],
                engine=c["engine"],
                model=c["model"],
                request_sha256=c["request_sha256"],
                state=c["state"],
                error_code=c["error_code"],
                usd=c["usd"],
                sent_at=c["sent_at"],
            )
            for c in conn.execute(
                f"SELECT * FROM {CALLS_TABLE} WHERE run_id = ? ORDER BY sent_at, call_id",
                (run_id,),
            )
        )
        if _has(conn, CALLS_TABLE)
        else ()
    )
    paper, choice, shown = _run_facts(conn, run_id)
    return ReviewRecord(
        run_id=run_id,
        paper_id=paper,
        engine_choice=choice,
        roles=roles,
        calls=calls,
        shown_document_ids=shown,
    )


def _reads(conn, run_id: str) -> list[ReadEntry]:
    if not _has(conn, READS_TABLE):
        return []
    return [
        ReadEntry(
            role_no=r["role_no"],
            call_id=r["call_id"],
            document_id=r["document_id"],
            document_kind=r["document_kind"],
            pages=tuple(json.loads(r["pages_json"] or "[]")),
            chapter_id=r["chapter_id"],
            part_no=r["part_no"],
            part_of=r["part_of"],
            chars=r["chars"],
            text_sha256=r["text_sha256"],
            pictures=r["pictures"],
        )
        for r in conn.execute(
            f"SELECT * FROM {READS_TABLE} WHERE run_id = ? ORDER BY role_no, call_id, seq",
            (run_id,),
        )
    ]


def _run_facts(conn, run_id: str):
    """(paper id, engine choice, the stored shown list or None): read, never invented."""
    paper = ""
    try:
        row = conn.execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        paper = (row["submittal_document_id"] if row else "") or ""
    except sqlite3.Error:
        pass
    choice = "automatic"
    try:
        row = conn.execute(
            "SELECT choice FROM review_engine_choice WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row and row["choice"] in ("automatic", "claude", "local"):
            choice = row["choice"]
    except sqlite3.Error:
        pass
    shown = None
    try:
        from . import review_shown

        got = review_shown.shown_ids(conn, run_id)
        shown = None if got is None else tuple(sorted(got))
    except sqlite3.Error:
        pass
    return paper, choice, shown


# --------------------------------------------------------------------------------------------------------- helpers


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _check_role(role_no: int) -> None:
    if role_no not in ROLE_NAMES:
        raise ValueError(f"no role {role_no!r}")


def _check(value, allowed, what: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {what} {value!r}")


MAX_WHY = 120  # a reason is a code or one short plain sentence: never document text


def cells_of(run_id: str, call_id: str, conn=None) -> list[CellEntry]:
    """The cell rows written for one call, in order."""
    conn = conn or connect()
    ensure_schema(conn)
    return [
        CellEntry(
            r["block_name"],
            r["row_no"],
            r["col_no"],
            r["kind"],
            r["chars"],
            r["cell_sha256"],
            r["source_document_id"],
            r["source_page"],
            r["span_start"],
            r["span_len"],
        )
        for r in conn.execute(
            f"SELECT * FROM {CELLS_TABLE} WHERE run_id = ? AND call_id = ? ORDER BY block_name, row_no, col_no",
            (run_id, call_id),
        )
    ]


WHY_WITHHELD = "why_withheld_held_text"


def refused_documents(run_id: str, ids) -> dict[str, str]:
    """{document id: code} for each of `ids` the one approval gate refuses for a Claude call of this run."""
    from . import claude_approved

    out: dict[str, str] = {}
    for doc in dict.fromkeys(ids):
        with claude_approved.carrying([doc]), claude_approved.reviewing(run_id):
            found = claude_approved.refusal()
        if found is not None:
            out[doc] = found[0]
    return out


_SEPARATORS = re.compile(r"[\s\-_:.]+")


def hfold(text: str) -> str:
    """The folding of every HELD-TEXT comparison (cells, rows, parameters, reasons): lower case, and white space, hyphens, underscores,
    colons and full stops all as one space, so a sentence joined by `-` or `_` is still that sentence."""
    return _SEPARATORS.sub(" ", str(text).lower()).strip()


_HELD_TTL_SECONDS = 300.0
_HELD_CACHE: dict = {}


class _HeldIndex:
    """The folded stored text of every document the gate refuses for one run, built ONCE and reused: the folded pages, the set of their
    words, and a bit table of their word 3-grams (a prefilter: a probe whose first three words are not in it cannot be in the text)."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.words: set[str] = set()
        total = 0
        for t in texts:
            total += t.count(" ") + 1
        bits = 1 << max(20, min(30, (max(total, 1) * 32).bit_length()))
        self.mask = bits - 1
        self.table = bytearray(bits >> 3)
        for t in texts:
            ws = t.split()
            self.words.update(ws)
            for i in range(len(ws) - 2):
                three = " ".join(ws[i : i + 3])
                for h in (hash(three) & self.mask, hash(three + "\x00") & self.mask):
                    self.table[h >> 3] |= 1 << (h & 7)

    def maybe(self, three: str) -> bool:
        return all(
            self.table[h >> 3] & (1 << (h & 7))
            for h in (hash(three) & self.mask, hash(three + "\x00") & self.mask)
        )


def reset_held_cache() -> None:
    _HELD_CACHE.clear()


def _held_index(conn, run_id: str) -> _HeldIndex | None:
    """The index of the refused documents of this run, cached per run for five minutes and while the stored pages and the run's shown
    list stay as they were."""
    import time

    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    pages = conn.execute("SELECT COUNT(*), MAX(page_no) FROM pages").fetchone()
    try:
        listed = conn.execute(
            "SELECT documents_json FROM review_shown_lists WHERE run_id = ?", (run_id,)
        ).fetchone()
    except sqlite3.Error:
        listed = None
    key = (path, run_id, pages[0], pages[1], listed[0] if listed else None)
    hit = _HELD_CACHE.get(run_id)
    if hit and hit[0] == key and time.monotonic() - hit[1] < _HELD_TTL_SECONDS:
        return hit[2]
    docs = [r[0] for r in conn.execute("SELECT DISTINCT document_id FROM pages")]
    refused = set(refused_documents(run_id, docs))
    index = None
    if refused:
        texts = [
            hfold(r["text"])
            for r in conn.execute("SELECT document_id, text FROM pages")
            if r["document_id"] in refused
        ]
        index = _HeldIndex(texts)
    _HELD_CACHE.clear()
    _HELD_CACHE[run_id] = (key, time.monotonic(), index)
    return index


def held_text_hits(
    conn, run_id: str, values, *, min_chars: int = HELD_MIN_CHARS
) -> set[str]:
    """The first of `values` (of `min_chars` or more characters once folded by `hfold`) that occurs, folded the same way, in the stored
    text of a document the gate refuses for this run; an empty set when none does (a caller needs only whether any does). One index
    per run (`_HeldIndex`), built once: one word is looked up among the words, two words are scanned, three or more must pass the
    3-gram table on their first three whole words and are then confirmed by an exact scan."""
    probes = {v: hfold(v) for v in values}
    probes = {v: f for v, f in probes.items() if len(f) >= min_chars}
    if not probes:
        return set()
    index = _held_index(conn, run_id)
    if index is None:
        return set()
    for v, f in probes.items():
        words = f.split()
        if len(words) == 1:
            if f in index.words:
                return {v}
        elif len(words) == 2 or index.maybe(" ".join(words[:3])):
            if any(f in t for t in index.texts):
                return {v}
    return set()


WHY_CODES = frozenset(
    {
        "not_reached", "not reached", "no_stored_text", "no_block_left", "run_is_local", "no_engine_decision", "role_budget",
        "text_from_held_document", "cell_not_from_sources", "cell_not_in_vocabulary", "cell_wrong_kind", "no_model_answer",
        "model_failed", "budget_stop", "gate_closed", "not_on_list", "outside_access", "read_nothing",
    }
)  # fmt: skip


def _short_why(why: str | None, conn=None, run_id: str | None = None) -> str | None:
    """A reason is a code of the fixed set `WHY_CODES` or one short plain sentence. Anything else is checked, folded by `hfold`, against
    the stored text of every refused document: the whole of it, or any three consecutive words, found there replaces the reason by a
    code. One token of code shape is not exempt: only the fixed set is."""
    text = str(why or "").strip()
    if len(text) > MAX_WHY or "\n" in text or "\r" in text:
        raise ValueError(f"a reason is at most {MAX_WHY} characters on one line")
    if text and text not in WHY_CODES and conn is not None and run_id:
        words = hfold(text).split()
        windows = {" ".join(words[i : i + 3]) for i in range(max(1, len(words) - 2))}
        if held_text_hits(conn, run_id, windows | {text}):
            return WHY_WITHHELD
    return text or None


MAX_STRING = 80  # a produced value is a count, an id, a code or a short word: never document text


def _counts_only(produced: dict) -> dict:
    """`produced_json` holds counts and ids only. A long string or a nested dict is refused, so no document text can be written here."""
    out: dict = {}
    for key, value in produced.items():
        if not isinstance(key, str) or len(key) > MAX_STRING:
            raise ValueError("a produced key is a short name")
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and len(value) <= MAX_STRING:
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(v, (int, float)) or (isinstance(v, str) and len(v) <= MAX_STRING)
            for v in value
        ):
            out[key] = list(value)
        else:
            raise ValueError(f"produced {key!r} is not a count, an id or a short code")
    return out
