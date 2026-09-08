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

import psutil

from . import model_transport, states, telemetry
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


#: How a scoped query says "every document" versus "these documents".
#:
#: `None` means corpus-wide and is reachable only from the route, which decides
#: it from the caller. An EMPTY LIST is not the same thing and must never be
#: treated as one - it means the caller is granted nothing, and every count it
#: produces is zero. Conflating the two is precisely the defect this scoping was
#: written to fix, in a smaller and harder-to-see form.
Allowed = list[str] | None


def _where(allowed: Allowed, column: str = "document_id") -> tuple[str, list[str]]:
    """A WHERE fragment restricting `column` to the caller's grants.

    Filtered IN THE QUERY rather than after it, for the reason `main.py`
    already gives on /api/documents: dropping unauthorised rows in Python
    happens to work while there is no LIMIT, and silently becomes a leak the
    day someone adds one.
    """
    if allowed is None:
        return "", []
    if not allowed:
        return " WHERE 1 = 0", []
    return f" WHERE {column} IN ({','.join('?' * len(allowed))})", list(allowed)


def corpus(allowed: Allowed = None) -> dict:
    conn = connect()
    doc_where, doc_args = _where(allowed, "id")
    chunk_where, chunk_args = _where(allowed)
    docs = conn.execute(
        """SELECT COUNT(*) AS documents,
                  COALESCE(SUM(page_count), 0) AS pages_declared,
                  COALESCE(SUM(chunk_count), 0) AS chunks_retrievable,
                  COALESCE(SUM(chunk_count_total), 0) AS chunks_total,
                  COALESCE(SUM(embedded_count), 0) AS embedded
           FROM documents""" + doc_where, doc_args
    ).fetchone()
    pages_extracted = conn.execute(
        "SELECT COUNT(*) FROM pages" + chunk_where, chunk_args).fetchone()[0]
    chunks_rows = conn.execute(
        "SELECT COUNT(*) FROM chunks" + chunk_where, chunk_args).fetchone()[0]
    vectors = conn.execute(
        "SELECT COUNT(*) FROM chunk_vectors" + chunk_where, chunk_args).fetchone()[0]
    indexed = conn.execute(
        "SELECT COUNT(*) FROM chunks_fts" + chunk_where, chunk_args).fetchone()[0]
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM documents" + doc_where
            + " GROUP BY status", doc_args
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


def exclusions(allowed: Allowed = None) -> list[dict]:
    """What search cannot see, and which rule excluded it."""
    where, args = _where(allowed)
    return [
        dict(r)
        for r in connect().execute(
            """SELECT scope, rule, COUNT(*) AS count,
                      COALESCE(SUM(text_length), 0) AS characters_dropped,
                      COALESCE(SUM(clause_headings), 0) AS clause_heading_pages
               FROM exclusions""" + where
            + """ GROUP BY scope, rule
               ORDER BY clause_heading_pages DESC, count DESC""", args
        )
    ]


