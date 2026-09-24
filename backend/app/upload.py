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

from . import access, classification, job_queue, states
from .config import settings
from .db import connect
from .errors import redact

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
#: Every OOXML file is a zip, so this proves only "a zip", never "a workbook".
#: `.docx`, `.pptx` and `.jar` open with the same four bytes, which is why the
#: magic check below is a GATE and not the validation - see `validate_xlsx`.
ZIP_MAGIC = b"PK\x03\x04"

#: What an upload may be. The stored suffix is derived from this rather than
#: from the filename, which is user-supplied text.
KIND_PDF = "pdf"
KIND_XLSX = "xlsx"
_SUFFIX_FOR_KIND = {KIND_PDF: ".pdf", KIND_XLSX: ".xlsx"}

#: The entry every real workbook has and no `.docx` or `.pptx` does.
_XLSX_REQUIRED_ENTRY = "xl/workbook.xml"

#: Ceiling on the TOTAL UNCOMPRESSED size of a workbook's entries.
#:
#: A zip bomb is small on disk and enormous when expanded, so a size limit on
#: the uploaded bytes does not bound it at all - the 512 MB upload ceiling is
#: no protection against a 40 KB file that expands to gigabytes. The declared
#: sizes in the central directory are read WITHOUT decompressing anything, and
#: a workbook that claims more than this is REFUSED rather than opened. A real
#: CRS template is a form of a few hundred kilobytes; 256 MB is far above any
#: legitimate one and far below what would hurt this machine.
MAX_XLSX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

#: A bound on the number of entries as well, because ten thousand tiny files
#: costs nothing in declared size and everything in syscalls.
MAX_XLSX_ENTRIES = 5_000

_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


