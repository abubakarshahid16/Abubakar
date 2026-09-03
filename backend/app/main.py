from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import chunker as chunk_mod
from . import ingest as ingest_mod
from . import extract as extract_mod
from . import upload as upload_mod
from .config import settings
from .db import connect, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    # Drain the upload queue. Without this a document sits at 'queued'
    # forever while the API reports a job id that means nothing.
    ingest_mod.start_worker()
    yield
    ingest_mod.stop_worker()


app = FastAPI(title="Nabaa", version="0.1.0", lifespan=lifespan)

# Vite dev server only. No wildcard - this API serves document content.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    """Readiness without loading any model."""
    return {
        "ok": True,
        "embed_model_present": (settings.embed_model_dir / "tokenizer.json").exists(),
        "answer_model": settings.answer_model,
        "ingestion": ingest_mod.get_worker().status(),
    }


@app.get("/api/documents/{document_id}/excluded")
def document_excluded(document_id: str, limit: int = 50, offset: int = 0):
    """Everything excluded from search, with the rule that excluded it.

    Nothing is dropped silently: every excluded page and chunk is recorded
    here with its reason and the text that was dropped.
    """
    conn = connect()
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
        return JSONResponse(status_code=404,
                            content={"code": "not_found", "message": "unknown document"})
    summary = [
        dict(r) for r in conn.execute(
            """SELECT scope, rule, COUNT(*) AS count,
                      SUM(text_length) AS characters_dropped
               FROM exclusions WHERE document_id = ?
               GROUP BY scope, rule ORDER BY count DESC""",
            (document_id,),
        )
    ]
    rows = conn.execute(
        """SELECT scope, page_start, page_end, chunk_id, rule, reason,
                  text_length, text_sample
           FROM exclusions WHERE document_id = ?
           ORDER BY page_start, id LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM exclusions WHERE document_id = ?", (document_id,)
    ).fetchone()[0]
    return {"total": total, "summary": summary, "limit": limit, "offset": offset,
            "excluded": [dict(r) for r in rows]}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    """Stream a PDF to disk. Returns the document record and a job id."""
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as e:
        return JSONResponse(
            status_code=400,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )
    return {
        "document": upload_mod.to_api(row),
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
    }


@app.get("/api/documents")
def list_documents():
    rows = connect().execute(
        "SELECT * FROM documents ORDER BY uploaded_at DESC"
    ).fetchall()
    return [upload_mod.to_api(r) for r in rows]


@app.post("/api/documents/{document_id}/extract")
def extract(document_id: str):
    """Extract pages in batches. Resumes from the last completed batch."""
    try:
        return extract_mod.extract_document(document_id)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"code": "not_found", "message": str(e)})


@app.post("/api/extract-all")
def extract_all():
    """Extract every queued or partially extracted document."""
    rows = connect().execute(
        "SELECT id FROM documents WHERE status IN ('queued','extracting') ORDER BY size_bytes"
    ).fetchall()
    return [extract_mod.extract_document(r["id"]) for r in rows]


@app.get("/api/documents/{document_id}/pages")
def document_pages(document_id: str, limit: int = 20, offset: int = 0):
    """Page-level extraction results, so extraction can be inspected."""
    rows = connect().execute(
        """SELECT page_no, char_count, needs_ocr, batch_no, substr(text,1,300) AS preview
           FROM pages WHERE document_id = ? ORDER BY page_no LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/documents/{document_id}/chunk")
def chunk(document_id: str):
    """Chunk an extracted document. Idempotent - re-running replaces rows."""
    try:
        return chunk_mod.chunk_document(document_id)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"code": "not_found", "message": str(e)})


@app.get("/api/documents/{document_id}/chunks")
def document_chunks(
    document_id: str,
    limit: int = 20,
    offset: int = 0,
    retrievable: str = "true",
):
    """Chunks for a document.

    retrievable = "true"  (default) only chunks search can see
                  "false"           only the excluded ones, for inspection
                  "all"             everything
    """
    clause = {"true": " AND retrievable = 1", "false": " AND retrievable = 0", "all": ""}
    if retrievable not in clause:
        return JSONResponse(
            status_code=400,
            content={"code": "internal", "message": "retrievable must be true, false or all"},
        )
    rows = connect().execute(
        f"""SELECT id, ordinal, page_start, page_end, section, kind, token_count,
                   content_hash, retrievable, quality_flags, text
            FROM chunks WHERE document_id = ?{clause[retrievable]}
            ORDER BY ordinal LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    total = connect().execute(
        f"SELECT COUNT(*) FROM chunks WHERE document_id = ?{clause[retrievable]}",
        (document_id,),
    ).fetchone()[0]
    return {
        "total_matching": total,
        "limit": limit,
        "offset": offset,
        "chunks": [dict(r) | {"retrievable": bool(r["retrievable"])} for r in rows],
    }
