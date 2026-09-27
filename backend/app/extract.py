"""Step 2 - resumable page-batch extraction.

PyMuPDF is not thread-safe; the official guidance is multiprocessing. Batches
are dispatched to at most two worker processes, but committed strictly in
order, so `jobs.last_completed_batch` is always a contiguous high-water mark
that a restart can trust.

Page rows are keyed on (document_id, page_no) and written with INSERT OR
REPLACE, so re-running a batch after a crash replaces rather than duplicates.
"""

from __future__ import annotations

import concurrent.futures as cf
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import pymupdf  # PyMuPDF

from . import ocr, states
from .config import settings
from .quality import normalise_text
from .db import connect
from .rates import Timer, rate

# Which pages go to recognition is decided HERE, per page, by
# `ocr.route_page` (audit F6) - detection only at this stage; ocr.py later
# consumes the flag via idx_pages_ocr. It used to be "fewer than 100 usable
# characters" alone, which never read a scanned page carrying a digital
# header, footer or DCC stamp (238 chars) and recorded nothing about it. The
# character floor is now `settings.ocr_min_usable_chars`, one rule of several,
# and the reason for every decision is stored on the page.
# A page this dense in mathematical symbols extracts as prose ABOUT maths with
# the maths missing. Flagged rather than silently degraded.
EQUATION_MARKERS = set("∫∑∏√±≤≥≠≈∞∂∇αβγδεθλμπρσφψωΓΔΘΛΞΠΣΦΨΩ")
# Proportion of tokens that look like broken maths before a page is flagged.
EQUATION_PAGE_RATIO = 0.25


def equation_density(text: str) -> float:
    """How much of this page reads as mathematical notation rather than words.

    PyMuPDF drops '=' and '+' from equations and flattens sub/superscripts, so
    an equation-dense page becomes prose ABOUT maths with the maths missing.
    Flagged the way needs_ocr is, so it is visible rather than quietly useless.
    """
    tokens = text.split()
    if not tokens:
        return 0.0
    hits = 0
    for t in tokens:
        if any(ch in EQUATION_MARKERS for ch in t):
            hits += 1
        elif len(t) <= 6 and any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t):
            # "x2", "hm3", "ea1s" - a letter/digit blend left by a broken formula
            hits += 1
    return hits / len(tokens)


@dataclass
class PageResult:
    page_no: int
    text: str
    needs_ocr: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def page_count(pdf_path: str) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def extract_batch(pdf_path: str, first_page: int, last_page: int) -> list[tuple]:
    """Extract [first_page, last_page] inclusive, 1-based.

    Runs in a worker process. Opens the document itself - a pymupdf.Document
    cannot cross a process boundary. Returns plain tuples so the payload
    pickles cheaply: (page_no, text, needs_ocr, equation_heavy, ocr_route).
    """
    out: list[tuple] = []
    with pymupdf.open(pdf_path) as doc:
        for pno in range(first_page - 1, min(last_page, doc.page_count)):
            page = doc.load_page(pno)
            text = page.get_text("text") or ""
            # Normalise here, once, so symbol-font control characters never
            # reach chunking. Leaving them in made real content look like
            # gibberish to the quality gate and silently excluded it.
            text = normalise_text(text)
            route = ocr.route_page(page, text)
            eq_heavy = equation_density(text) >= EQUATION_PAGE_RATIO
            out.append((pno + 1, text, route.needs_ocr, eq_heavy, route.reason))
    return out


def _batches(total_pages: int, size: int, start_batch: int) -> list[tuple[int, int, int]]:
    """(batch_no, first_page, last_page), 0-based batch numbers, 1-based pages."""
    result = []
    n = 0
    page = 1
    while page <= total_pages:
        last = min(page + size - 1, total_pages)
        if n >= start_batch:
            result.append((n, page, last))
        page = last + 1
        n += 1
    return result


