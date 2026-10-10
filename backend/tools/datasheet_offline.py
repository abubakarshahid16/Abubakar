"""The datasheet reader run on one file, with no project database.

TWO ENTRY POINTS:

  * `read_file(path, office_input=..., ai_engine=..., model_call=None)` -
    THE PRODUCTION PATH, as a real upload runs it: `upload.ingest` (the
    upload's own validation and refusals), `extract.extract_document`,
    `chunker.chunk_document`, the OCR stage (`ocr.recognise_document`, then a
    re-chunk) for pages the project routes to recognition, then
    `datasheets.extract_facts` - with DATASHEET_OFFICE_INPUT and
    DATASHEET_AI_READER set for the run and restored afterwards, even on an
    exception. The keyword index and embedding are the only stages left out:
    neither feeds the fact reader.
  * `read_pdf_rules(pdf_path)` - the older, narrower measurement: the rules
    reader over one PDF registered with one chunk per page, no ingestion.
    Kept because earlier baselines were measured with it.

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

(The three points above describe `read_pdf_rules`. `read_file` does run the
ingestion stages, inside the same throwaway database.)

OCR IS REPORTED, NEVER SILENT. A page the project routes to recognition is
recognised only when the project's own engine can run here (`ocr_available`:
the `rapidocr` package and the vendored model files under
`settings.ocr_model_dir`). When it cannot, the file's status is
`ocr_unavailable` with the reason - a scanned datasheet that yields nothing is
never reported as a reader that read it and found nothing.

THE MODEL CALL. With `ai_engine` set and no `model_call`, the engine is the
one production resolves (`datasheet_ai.model_call_for`: Ollama through
`model_transport`, Claude through `claude_spend`'s USD caps). A `model_call`
handed in (a benchmark's counted call, a test's fake) replaces it for the run
through `datasheet_ai.using_model_call`; it never switches the reader on.

Not thread-safe (it swaps process settings): for scripts and tests only.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import tempfile
from pathlib import Path

from app import datasheets, db, submittal_review
from app.config import settings

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
    """The settings that change what the datasheet reader does, as configured."""
    return {"geometry_reader_enabled": bool(settings.geometry_reader_enabled),
            "geometry_table_reader_enabled": bool(settings.geometry_table_reader_enabled),
            "datasheet_office_input": bool(settings.datasheet_office_input),
            "datasheet_ai_reader": str(settings.datasheet_ai_reader)}


#: Environment names of the three paths, set for the run too: a worker
#: process started by `spawn` (Windows) builds its own settings from the
#: environment, and must render and cache into the throwaway directory, never
#: into the project's data directory.
_PATH_ENV = ("DATA_DIR", "DB_PATH", "UPLOAD_DIR")


@contextlib.contextmanager
def _private_database():
    saved = (settings.data_dir, settings.db_path, settings.upload_dir)
    saved_env = {name: os.environ.get(name) for name in _PATH_ENV}
    with tempfile.TemporaryDirectory(prefix="ds-offline-") as tmp:
        root = Path(tmp)
        db.reset_connection()
        settings.data_dir = root
        settings.db_path = root / "offline.sqlite"
        settings.upload_dir = root / "uploads"
        os.environ.update({"DATA_DIR": str(root), "DB_PATH": str(root / "offline.sqlite"),
                           "UPLOAD_DIR": str(root / "uploads")})
        try:
            db.init_db()
            submittal_review.ensure_schema()
            submittal_review.migrate_facts_to_per_document()
            yield root
        finally:
            db.reset_connection()
            settings.data_dir, settings.db_path, settings.upload_dir = saved
            for name, value in saved_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


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


# ================================================================ read_file

#: `read_file` statuses. Anything but READ is a file the run could not fully
#: read, and says why in `reason`.
READ = "read"
REFUSED = "refused_at_upload"
NOT_INDEXED = "stored_not_indexed"
OCR_UNAVAILABLE = "ocr_unavailable"
FAILED = "failed"

#: OCR rounds before giving up on pages that stay pending (each round reads
#: every pending page; a page is consumed even when it fails, so one round is
#: normally enough).
MAX_OCR_ROUNDS = 3

#: The extra columns `read_file` returns beside `FACT_COLUMNS`: the reader's
#: section (an AI fact's is `model:<kind>`) and its state and confidence.
FILE_FACT_COLUMNS = FACT_COLUMNS + ("section", "confidence")


def ocr_available() -> tuple[bool, str]:
    """(True, "") when the project's OCR engine can run here: the `rapidocr`
    package imports and every vendored model file `ocr._build_engine` loads is
    present under `settings.ocr_model_dir`. Otherwise (False, why)."""
    if importlib.util.find_spec("rapidocr") is None:
        return False, "the rapidocr package is not installed"
    folder = Path(settings.ocr_model_dir)
    missing = [name for name in (settings.ocr_det_model, settings.ocr_rec_model,
                                 settings.ocr_cls_model)
               if not (folder / name).is_file()]
    if missing:
        return False, f"OCR model file(s) missing from ocr_model_dir: {', '.join(missing)}"
    return True, ""


@contextlib.contextmanager
def _run_flags(*, office_input: bool, ai_engine: str | None):
    """DATASHEET_OFFICE_INPUT and DATASHEET_AI_READER for one run; the values
    they had are put back on the way out, whatever happens inside."""
    saved = (settings.datasheet_office_input, settings.datasheet_ai_reader)
    try:
        settings.datasheet_office_input = bool(office_input)
        settings.datasheet_ai_reader = (ai_engine or "off")
        yield
    finally:
        settings.datasheet_office_input, settings.datasheet_ai_reader = saved


def _ingest(path: Path, *, run_ocr: bool) -> dict:
    """The upload and ingestion stages a real upload runs before the fact
    reader, in the throwaway database. Returns `{"document_id", "status",
    "reason", "stages", "ocr"}`; never raises for the FILE's sake (a refusal,
    a failed stage) - that is the file's result."""
    from app import chunker, extract, ocr, states, upload

    out: dict = {"document_id": None, "status": READ, "reason": None,
                 "stages": [], "ocr": {"pages_needing_ocr": 0}}
    try:
        with path.open("rb") as fh:
            row, _job_id, _dup = upload.ingest(fh, path.name)
    except upload.UploadError as exc:
        out.update(status=REFUSED, reason=f"refused at upload ({exc.code}): {exc.message}")
        return out
    out["stages"].append("upload")
    out["document_id"] = row["id"]
    if row["status"] == states.STORED_NOT_INDEXED:
        out.update(status=NOT_INDEXED,
                   reason="stored and never indexed, as production stores a workbook "
                          "with DATASHEET_OFFICE_INPUT off")
        return out
    try:
        result = extract.extract_document(row["id"])
        if result.get("error"):
            out.update(status=FAILED, reason=f"extract stage: {result['error']}")
            return out
        out["stages"].append("extract")
        chunker.chunk_document(row["id"])
        out["stages"].append("chunk")
    except Exception as exc:  # noqa: BLE001 - a stage that fails is this file's result
        out.update(status=FAILED, reason=f"ingestion failed ({type(exc).__name__}: {exc})")
        return out
    pending = ocr.pending_pages(row["id"])
    out["ocr"]["pages_needing_ocr"] = len(pending)
    if not pending:
        return out
    ok, why = ocr_available() if run_ocr else (False, "OCR not run for this reading")
    if not ok:
        out["ocr"]["unavailable"] = why
        out.update(status=OCR_UNAVAILABLE,
                   reason=f"ocr unavailable: {len(pending)} page(s) need recognition "
                          f"and {why}")
        return out
    recognised = with_text = failed = 0
    for _round in range(MAX_OCR_ROUNDS):
        done = ocr.recognise_document(row["id"])
        recognised += done.get("pages_recognised", 0)
        with_text += done.get("pages_with_text", 0)
        failed += done.get("pages_failed", 0)
        if not ocr.pending_pages(row["id"]):
            break
    out["ocr"].update(pages_recognised=recognised, pages_with_text=with_text,
                      pages_failed=failed)
    out["stages"].append("ocr")
    if with_text:
        # Recognised text changes the chunk signature: the re-chunk is what
        # carries it to the fact reader, exactly as the ingest loop does.
        chunker.chunk_document(row["id"])
        out["stages"].append("chunk")
    return out


