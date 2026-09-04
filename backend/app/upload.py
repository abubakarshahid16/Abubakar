"""Step 1 - streaming PDF upload.

Streams to a temp file in fixed blocks, hashing in the same pass, so a
1000-page PDF never enters memory whole. Validates it is really a PDF,
sanitises the filename to display metadata only, deduplicates by SHA-256,
then atomically renames into place and records document + job rows.
"""

import hashlib
import os
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from .config import settings
from .db import connect
from .errors import redact

PDF_MAGIC = b"%PDF-"
_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


class UploadError(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def sanitise_filename(raw: str) -> str:
    """Filenames are display metadata only. Strip any path, keep it printable."""
    name = raw.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\x00", "")
    name = _SAFE.sub("_", name).strip(" .")
    if not name:
        name = "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:200]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stream_to_temp(src: BinaryIO, temp_path: Path) -> tuple[str, int]:
    """Write src to temp_path in fixed blocks, hashing as we go.

    Returns (sha256_hex, bytes_written). Never reads the whole file.
    """
    digest = hashlib.sha256()
    total = 0
    limit = settings.max_upload_mb * 1024 * 1024
    first = True

    with open(temp_path, "wb") as out:
        while True:
            block = src.read(settings.upload_chunk_bytes)
            if not block:
                break
            if first:
                if not block.startswith(PDF_MAGIC):
                    raise UploadError(
                        "not_pdf",
                        "That file is not a PDF",
                        f"magic bytes were {block[:5]!r}",
                    )
                first = False
            total += len(block)
            if total > limit:
                raise UploadError(
                    "too_large",
                    f"File exceeds the {settings.max_upload_mb} MB limit",
                )
            digest.update(block)
            out.write(block)

    if total == 0:
        raise UploadError("not_pdf", "The file was empty")
    return digest.hexdigest(), total


def find_by_hash(sha256: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
    ).fetchone()


def ingest(src: BinaryIO, raw_filename: str) -> tuple[sqlite3.Row, str | None, str | None]:
    """Stream, validate, hash, dedupe, store, record.

    Returns (document_row, job_id, duplicate_of).
    """
    settings.ensure_dirs()
    filename = sanitise_filename(raw_filename)
    temp_path = settings.upload_dir / f".incoming-{uuid.uuid4().hex}.part"

    try:
        sha256, size = stream_to_temp(src, temp_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    existing = find_by_hash(sha256)
    if existing is not None:
        temp_path.unlink(missing_ok=True)
        return existing, None, existing["id"]

    final_path = settings.upload_dir / f"{sha256}.pdf"
    os.replace(temp_path, final_path)  # atomic within the same volume

    doc_id = f"doc_{sha256[:12]}"
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (doc_id, filename, sha256, size, str(final_path), now),
        )
        conn.execute(
            """INSERT INTO jobs
               (id, document_id, stage, state, started_at, updated_at)
               VALUES (?, ?, 'extract', 'running', ?, ?)""",
            (job_id, doc_id, now, now),
        )

    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return row, job_id, None


def to_api(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "page_count": row["page_count"],
        "pages_done": row["pages_done"],
        "chunk_count": row["chunk_count"],
        "chunk_count_total": row["chunk_count_total"],
        "embedded_count": row["embedded_count"],
        "status": row["status"],
        "needs_ocr_pages": row["needs_ocr_pages"],
        "equation_pages": row["equation_pages"],
        "error": (
            {
                "code": row["error_code"],
                "message": redact(row["error_message"] or ""),
            }
            if row["error_code"]
            else None
        ),
        "uploaded_at": row["uploaded_at"],
        "indexed_at": row["indexed_at"],
    }