def _commit_batch(doc_id: str, job_id: str, batch_no: int, rows: list[tuple]) -> None:
    """Persist one batch and advance the checkpoint atomically.

    A row without a routing reason (a 4-tuple from an older caller) stores
    NULL reason and version, which reads as "not decided by the current
    rule" - stale, never as a decision nobody made.
    """
    conn = connect()
    payload = []
    for p, t, o, e, *rest in rows:
        reason = rest[0] if rest else None
        payload.append((doc_id, p, t, len(t.strip()), int(o), int(e), batch_no, reason,
                        ocr.OCR_ROUTE_VERSION if reason is not None else None))
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO pages
               (document_id, page_no, text, char_count, needs_ocr, equation_heavy,
                batch_no, ocr_route, ocr_route_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
        done = conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(needs_ocr),0) AS o,"
            " COALESCE(SUM(equation_heavy),0) AS e FROM pages WHERE document_id = ?",
            (doc_id,),
        ).fetchone()
        conn.execute(
            "UPDATE jobs SET last_completed_batch = ?, pages_done = ?, updated_at = ? WHERE id = ?",
            (batch_no, done["c"], _now(), job_id),
        )
        conn.execute(
            "UPDATE documents SET pages_done = ?, needs_ocr_pages = ?, status = ? WHERE id = ?",
            (done["c"], done["o"], "extracting", doc_id),
        )


def extract_document(doc_id: str, progress=None) -> dict:
    """Extract one document, resuming from its last completed batch.

    `progress` is called as progress(pages_done, total_pages) after each batch.
    """
    conn = connect()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError(f"unknown document {doc_id}")
    job = conn.execute(
        "SELECT * FROM jobs WHERE document_id = ? ORDER BY started_at DESC LIMIT 1", (doc_id,)
    ).fetchone()
    if job is None:
        raise ValueError(f"no job for {doc_id}")

    pdf_path = doc["stored_path"]
    if not os.path.exists(pdf_path):
        # Row survived but the bytes did not. Fail loudly in the record
        # rather than crashing the worker mid-queue.
        with conn:
            conn.execute(
                "UPDATE documents SET status='failed', error_code='extract_failed',"
                " error_message='stored file is missing' WHERE id = ?", (doc_id,))
            conn.execute(
                "UPDATE jobs SET state='failed', error_code='extract_failed',"
                " error_message='stored file is missing', updated_at=? WHERE id = ?",
                (_now(), job["id"]))
        return {"document_id": doc_id, "filename": doc["filename"], "pages_total": None,
                "pages_extracted": 0, "pages_extracted_this_run": 0, "needs_ocr": 0,
                "seconds": 0.0, "pages_per_sec": None, "resumed_from_batch": 0,
                "error": "stored file is missing"}

    total = doc["page_count"] or page_count(pdf_path)
    if doc["page_count"] is None:
        with conn:
            conn.execute("UPDATE documents SET page_count = ? WHERE id = ?", (total, doc_id))
            conn.execute("UPDATE jobs SET pages_total = ? WHERE id = ?", (total, job["id"]))

    start_batch = 0 if job["last_completed_batch"] is None else job["last_completed_batch"] + 1
    todo = _batches(total, settings.page_batch_size, start_batch)
    timer = Timer()
    pages_this_run = 0

    if todo:
        # Two processes, never threads. Commit strictly in order so the
        # checkpoint stays a contiguous high-water mark.
        with cf.ProcessPoolExecutor(max_workers=settings.extract_processes) as pool:
            inflight: dict[int, cf.Future] = {}
            queue = list(todo)
            while queue or inflight:
                while queue and len(inflight) < settings.extract_processes:
                    bno, first, last = queue.pop(0)
                    inflight[bno] = pool.submit(extract_batch, pdf_path, first, last)
                nxt = min(inflight)
                rows = inflight.pop(nxt).result()
                _commit_batch(doc_id, job["id"], nxt, rows)
                pages_this_run += len(rows)
                if progress:
                    cur = conn.execute(
                        "SELECT pages_done FROM documents WHERE id = ?", (doc_id,)
                    ).fetchone()["pages_done"]
                    progress(cur, total)

    elapsed = timer.seconds()
    final = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(needs_ocr),0) AS o,"
        " COALESCE(SUM(equation_heavy),0) AS e FROM pages WHERE document_id = ?",
        (doc_id,),
    ).fetchone()
    with conn:
        # Extraction complete; chunking is step 3, so the document is not
        # "ready" - it has no searchable chunks yet.
        conn.execute(
            "UPDATE documents SET pages_done = ?, needs_ocr_pages = ?,"
            " equation_pages = ?, status = 'chunking' WHERE id = ?",
            (final["c"], final["o"], final["e"], doc_id),
        )
        conn.execute(
            "UPDATE jobs SET stage = 'chunk', state = 'done', pages_done = ?, updated_at = ? WHERE id = ?",
            (final["c"], _now(), job["id"]),
        )
    return {
        "document_id": doc_id,
        "filename": doc["filename"],
        "pages_total": total,
        "pages_extracted": final["c"],
        "needs_ocr": final["o"],
        "equation_heavy_pages": final["e"],
        "pages_extracted_this_run": pages_this_run,
        "seconds": elapsed,
        "pages_per_sec": rate(pages_this_run, elapsed),
        "resumed_from_batch": start_batch,
    }