def read_file(path: str | Path, *, office_input: bool, ai_engine: str | None,
              model_call=None, run_ocr: bool = True) -> dict:
    """One datasheet through the production path (see the module doc).

    `office_input` is DATASHEET_OFFICE_INPUT for the run; `ai_engine` is
    DATASHEET_AI_READER ("ollama", "claude", or None for off); `model_call`
    (only with an engine) replaces the engine's call. Returns `{"status",
    "reason", "facts": [FILE_FACT_COLUMNS], "summary": extract_facts' result
    or None, "flags": the flags the run used, "stages", "ocr"}`. Superseded
    rows are left out. Settings and flags are restored afterwards.
    """
    from app import datasheet_ai

    if model_call is not None and not ai_engine:
        raise ValueError("a model_call needs an ai_engine: with the AI reader off it is never asked")
    source = Path(path).resolve()
    override = (datasheet_ai.using_model_call(model_call) if model_call is not None
                else contextlib.nullcontext())
    with _private_database(), _run_flags(office_input=office_input, ai_engine=ai_engine), override:
        flags = reader_flags()
        out = _ingest(source, run_ocr=run_ocr)
        facts: list[dict] = []
        summary = None
        doc_id = out["document_id"]
        if doc_id is not None and out["status"] in (READ, OCR_UNAVAILABLE):
            try:
                summary = datasheets.extract_facts(
                    doc_id, allowed_document_ids=frozenset({doc_id}))
            except Exception as exc:  # noqa: BLE001 - the reader failing is this file's result
                out.update(status=FAILED, reason=f"extract_facts failed ({type(exc).__name__}: {exc})")
            else:
                rows = db.connect().execute(
                    "SELECT " + ", ".join(FILE_FACT_COLUMNS) + " FROM submittal_facts"
                    " WHERE submittal_document_id = ? AND superseded_at IS NULL"
                    " ORDER BY page, rowid", (doc_id,)).fetchall()
                facts = [dict(r) for r in rows]
    return {"status": out["status"], "reason": out["reason"], "facts": facts,
            "summary": summary, "flags": flags, "stages": out["stages"], "ocr": out["ocr"]}
