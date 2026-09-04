"""SQLite FTS5 keyword index.

Built immediately after chunking and BEFORE any embedding, because keyword
search needs no vectors. A 1,200-page specification is therefore answerable
seconds after upload, while embedding continues in the background and upgrades
retrieval from keyword-only to hybrid.

Tokenisation matters more here than it looks. Petroleum specifications are full
of identifiers - `API 610`, clause `5.3.2`, `ASTM A216 WCB`, `P-101A` - and the
default unicode61 tokenizer splits on `.` and `-`, turning `5.3.2` into three
separate tokens and destroying exactly the lookups lexical search exists to get
right. Those characters are kept inside tokens instead.
"""

from __future__ import annotations

import re
import sqlite3

from .db import connect
from .rates import Timer, rate

#: Keep `.`, `-`, `/` and `_` inside tokens so identifiers survive intact.
TOKENIZER = "unicode61 remove_diacritics 2 tokenchars '.-/_'"

SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    section,
    filename,
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    tokenize = "{TOKENIZER}"
);
"""

#: Matches an engineering identifier: API 610, 5.3.2, ASTM-A216, P-101A.
IDENTIFIER = re.compile(r"\b(?:[A-Z]{2,}[- ]?\d+[A-Za-z0-9.-]*|\d+(?:\.\d+){1,3})\b")


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    conn = conn or connect()
    conn.executescript(SCHEMA)
    conn.commit()


def index_document(
    document_id: str,
    advance_to: str | None = None,
    expect_status: str | None = None,
) -> dict:
    """(Re)build the keyword index for one document.

    Only retrievable chunks are indexed, so search can never return a chunk
    the quality gate or classifier excluded - the exclusion is enforced at
    index time rather than relying on every query remembering to filter.

    `advance_to` moves the document's status IN THE SAME TRANSACTION as the
    index write. Doing the work and advancing the state used to be two
    separate steps, which left a document with a fully built, searchable
    index still sitting at `indexing_keyword` - so embedding never started
    and the document was stranded. Either both happen or neither does.
    """
    timer = Timer()
    conn = connect()
    ensure_schema(conn)

    rows = conn.execute(
        """SELECT id, text, section, filename FROM chunks
           WHERE document_id = ? AND retrievable = 1 ORDER BY ordinal""",
        (document_id,),
    ).fetchall()

    with conn:
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO chunks_fts (text, section, filename, chunk_id, document_id)
               VALUES (?, ?, ?, ?, ?)""",
            [(r["text"], r["section"] or "", r["filename"], r["id"], document_id) for r in rows],
        )
        if advance_to is not None:
            # compare-and-set, so a concurrent change cannot be overwritten
            if expect_status is None:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (advance_to, document_id),
                )
            else:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ? AND status = ?",
                    (advance_to, document_id, expect_status),
                )

    elapsed = timer.seconds()
    return {
        "document_id": document_id,
        "indexed": len(rows),
        "seconds": elapsed,
        "chunks_per_sec": rate(len(rows), elapsed),
    }


def indexed_count(document_id: str | None = None) -> int:
    conn = connect()
    ensure_schema(conn)
    if document_id is None:
        return conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE document_id = ?", (document_id,)
    ).fetchone()[0]


def drop_document(document_id: str) -> None:
    conn = connect()
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))


# ------------------------------------------------------------------ querying


def _escape(token: str) -> str:
    """FTS5 treats several characters as syntax. Quote every token."""
    return '"' + token.replace('"', '""') + '"'


def build_match_query(question: str) -> str:
    """Turn a natural question into an FTS5 MATCH expression.

    Identifiers are required rather than merely preferred: a question naming
    `API 610` is asking about API 610, and a passage that does not mention it
    is not an answer. Remaining words are OR-ed so a partial match still
    returns something rather than nothing.
    """
    identifiers = IDENTIFIER.findall(question)
    words = [w for w in re.findall(r"[\w.\-/]{2,}", question) if w not in identifiers]

    parts: list[str] = []
    if identifiers:
        parts.append(" AND ".join(_escape(i) for i in identifiers))
    if words:
        ors = " OR ".join(_escape(w) for w in words)
        parts.append(f"({ors})")
    if not parts:
        return ""
    return " AND ".join(parts)


def search(
    question: str,
    limit: int = 30,
    document_id: str | None = None,
) -> list[dict]:
    """Keyword search over retrievable chunks. bm25: lower is better."""
    match = build_match_query(question)
    if not match:
        return []

    conn = connect()
    ensure_schema(conn)
    params: list[object] = [match]
    where = "chunks_fts MATCH ?"
    if document_id:
        where += " AND document_id = ?"
        params.append(document_id)
    params.append(limit)

    try:
        rows = conn.execute(
            f"""SELECT chunk_id, document_id, filename, section,
                       bm25(chunks_fts, 4.0, 2.0, 1.0) AS score
                FROM chunks_fts
                WHERE {where}
                ORDER BY score LIMIT ?""",
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        # a malformed MATCH expression must not 500 the API
        return []

    return [
        {
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "filename": r["filename"],
            "section": r["section"] or None,
            "bm25": r["score"],
        }
        for r in rows
    ]