#: Statuses a re-route may send back through the pipeline when it finds a
#: page that now needs recognition. READY and NO_SEARCHABLE_CONTENT may go to
#: CHUNKING (states.py); chunking skips unchanged text by its signature, so
#: the worker's cost is the new pages' recognition and whatever they change.
_REROUTE_RESUMABLE = (states.READY, states.NO_SEARCHABLE_CONTENT)


def reroute_document(doc_id: str, *, apply: bool = True) -> dict:
    """Re-decide OCR routing for an ALREADY-EXTRACTED document.

    Re-opens the stored PDF and runs `ocr.route_page` on each page against
    the text already stored in `pages` - nothing is re-extracted, re-chunked
    or re-embedded here. Pages whose decision is unchanged only get their
    reason and version recorded. When a page newly needs recognition and has
    none yet, a finished document is moved to CHUNKING so the ingestion
    worker picks it up: chunking is skipped as unchanged, the keyword index
    is rebuilt, and the OCR stage reads only the newly routed pages.

    `apply=False` computes the same answer and writes nothing (the estimate
    `scripts/reroute_ocr.py` prints by default). Counts only, never text.
    """
    conn = connect()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError(f"unknown document {doc_id}")
    result = {"document_id": doc_id, "pages": 0, "stale": 0, "newly_needs_ocr": 0,
              "no_longer_needs_ocr": 0, "requeued": False, "routes": {}, "error": None}
    if not doc["stored_path"] or not os.path.exists(doc["stored_path"]):
        result["error"] = "stored file is missing"
        return result
    rows = conn.execute(
        "SELECT page_no, text, needs_ocr, ocr_route_version FROM pages"
        " WHERE document_id = ? ORDER BY page_no", (doc_id,)).fetchall()
    recognised = {r["page_no"] for r in conn.execute(
        "SELECT page_no FROM page_ocr WHERE document_id = ?", (doc_id,))}
    updates = []
    newly_pending = 0
    with pymupdf.open(doc["stored_path"]) as pdf:
        for r in rows:
            if not 1 <= r["page_no"] <= pdf.page_count:
                continue
            route = ocr.route_page(pdf.load_page(r["page_no"] - 1), r["text"] or "")
            result["pages"] += 1
            result["routes"][route.code] = result["routes"].get(route.code, 0) + 1
            if r["ocr_route_version"] != ocr.OCR_ROUTE_VERSION:
                result["stale"] += 1
            if route.needs_ocr and not r["needs_ocr"]:
                result["newly_needs_ocr"] += 1
                if r["page_no"] not in recognised:
                    newly_pending += 1
            elif r["needs_ocr"] and not route.needs_ocr:
                result["no_longer_needs_ocr"] += 1
            updates.append((int(route.needs_ocr), route.reason, ocr.OCR_ROUTE_VERSION,
                            doc_id, r["page_no"]))
    requeue = newly_pending > 0 and doc["status"] in _REROUTE_RESUMABLE
    result["requeued"] = requeue
    if not apply:
        return result
    with conn:
        conn.executemany(
            "UPDATE pages SET needs_ocr = ?, ocr_route = ?, ocr_route_version = ?"
            " WHERE document_id = ? AND page_no = ?", updates)
        conn.execute(
            "UPDATE documents SET needs_ocr_pages ="
            " (SELECT COALESCE(SUM(needs_ocr), 0) FROM pages WHERE document_id = ?)"
            " WHERE id = ?", (doc_id, doc_id))
        if requeue:
            states.check_transition(doc["status"], states.CHUNKING)
            conn.execute(
                "UPDATE documents SET status = ?, error_code = NULL, error_message = NULL"
                " WHERE id = ? AND status = ?", (states.CHUNKING, doc_id, doc["status"]))
    return result
