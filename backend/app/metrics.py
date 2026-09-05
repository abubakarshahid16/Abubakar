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
import time
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

#: When the previous call was. The window is NOT the refresh interval: every
#: caller of /api/metrics resets it, so two open tabs halve it and the reading
#: stops being an average of anything. Below this many seconds the sample is
#: reported as unmeasured rather than as noise - the same rule the stage rates
#: already follow with their 50 ms floor.
_cpu_last_call: float | None = None
CPU_MIN_WINDOW_SECONDS = 2.0


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
                      COALESCE(SUM(text_length), 0) AS characters_dropped,
                      COALESCE(SUM(clause_headings), 0) AS clause_heading_pages
               FROM exclusions GROUP BY scope, rule
               ORDER BY clause_heading_pages DESC, count DESC"""
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
    it reports usage since the PREVIOUS CALL. That is not the refresh interval:
    every caller resets the window, so the measured span is reported alongside
    the value and a span too short to average is reported as no value at all.
    """
    global _cpu_measured_once, _cpu_last_call
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(settings.data_dir)
    now = time.monotonic()
    window = None if _cpu_last_call is None else round(now - _cpu_last_call, 1)
    _cpu_last_call = now
    cpu = psutil.cpu_percent(interval=None)
    if not _cpu_measured_once:
        _cpu_measured_once = True
        cpu = None
    elif window is not None and window < CPU_MIN_WINDOW_SECONDS:
        # A 0.3-second window is not an average, it is a spike. Saying nothing
        # is more accurate than saying 0% while the worker is running. The
        # window is still reported, so the screen can say WHY there is no
        # figure rather than giving one reason for two different situations.
        cpu = None
    return {
        "cpu_percent_since_last_call": cpu,
        "cpu_window_seconds": window,
        "ram_free_bytes": memory.available,
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


def _reranker_name() -> str:
    """The reranker's actual name, not the directory it happens to live in."""
    import json

    from . import reranker as reranker_mod

    cfg = reranker_mod.model_dir() / "config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a dashboard label must never 500
        return f"{reranker_mod.model_dir().name} (name unavailable)"
    for key in ("_name_or_path", "name_or_path", "model_type"):
        value = data.get(key)
        if value:
            return str(value)
    return f"{reranker_mod.model_dir().name} (name unavailable)"


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
        # The FOLDER was being reported as the model, so the dashboard read
        # "RERANKER - reranker": a field showing its own label as its value.
        # Same family as everything in the honesty audit - a value derived
        # from something adjacent to the truth. Read from the model's own
        # config, and fall back to the folder only if that is unreadable,
        # which is stated rather than silent.
        "reranker_model": _reranker_name(),
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

    # Free RAM against what the answer model needs. Measured before the model
    # is loaded, because that is when it is actionable.
    memory = psutil.virtual_memory()
    needed = settings.answer_model_ram_bytes
    models_info = models()
    if memory.available < needed and not models_info["answer_model_loaded"]:
        out.append({
            "severity": "warning",
            "code": "low_memory_for_answer_model",
            "document_id": None,
            "message": (
                f"{memory.available / 1e9:.1f} GB of RAM free and "
                f"{settings.answer_model} needs about {needed / 1e9:.1f} GB. "
                f"Tier 2 (Explain) may swap hard or fail. Quoted answers are "
                f"unaffected. Close other applications, or pre-warm the model "
                f"before it is needed."
            ),
        })

    # Two numbers, not one, and the difference is the whole point. The old
    # alert summed needs_ocr_pages and said "OCR is detected but NOT
    # implemented, so those pages are not searchable" - which stopped being
    # true the day recognition shipped, and left the Dashboard contradicting
    # the Documents screen about the same documents.
    #
    # An alert only when work is OUTSTANDING. Pages that have been recognised
    # are not a warning; they are the feature working.
    row = conn.execute(
        """SELECT COALESCE(SUM(needs_ocr_pages), 0) AS flagged,
                  COALESCE(SUM(recognised_pages), 0) AS recognised
           FROM documents"""
    ).fetchone()
    flagged, recognised = row["flagged"], row["recognised"]
    awaiting = max(flagged - recognised, 0)
    if awaiting:
        out.append({
            "severity": "warning",
            "code": "needs_ocr",
            "document_id": None,
            "message": (
                f"{awaiting} scanned page(s) have not been read yet. "
                f"Recognition has not run on them, so they are not searchable "
                f"until it does."
            ),
        })
    elif recognised:
        out.append({
            "severity": "info",
            "code": "pages_recognised",
            "document_id": None,
            "message": (
                f"{recognised} scanned page(s) were read by OCR and are "
                f"searchable. Recognised text is labelled as recognised "
                f"wherever it is quoted, never as the document's own words."
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
