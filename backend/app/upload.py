"""Step 1 - streaming PDF upload.

Streams to a temp file in fixed blocks, hashing in the same pass, so a
1000-page PDF never enters memory whole. Validates it is really a PDF,
sanitises the filename to display metadata only, deduplicates by SHA-256,
then atomically renames into place and records document + job rows.
"""

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from . import access, classification
from .config import settings
from .db import connect
from .errors import redact

log = logging.getLogger(__name__)

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
    _suggest_classification(doc_id, filename, final_path)
    return row, job_id, None


def _suggest_classification(doc_id: str, filename: str, pdf_path: Path) -> None:
    """Suggest what this document IS. Never confirms, never grants.

    ONE HOOK COVERS BOTH INGEST PATHS. The manual upload route and the watched
    folder both come through `ingest`, so suggesting here means neither can
    acquire a document the other classifies - which two call sites would
    eventually allow.

    SUGGESTION ONLY. `confirmed_by` stays NULL: confirming requires the admin
    capability, because a wrong classification misroutes searches for everyone
    rather than only for the person who uploaded. The needs-classification
    queue is what surfaces this to a human.

    NEVER RAISES INTO THE INGEST. A document that failed to be classified is
    still a document, and losing an upload over a suggestion would trade the
    valuable thing for the cheap one. It lands unclassified, which is a real
    state the queue already reports.

    EXISTING DOCUMENTS GET NOTHING. This runs on new ingests only;
    back-classifying the current corpus is a human-confirmed step and not a
    side effect of deploying this.
    """
    try:
        revision = classification.register_revision()
        first_page = _first_page_text(pdf_path)
        suggestion = classification.suggest(filename, first_page, revision)
        if suggestion.is_empty:
            # Nothing matched. Recorded anyway, with every field NULL, so the
            # document appears in the needs-classification queue rather than
            # being absent from it - "no row" and "no match" would otherwise
            # look identical to the UI.
            pass
        classification.write_suggestion(
            doc_id, suggestion,
            suggested_by=(classification.SOURCE_REGISTER
                          if suggestion.register_id else
                          classification.SOURCE_PATTERN if not suggestion.is_empty
                          else classification.SOURCE_NONE))
    except Exception:  # noqa: BLE001 - a suggestion must never fail an ingest
        log.warning("classification suggestion failed for %s", doc_id)


def _first_page_text(pdf_path: Path) -> str:
    """Page 1 only, and cheaply.

    Read here rather than waiting for extraction because the suggestion is
    wanted at upload time - the uploader should see what the system thinks it
    is while they are still looking at the screen. One page, so the cost is a
    single page parse and not a document.
    """
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            if document.page_count == 0:
                return ""
            return document.load_page(0).get_text() or ""
    except Exception:  # noqa: BLE001
        return ""


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
        "recognised_pages": row["recognised_pages"] if "recognised_pages" in row.keys() else 0,
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
        # The category, read from the grant tables. Not the filename: a file
        # called civil-Design-and-Construction.pdf is Civil because an
        # administrator granted it to Civil, and would be nothing otherwise.
        "disciplines": access.disciplines_for(row["id"]),
    }
