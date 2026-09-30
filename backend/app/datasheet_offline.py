"""The RULES datasheet reader run on one PDF file, with no project database.

WHY THIS EXISTS. `datasheets.extract_facts` is the rules reader, and every
filter that decides what becomes a fact (the value gate, furniture, tag rows,
dates, grid precedence, blank markers, row noise, create_fact's own
normalisation) lives inside it, in one place. A benchmark that re-implemented
that chain would measure a copy, and the copy would drift from the reader it
claims to measure (CLAUDE.md rule 8: a rule with two homes drifts).

So this module does NOT re-implement anything. It gives `extract_facts` what
an upload leaves behind - a `documents` row, one `pages` row and one
retrievable chunk per page - inside a PRIVATE, THROWAWAY SQLite file in a
temporary directory, runs the unchanged reader, reads the facts back and
deletes the directory. Nothing here changes how `extract_facts` behaves.

WHAT IT IS NOT:
  * It never opens the project's database: `settings.data_dir`, `db_path`
    and `upload_dir` point into the temporary directory for the duration of
    the call and are restored afterwards, with the thread's connection reset
    on the way in and out.
  * It runs no ingestion. The chunker, the OCR tier (`ocr.py`, which fills
    `page_ocr` during upload) and the embedder do not run, so a scanned page
    with no text layer reaches the rules reader with nothing to read - which
    is what the rules reader alone does with it. Callers that report numbers
    from this say so.
  * The reader's own flags are read from `settings` as they are, so the
    measurement is of the rules reader as configured. `reader_flags()` names
    them for the report.

Not thread-safe (it swaps process settings): for scripts and tests only.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

from . import datasheets, db, submittal_review
from .config import settings

#: The fact columns a caller gets back - what a reviewer sees of a fact.
FACT_COLUMNS = (
    "field_name", "field_label", "field_value", "raw_value", "raw_unit", "unit",
    "normalized_value", "normalized_unit", "value_min", "value_max", "is_blank",
    "blank_marker", "page", "value_column", "equipment_tag", "extraction_method",
    "validation_state",
)

_DOC_ID = "doc_offline_bench"
_STAMP = "2026-01-01T00:00:00Z"


def reader_flags() -> dict:
    """The settings that change what the rules reader does, as configured."""
    return {"geometry_reader_enabled": bool(settings.geometry_reader_enabled),
            "geometry_table_reader_enabled": bool(settings.geometry_table_reader_enabled)}


@contextlib.contextmanager
def _private_database():
    saved = (settings.data_dir, settings.db_path, settings.upload_dir)
    with tempfile.TemporaryDirectory(prefix="ds-offline-") as tmp:
        root = Path(tmp)
        db.reset_connection()
        settings.data_dir = root
        settings.db_path = root / "offline.sqlite"
        settings.upload_dir = root / "uploads"
        try:
            db.init_db()
            submittal_review.ensure_schema()
            submittal_review.migrate_facts_to_per_document()
            yield root
        finally:
            db.reset_connection()
            settings.data_dir, settings.db_path, settings.upload_dir = saved


def _register(pdf_path: Path) -> None:
    """A stored, chunked document, the way an upload leaves one: one
    retrievable chunk per page carrying the page's own text layer."""
    import pymupdf
    with pymupdf.open(str(pdf_path)) as pdf:
        texts = [page.get_text() for page in pdf]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,?,?,'ready',?,?)",
            (_DOC_ID, pdf_path.name, f"sha-{_DOC_ID}", pdf_path.stat().st_size,
             str(pdf_path), len(texts), _STAMP))
        for page_no, text in enumerate(texts, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)", (_DOC_ID, page_no, text, len(text)))
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                "section,kind,text,token_count,content_hash,retrievable)"
                " VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)",
                (f"{_DOC_ID}-c{page_no}", _DOC_ID, pdf_path.name, page_no, page_no,
                 page_no, text, f"h-{_DOC_ID}-{page_no}"))


def read_pdf_rules(pdf_path: str | Path) -> dict:
    """Run the unchanged rules reader over one PDF.

    Returns `{"facts": [...], "summary": <extract_facts' own result>,
    "flags": reader_flags()}`; each fact carries `FACT_COLUMNS`. Superseded
    rows are left out, as every reader of current facts leaves them out.
    """
    path = Path(pdf_path).resolve()
    with _private_database():
        _register(path)
        summary = datasheets.extract_facts(_DOC_ID, allowed_document_ids=frozenset({_DOC_ID}))
        rows = db.connect().execute(
            "SELECT " + ", ".join(FACT_COLUMNS) + " FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL"
            " ORDER BY page, rowid", (_DOC_ID,)).fetchall()
        facts = [dict(r) for r in rows]
    return {"facts": facts, "summary": summary, "flags": reader_flags()}
