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
    status            TEXT NOT NULL DEFAULT 'queued',
    needs_ocr_pages   INTEGER NOT NULL DEFAULT 0,
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
    kind           TEXT NOT NULL DEFAULT 'prose',
    text           TEXT NOT NULL,
    token_count    INTEGER NOT NULL,
    content_hash   TEXT NOT NULL
);

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


def init_db(path: Path | None = None) -> None:
    if path is not None:
        settings.db_path = path
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()


def reset_connection() -> None:
    """Test helper - drop the thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