def jobs(allowed: Allowed = None) -> dict:
    conn = connect()
    job_where, job_args = _where(allowed)
    by_state = {
        r["state"]: r["n"]
        for r in conn.execute(
            "SELECT state, COUNT(*) AS n FROM jobs" + job_where
            + " GROUP BY state", job_args)
    }
    # `failures` carries the filename and the raw error_message, so this is one
    # of the two paths by which a document's NAME leaves this endpoint. The
    # other is `warnings`.
    id_where, id_args = _where(allowed, "id")
    clause = (" AND status = ?" if id_where else " WHERE status = ?")
    failures = [
        dict(r)
        for r in conn.execute(
            """SELECT id, filename, error_code, error_message, uploaded_at
               FROM documents""" + id_where + clause
            + " ORDER BY uploaded_at DESC LIMIT 20",
            [*id_args, states.FAILED],
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
        # THROUGH THE ONE TRANSPORT, even though neither probe sends document
        # content. They talk to the same operator-settable host as the answer
        # path, and exempting "harmless" requests from the host check is how a
        # second unchecked call site gets written.
        tags = model_transport.get_json("/api/tags", timeout=OLLAMA_TIMEOUT)
        available = [m.get("name", "") for m in (tags or {}).get("models", [])]
        info["answer_model_reachable"] = True
        info["answer_model_installed"] = any(
            n == settings.answer_model or n.startswith(settings.answer_model)
            for n in available
        )
        # `required=False`: a non-200 from /api/ps means Ollama is up and told
        # us nothing about loaded models, which is a different state from
        # Ollama being absent. Preserved exactly as it was.
        running = model_transport.get_json(
            "/api/ps", timeout=OLLAMA_TIMEOUT, required=False)
        if running is not None:
            loaded = [m.get("name", "") for m in running.get("models", [])]
            info["answer_model_loaded"] = any(
                n == settings.answer_model or n.startswith(settings.answer_model)
                for n in loaded
            )
    except model_transport.ModelHostRefused:
        # NOT swallowed into `ollama_error`. Every other failure here is a
        # state of the world (Ollama stopped, port dead) and belongs in a
        # dashboard field; a refused host is a misconfigured privacy boundary
        # and belongs in the operator's face. A dashboard that renders it as
        # "ollama_error: ModelHostRefused" beside a green tick is audit entry
        # 24 again - a control whose absence is invisible.
        raise
    except Exception as exc:  # noqa: BLE001 - a stopped Ollama is a state, not a crash
        info["ollama_error"] = type(exc).__name__
    return info


def warnings(allowed: Allowed = None, host: bool = True) -> list[dict]:
    """Conditions an operator must not have to infer from the numbers.

    no_searchable_content is the important one: the document finished, so
    every progress bar reads complete, and search can see none of it.

    BOTH document loops below interpolate a FILENAME into the message, so this
    function is the widest disclosure on the endpoint - and the first loop is
    the one that matters, because `no_searchable_content` is a SUCCESSFUL
    terminal state. A scanned PDF whose every chunk is excluded lands there
    with nothing going wrong, which makes it likelier in normal use than
    `failed`. Both are scoped.
    """
    conn = connect()
    id_where, id_args = _where(allowed, "id")
    clause = (" AND status = ?" if id_where else " WHERE status = ?")
    out: list[dict] = []

    for r in conn.execute(
        """SELECT id, filename, page_count, needs_ocr_pages, error_message
           FROM documents""" + id_where + clause,
        [*id_args, states.NO_SEARCHABLE_CONTENT],
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
        "SELECT id, filename, error_code, error_message FROM documents"
        + id_where + clause,
        [*id_args, states.FAILED],
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
            # THE FIGURE IS HOST TELEMETRY WHEREVER IT APPEARS, including in
            # prose. Gating the `system` block alone would have left free RAM
            # and the model's footprint stated in this sentence, to every
            # caller - the fact leaking through the description of the fact.
            #
            # Both versions carry the SAME OPERATIONAL MEANING: Explain may be
            # slow or fail, quoted answers are not affected, and closing
            # applications is the remedy. A reader who cannot act on a figure
            # loses nothing by not being given it, and a warning that simply
            # vanished for non-admins would be worse than either - it would
            # hide a real condition from the person sitting in front of it.
            "message": (
                f"{memory.available / 1e9:.1f} GB of RAM free and "
                f"{settings.answer_model} needs about {needed / 1e9:.1f} GB. "
                f"Tier 2 (Explain) may swap hard or fail. Quoted answers are "
                f"unaffected. Close other applications, or pre-warm the model "
                f"before it is needed."
                if host else
                "This machine is low on memory for the answer model. Tier 2 "
                "(Explain) may be slow or fail. Quoted answers are unaffected. "
                "Closing other applications will help."
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
    # SCOPED, like every other count on this endpoint. These three summed the
    # whole `documents` table with no WHERE at all, and were shipped beside
    # `"corpus_wide": false` - so a caller with four grants was told how many
    # scanned pages were outstanding across documents they cannot read, and
    # the number contradicted the Documents screen for the same person.
    row = conn.execute(
        """SELECT COALESCE(SUM(needs_ocr_pages), 0) AS flagged,
                  COALESCE(SUM(recognised_pages), 0) AS recognised
           FROM documents""" + id_where, id_args
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
        "SELECT COALESCE(SUM(equation_pages), 0) FROM documents" + id_where,
        id_args,
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


def _scoped_worker(status: dict, allowed: Allowed, corpus_wide: bool) -> dict:
    """The worker block with anything document-identifying removed.

    THESE ARE THE FIELDS THAT WERE MOVED HERE OFF /api/health, and the reason
    given for moving them was that this endpoint is scoped. It was not.
    `current_document` is a real document id which the UI joins against the
    document list to show a filename, and `last_error` is free text that can
    name one - so an unauthenticated caller learning that a specific document
    exists and is being processed was the whole point of moving them, and
    without this they simply moved to a different unscoped route.

    A caller who may not read the document being processed does not learn its
    id. `alive`, `stalled` and the counts stay: they describe the machine, not
    anybody's documents, which is the same distinction /api/health draws.
    """
    if corpus_wide:
        return status
    current = status.get("current_document")
    if current is not None and current in (allowed or []):
        return status
    return {**status, "current_document": None, "last_error": None}


def snapshot(worker_status: dict, allowed: Allowed = None,
             corpus_wide: bool = False, host: bool = False) -> dict:
    """Everything the dashboard shows, restricted to `allowed`.

    `host` gates the machine's own specifications - CPU cores and load, RAM
    total/used/free, this process's resident size, disk totals - on the ADMIN
    CAPABILITY. They are not a document, so the #75 corpus scoping could never
    have removed them: 411 bytes of fingerprinting material inside a 3,567-byte
    response, served to every caller including an unauthenticated one, by a
    product whose stated boundary is that nothing leaves this machine.

    The block is OMITTED, not blanked. Sending each field as 0 or null would
    state measurements that are false, and this codebase renders an absent
    value as absent everywhere else.

    `host` also decides whether the low-memory warning may state the figure -
    see `warnings`. Gating the block while the prose restates free RAM would
    have moved the leak rather than closed it.

    `corpus_wide` is reported back to the client rather than inferred there.
    A count with no stated boundary reads as total, and an admin looking at
    figures that include documents they cannot open needs the screen to say so
    - which it cannot do unless the payload tells it which kind of number it
    is holding.
    """
    return {
        "at": _now(),
        "refresh_seconds": 15,
        "corpus_wide": corpus_wide,
        "corpus": corpus(allowed),
        "exclusions": exclusions(allowed),
        "jobs": jobs(allowed),
        # Throughput and latency are process-level and carry no document
        # identity. They are the operator's view of the machine, not of a
        # corpus, so they are not scoped by grants.
        "throughput": telemetry.throughput(),
        "retrieval": telemetry.retrieval_latency(),
        **({"system": system()} if host else {}),
        "models": models(),
        "worker": _scoped_worker(worker_status, allowed, corpus_wide),
        "warnings": warnings(allowed, host),
    }