class UploadError(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def sanitise_filename(raw: str, kind: str = KIND_PDF) -> str:
    """Filenames are display metadata only. Strip any path, keep it printable.

    `kind` defaults to `pdf`, so the single-argument behaviour is EXACTLY what
    it has always been - `test_upload.py` pins it, and the PDF path is
    deliberately unchanged by the workbook work.

    The suffix comes from the VALIDATED kind, never from what the caller named
    the file. A `.pdf` that is really a workbook is stored as `.xlsx`, and a
    `.xlsx` that is really a PDF is stored as `.pdf`, because the bytes decide.
    """
    suffix = _SUFFIX_FOR_KIND.get(kind, ".pdf")
    name = raw.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\x00", "")
    name = _SAFE.sub("_", name).strip(" .")
    if not name:
        name = f"document{suffix}"
    if not name.lower().endswith(suffix):
        name += suffix
    return name[:200]


def validate_xlsx(temp_path: Path) -> None:
    """Prove a zip is really a workbook, and that opening it is bounded.

    `PK\\x03\\x04` says "zip" and nothing more; `.docx`, `.pptx` and `.jar`
    share it. A workbook is identified by an ENTRY IT MUST CONTAIN, which is
    the part a renamed `.docx` cannot fake.

    NOTHING IS DECOMPRESSED HERE. `ZipFile.infolist()` reads the central
    directory, so the declared sizes are checked before any expansion, and a
    decompression bomb is refused rather than expanded and then noticed. The
    declared size is what a bomb lies about - but lying LOW does not help an
    attacker, because the real expansion never happens: this module stores the
    original bytes and never reads the workbook again.

    Raises `UploadError`; the caller deletes the temp file, so a file that
    fails any check is never partially stored.
    """
    import zipfile

    try:
        with zipfile.ZipFile(temp_path) as book:
            entries = book.infolist()
            if len(entries) > MAX_XLSX_ENTRIES:
                raise UploadError(
                    "not_xlsx",
                    "That workbook has too many internal parts to be genuine",
                    f"{len(entries)} entries, limit {MAX_XLSX_ENTRIES}",
                )
            declared = sum(e.file_size for e in entries)
            if declared > MAX_XLSX_UNCOMPRESSED_BYTES:
                raise UploadError(
                    "not_xlsx",
                    "That workbook expands to more than this system accepts",
                    f"declared {declared} bytes, limit {MAX_XLSX_UNCOMPRESSED_BYTES}",
                )
            names = {e.filename for e in entries}
            # An .xlsm is a structurally valid workbook - it has
            # xl/workbook.xml and would otherwise pass every check here. The
            # macro part is the only thing that distinguishes it, and it is
            # the whole reason to refuse it: a macro is code, and this system
            # hands stored files back to a browser and to engineers who will
            # open them in Excel. Refused whatever the file is named.
            if any(n.lower().startswith("xl/vbaproject") for n in names):
                raise UploadError(
                    "not_xlsx",
                    "Macro-enabled workbooks are not accepted",
                    "the file contains a VBA project",
                )
            if _XLSX_REQUIRED_ENTRY not in names:
                # A .docx or .pptx reaches exactly here: a valid zip, sane
                # sizes, and no workbook part.
                raise UploadError(
                    "not_xlsx",
                    "That file is not an Excel workbook",
                    f"no {_XLSX_REQUIRED_ENTRY} entry",
                )
    except zipfile.BadZipFile as exc:
        # NOT `not_xlsx`. This file opened with `PK\x03\x04` and then failed to
        # be a zip at all, so calling it a bad *workbook* claims to know more
        # about it than we do - four bytes of coincidence is not a declaration
        # of intent. It is simply not a file this system accepts, which is what
        # `not_pdf` has always meant for the overwhelmingly common case, and
        # what `test_non_pdf_is_rejected_and_leaves_nothing_behind` asserts.
        #
        # A file that IS a readable zip and is not a workbook - a .docx, a
        # .pptx - gets `not_xlsx` above, because there the intent is clear and
        # the precise message is the useful one.
        raise UploadError(
            "not_pdf",
            "That file is not a PDF",
            f"opened as a zip but could not be read: {exc}",
        ) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def detect_kind(temp_path: Path) -> str:
    """`pdf` or `xlsx`, from the first bytes of the STORED file.

    Separate from `stream_to_temp` so that function keeps its two-value return
    and its existing callers and tests are untouched. Reading four bytes back
    off a file that was just written is free.
    """
    with open(temp_path, "rb") as fh:
        head = fh.read(len(ZIP_MAGIC))
    return KIND_XLSX if head.startswith(ZIP_MAGIC) else KIND_PDF


def stream_to_temp(src: BinaryIO, temp_path: Path) -> tuple[str, int]:
    """Write src to temp_path in fixed blocks, hashing as we go.

    Returns `(sha256_hex, bytes_written)`. Never reads the whole file.

    THE MAGIC CHECK IS STILL ON THE FIRST BLOCK AND STILL REFUSES BEFORE
    STORING. The PDF branch is byte-for-byte the behaviour it always had,
    including the `not_pdf` code and the `magic bytes were ...` detail; a
    workbook is a second accepted opening rather than a relaxation of the
    first. Anything that is neither is still refused as `not_pdf`, because
    "that file is not a PDF" is the true and useful sentence for the
    overwhelmingly common case.

    A zip opening is only PROVISIONALLY a workbook here. `PK\\x03\\x04` is
    shared with `.docx`, `.pptx` and `.jar`, so the caller must run
    `validate_xlsx` on the completed file before storing it. Doing that here
    is impossible: the file is not finished being written yet.
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
                if not (block.startswith(PDF_MAGIC) or block.startswith(ZIP_MAGIC)):
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


def ingest(src: BinaryIO, raw_filename: str, *,
           priority: int = job_queue.PRIORITY_INTERACTIVE,
           ) -> tuple[sqlite3.Row, str | None, str | None]:
    """Stream, validate, hash, dedupe, store, record.

    Returns (document_row, job_id, duplicate_of).

    PRIORITY (#177) defaults to INTERACTIVE because the one caller that does
    not say otherwise is `POST /api/documents` - a person at the upload
    screen, waiting for their document to become answerable. The watched
    folder passes BACKFILL (`watcher.FolderWatcher._handle`): it ingests
    whatever lands in a drop folder, typically a bulk load of historical
    files, and nobody is waiting on any one of them. The worker takes higher
    priority first, so an upload is not stuck behind hundreds of backfilled
    documents. A DUPLICATE keeps the priority its first upload gave it - the
    existing row is returned untouched, the same as every other field.
    """
    settings.ensure_dirs()
    temp_path = settings.upload_dir / f".incoming-{uuid.uuid4().hex}.part"

    try:
        sha256, size = stream_to_temp(src, temp_path)
        kind = detect_kind(temp_path)
        if kind == KIND_XLSX:
            # Run on the COMPLETED temp file, before anything is stored. A
            # file that fails here is deleted by the except below and never
            # reaches the upload directory, so a rejected upload leaves
            # nothing behind to be found or served later.
            validate_xlsx(temp_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    # Named from the VALIDATED kind, not from what the caller called the file.
    filename = sanitise_filename(raw_filename, kind)

    existing = find_by_hash(sha256)
    if existing is not None:
        temp_path.unlink(missing_ok=True)
        return existing, None, existing["id"]

    final_path = settings.upload_dir / f"{sha256}{_SUFFIX_FOR_KIND[kind]}"
    # THE ORIGINAL IS NEVER REWRITTEN. Storage is content-addressed, so an
    # existing file at this path holds bytes whose SHA-256 is this name - the
    # same bytes being uploaded. Replacing it would be a no-op in the good case
    # and a silent corruption in every other one (a truncated temp file, a
    # hash collision, a future caller that computes the name differently), and
    # nothing downstream would report it: extraction, page images and every
    # citation would simply start describing a different document under the
    # same id. Master-plan section 27: "Original uploaded files remain
    # immutable." Keeping the first copy is what makes that a property of the
    # code rather than a sentence in a document.
    if final_path.exists():
        temp_path.unlink(missing_ok=True)
    else:
        os.replace(temp_path, final_path)  # atomic within the same volume

    doc_id = f"doc_{sha256[:12]}"
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = connect()

    # ---------------------------------------------------------------------
    # A WORKBOOK IS STORED AND NEVER INDEXED. THIS IS A DECISION, NOT A CRASH.
    #
    # A CRS template is a FORM TO BE FILLED, not corpus content. Extracting it
    # would put spreadsheet scaffolding - blank cells, header rows, the word
    # "Remarks" - into the retrieval pool, where it can be returned as the
    # answer to an engineering question. That is worse than useless: it is a
    # citation to a document that asserts nothing.
    #
    # So the row is written in a TERMINAL state with NO extract job, and the
    # worker never sees it. The alternative - queue it and let `extract` fail
    # on a file PyMuPDF cannot open - would reach the same place by accident,
    # land it in `failed`, and tell an operator to go and fix something that is
    # working exactly as intended.
    #
    # `job_id` is None for the same reason: a job id is a promise that work is
    # happening, and none is.
    # ---------------------------------------------------------------------
    indexed = kind != KIND_XLSX
    status = states.QUEUED if indexed else states.STORED_NOT_INDEXED

    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status,
                uploaded_at, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, filename, sha256, size, str(final_path), status, now,
             priority),
        )
        if indexed:
            conn.execute(
                """INSERT INTO jobs
                   (id, document_id, stage, state, started_at, updated_at,
                    priority)
                   VALUES (?, ?, 'extract', 'running', ?, ?, ?)""",
                (job_id, doc_id, now, now, priority),
            )

    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if indexed:
        # Reads page 1 with PyMuPDF, which cannot open a workbook. Skipped
        # explicitly rather than relying on the function's own except clause:
        # "it happens to be caught" is not a design, and the log line it would
        # emit would report a failure that is not one.
        _suggest_classification(doc_id, filename, final_path)
    else:
        _suggest_workbook_classification(doc_id, filename)
    return row, (job_id if indexed else None), None


def _suggest_workbook_classification(doc_id: str, filename: str) -> None:
    """Classify a workbook from its FILENAME ALONE - there is no page 1.

    Still a suggestion and still never a confirmation: `confirmed_by` stays
    NULL and the document appears in the needs-classification queue like any
    other. A workbook is very likely a CRS template, but "very likely" is a
    guess, and this project shows a guess as a guess until a human confirms it.
    """
    try:
        suggestion = classification.suggest(
            filename, "", classification.register_revision())
        classification.write_suggestion(
            doc_id, suggestion,
            suggested_by=(classification.SOURCE_REGISTER
                          if suggestion.register_id else
                          classification.SOURCE_PATTERN if not suggestion.is_empty
                          else classification.SOURCE_NONE))
    except Exception:  # noqa: BLE001 - a suggestion must never fail an ingest
        log.warning("classification suggestion failed for %s", doc_id)


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
        import pymupdf

        with pymupdf.open(pdf_path) as document:
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
