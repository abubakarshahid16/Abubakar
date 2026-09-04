"""SQLite storage. WAL mode, foreign keys on, one connection per thread."""

import sqlite3
import threading
from pathlib import Path

from .config import settings

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id                TEXT PRIMARY KEY,
    filename          TEXT NOT NULL,
    sha256            TEXT NOT NULL UNIQUE,
    size_bytes        INTEGER NOT NULL,
    stored_path       TEXT NOT NULL,
    page_count        INTEGER,
    pages_done        INTEGER NOT NULL DEFAULT 0,
    chunk_count       INTEGER NOT NULL DEFAULT 0,
    chunk_count_total INTEGER NOT NULL DEFAULT 0,
    chunk_signature   TEXT,
    status            TEXT NOT NULL DEFAULT 'queued',
    needs_ocr_pages   INTEGER NOT NULL DEFAULT 0,
    equation_pages    INTEGER NOT NULL DEFAULT 0,
    error_code        TEXT,
    error_message     TEXT,
    uploaded_at       TEXT NOT NULL,
    indexed_at        TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id                    TEXT PRIMARY KEY,
    document_id           TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage                 TEXT NOT NULL DEFAULT 'extract',
    state                 TEXT NOT NULL DEFAULT 'running',
    pages_total           INTEGER,
    pages_done            INTEGER NOT NULL DEFAULT 0,
    last_completed_batch  INTEGER,
    retries               INTEGER NOT NULL DEFAULT 0,
    error_code            TEXT,
    error_message         TEXT,
    started_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no       INTEGER NOT NULL,
    text          TEXT NOT NULL,
    char_count    INTEGER NOT NULL,
    needs_ocr     INTEGER NOT NULL DEFAULT 0,
    equation_heavy INTEGER NOT NULL DEFAULT 0,
    batch_no      INTEGER NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    page_start     INTEGER NOT NULL,
    page_end       INTEGER NOT NULL,
    section        TEXT,
    -- The parent block this chunk came out of. Retrieval works on the small
    -- chunk; the reader is shown the surrounding block, because a clause cut
    -- between its table and its notes answers with the notes and leaves the
    -- figure behind. See expand_passage.
    parent_id      TEXT,
    kind           TEXT NOT NULL DEFAULT 'prose',
    text           TEXT NOT NULL,
    token_count    INTEGER NOT NULL,
    content_hash   TEXT NOT NULL,
    retrievable    INTEGER NOT NULL DEFAULT 1,
    quality_flags  TEXT
);

CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    dim          INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vectors_document ON chunk_vectors(document_id);

CREATE TABLE IF NOT EXISTS exclusions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    scope         TEXT NOT NULL,          -- 'page' | 'chunk'
    page_start    INTEGER,
    page_end      INTEGER,
    chunk_id      TEXT,
    rule          TEXT NOT NULL,          -- which rule excluded it
    reason        TEXT,                   -- the detail behind the rule
    text_sample   TEXT NOT NULL,          -- what was dropped
    text_length   INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    document_id   TEXT REFERENCES documents(id) ON DELETE SET NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    ordinal           INTEGER NOT NULL,
    role              TEXT NOT NULL,      -- 'user' | 'assistant'
    text              TEXT,               -- question, or answer; null on a refusal
    -- user rows only: what retrieval actually ran, after follow-up resolution,
    -- and which terms were carried in. Stored so the UI can show the reader
    -- what was assumed rather than silently reinterpreting the question.
    resolved_question TEXT,
    carried_terms     TEXT,               -- JSON array
    -- assistant rows only
    answer_type       TEXT,
    reason            TEXT,
    explains_id       TEXT REFERENCES messages(id) ON DELETE SET NULL,
    payload           TEXT,               -- JSON: passages, citations, timings
    created_at        TEXT NOT NULL,
    UNIQUE (conversation_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_exclusions_document ON exclusions(document_id, scope);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_pages_ocr ON pages(document_id, needs_ocr);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
"""


def connect() -> sqlite3.Connection:
    """Thread-local connection. WAL lets one writer and many readers coexist."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        settings.ensure_dirs()
        conn = sqlite3.connect(settings.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        _local.conn = conn
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations for databases created by an earlier build."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    if have and "retrievable" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN retrievable INTEGER NOT NULL DEFAULT 1")
    if have and "quality_flags" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN quality_flags TEXT")
    if have and "parent_id" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN parent_id TEXT")
    pg = {r["name"] for r in conn.execute("PRAGMA table_info(pages)")}
    if pg and "equation_heavy" not in pg:
        conn.execute("ALTER TABLE pages ADD COLUMN equation_heavy INTEGER NOT NULL DEFAULT 0")
    docs = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    if docs and "chunk_count_total" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN chunk_count_total INTEGER NOT NULL DEFAULT 0")
    if docs and "chunk_signature" not in docs:
        conn.execute("ALTER TABLE documents ADD COLUMN chunk_signature TEXT")
    if docs and "equation_pages" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN equation_pages INTEGER NOT NULL DEFAULT 0")
    if docs and "embedded_count" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN embedded_count INTEGER NOT NULL DEFAULT 0")
    # created after the migration so it cannot reference a missing column
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_retrievable ON chunks(retrievable)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id, ordinal)"
    )
    conn.commit()


def init_db(path: Path | None = None) -> None:
    if path is not None:
        settings.db_path = path
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def reset_connection() -> None:
    """Test helper - drop the thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
