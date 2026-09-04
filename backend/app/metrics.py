"""Everything the dashboard shows, and nothing it does not measure.

The rule for this whole module: a value that has not been measured is null,
and the screen says so. Never a zero standing in for "unknown", never a
last-known figure presented as current, never a rate derived from an interval
too short to divide by. Those three mistakes have all been made in this build
already, and a dashboard is where they do the most damage, because a number on
a dashboard is read as a fact.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

import httpx
import psutil

from . import states, telemetry
from .config import settings
from .db import connect

#: Ollama is a separate process. Asking it anything on a 15-second refresh has
#: to be cheap and has to fail fast, or a stopped Ollama would hang the whole
#: dashboard instead of being reported as stopped.
OLLAMA_TIMEOUT = 1.5

_process = psutil.Process()

#: psutil.cpu_percent(interval=None) reports usage SINCE THE PREVIOUS CALL, so
#: the very first call has no baseline and returns exactly 0.0. Reporting that
#: would put "CPU 0%" on the screen as a fact on first render. The first call
#: reports None instead, and the screen says it is not measured yet; from the
#: next refresh on it is a true interval average.
_cpu_measured_once = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def corpus() -> dict:
    conn = connect()
    docs = conn.execute(
        """SELECT COUNT(*) AS documents,
                  COALESCE(SUM(page_count), 0) AS pages_declared,
                  COALESCE(SUM(chunk_count), 0) AS chunks_retrievable,
                  COALESCE(SUM(chunk_count_total), 0) AS chunks_total,
                  COALESCE(SUM(embedded_count), 0) AS embedded
           FROM documents"""
    ).fetchone()
    pages_extracted = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    chunks_rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vectors = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    indexed = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
        )
    }
    return {
        "documents": docs["documents"],
        "by_status": by_status,
        # Declared by the PDF manifest vs actually extracted. They differ while
        # a document is still processing, and showing only one would hide that.
        "pages_declared": docs["pages_declared"],
        "pages_extracted": pages_extracted,
        "chunks_total": chunks_rows,
        "chunks_retrievable": docs["chunks_retrievable"],
        "chunks_excluded": max(0, chunks_rows - docs["chunks_retrievable"]),
        "chunks_indexed_keyword": indexed,
        "chunks_embedded": vectors,
    }


def exclusions() -> list[dict]:
    """What search cannot see, and which rule excluded it."""
    return [
        dict(r)
        for r in connect().execute(
            """SELECT scope, rule, COUNT(*) AS count,
                      COALESCE(SUM(text_length), 0) AS characters_dropped
               FROM exclusions GROUP BY scope, rule ORDER BY count DESC"""
        )
    ]


def jobs() -> dict:
    conn = connect()
    by_state = {
        r["state"]: r["n"]
        for r in conn.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state")
    }
    failures = [
        dict(r)
        for r in conn.execute(
            """SELECT id, filename, error_code, error_message, uploaded_at
               FROM documents WHERE status = ? ORDER BY uploaded_at DESC LIMIT 20""",
            (states.FAILED,),
        )
    ]
    return {
        "by_state": by_state,
        "running": by_state.get("running", 0),
        "failed_documents": len(failures),
        "failures": failures,
    }


def system() -> dict:
    """CPU, memory and disk. Measured, including this process's own footprint.

    cpu_percent is called without an interval so it never blocks the request;
    it reports usage since the previous call, which on a 15-second refresh is
    a 15-second average. The field name says so.
    """
    global _cpu_measured_once
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(settings.data_dir)
    cpu = psutil.cpu_percent(interval=None)
    if not _cpu_measured_once:
        _cpu_measured_once = True
        cpu = None
    return {
        "cpu_percent_since_last_call": cpu,
        "cpu_logical_cores": psutil.cpu_count(logical=True),
        "cpu_physical_cores": psutil.cpu_count(logical=False),
        "ram_total_bytes": memory.total,
        "ram_used_bytes": memory.total - memory.available,
        "ram_percent": memory.percent,
        "process_rss_bytes": _process.memory_info().rss,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_percent": round(100 * disk.used / disk.total, 1) if disk.total else None,
        "data_dir_bytes": _directory_size(),
    }


def _directory_size() -> int:
    total = 0
    if not settings.data_dir.exists():
        return 0
    for path in settings.data_dir.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            # a file being written while we walk is not an error worth raising
            continue
    return total


def models() -> dict:
    """What is actually on disk and actually running.

    The embedding model is checked by file, not by a flag someone set. The
    answer model is checked by asking Ollama, because "configured" and
    "running" are different states and the dashboard has to distinguish them:
    Tier 2 fails without it while Tier 1 keeps working.
    """
    from . import reranker as reranker_mod

    embed_dir = settings.embed_model_dir
    info = {
        "embed_model": embed_dir.name,
        "embed_model_present": (embed_dir / "tokenizer.json").exists(),
        # Asked of the reranker module rather than guessed from a path here.
        # A hand-written second copy of the layout is exactly how this field
        # first reported the mandatory reranker as absent while it was working.
        "reranker_model": reranker_mod.model_dir().name,
        "reranker_present": reranker_mod.available(),
        "answer_model": settings.answer_model,
        "answer_model_reachable": False,
        "answer_model_loaded": False,
        "ollama_error": None,
    }
    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
            tags = client.get(f"{settings.ollama_url}/api/tags")
            tags.raise_for_status()
            available = [m.get("name", "") for m in tags.json().get("models", [])]
            info["answer_model_reachable"] = True
            info["answer_model_installed"] = any(
                n == settings.answer_model or n.startswith(settings.answer_model)
                for n in available
            )
            running = client.get(f"{settings.ollama_url}/api/ps")
            if running.status_code == 200:
                loaded = [m.get("name", "") for m in running.json().get("models", [])]
                info["answer_model_loaded"] = any(
                    n == settings.answer_model or n.startswith(settings.answer_model)
                    for n in loaded
                )
    except Exception as exc:  # noqa: BLE001 - a stopped Ollama is a state, not a crash
        info["ollama_error"] = type(exc).__name__
    return info


def warnings() -> list[dict]:
    """Conditions an operator must not have to infer from the numbers.

    no_searchable_content is the important one: the document finished, so
    every progress bar reads complete, and search can see none of it.
    """
    conn = connect()
    out: list[dict] = []

    for r in conn.execute(
        """SELECT id, filename, page_count, needs_ocr_pages, error_message
           FROM documents WHERE status = ?""",
        (states.NO_SEARCHABLE_CONTENT,),
    ):
        out.append({
            "severity": "warning",
            "code": states.NO_SEARCHABLE_CONTENT,
            "document_id": r["id"],
            "message": (
                f"{r['filename']} finished processing but search can see none of "
                f"it. {r['error_message'] or 'No retrievable chunk was produced.'}"
            ),
        })

    for r in conn.execute(
        "SELECT id, filename, error_code, error_message FROM documents WHERE status = ?",
        (states.FAILED,),
    ):
        out.append({
            "severity": "error",
            "code": r["error_code"] or "failed",
            "document_id": r["id"],
            "message": f"{r['filename']}: {r['error_message'] or 'processing failed'}",
        })

    ocr = conn.execute(
        "SELECT COALESCE(SUM(needs_ocr_pages), 0) FROM documents"
    ).fetchone()[0]
    if ocr:
        out.append({
            "severity": "warning",
            "code": "needs_ocr",
            "document_id": None,
            "message": (
                f"{ocr} page(s) have no extractable text. OCR is detected but "
                f"NOT implemented, so those pages are not searchable."
            ),
        })

    equations = conn.execute(
        "SELECT COALESCE(SUM(equation_pages), 0) FROM documents"
    ).fetchone()[0]
    if equations:
        out.append({
            "severity": "info",
            "code": "equation_pages",
            "document_id": None,
            "message": (
                f"{equations} page(s) are equation-heavy; the mathematics did not "
                f"survive text extraction. The rendered page image is the mitigation."
            ),
        })
    return out


def snapshot(worker_status: dict) -> dict:
    return {
        "at": _now(),
        "refresh_seconds": 15,
        "corpus": corpus(),
        "exclusions": exclusions(),
        "jobs": jobs(),
        "throughput": telemetry.throughput(),
        "retrieval": telemetry.retrieval_latency(),
        "system": system(),
        "models": models(),
        "worker": worker_status,
        "warnings": warnings(),
    }
