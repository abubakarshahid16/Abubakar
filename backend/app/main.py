from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
