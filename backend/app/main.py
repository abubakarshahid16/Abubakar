from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import chunker as chunk_mod
from . import extract as extract_mod
from . import upload as upload_mod
from .config import settings
from .db import connect, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    yield


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
    }


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
def document_chunks(document_id: str, limit: int = 10, offset: int = 0):
    rows = connect().execute(
        """SELECT id, ordinal, page_start, page_end, section, kind, token_count,
                  content_hash, text
           FROM chunks WHERE document_id = ? ORDER BY ordinal LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]
