from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
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
