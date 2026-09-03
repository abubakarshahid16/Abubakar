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
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import fitz  # PyMuPDF

from .config import settings
from .db import connect

# A page with less usable text than this is assumed to be scanned or
# image-dominant. Detection only - OCR is deliberately not implemented.
MIN_USABLE_CHARS = 100


@dataclass
class PageResult:
    page_no: int
    text: str
    needs_ocr: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def extract_batch(pdf_path: str, first_page: int, last_page: int) -> list[tuple[int, str, bool]]:
    """Extract [first_page, last_page] inclusive, 1-based.

    Runs in a worker process. Opens the document itself - a fitz.Document
    cannot cross a process boundary. Returns plain tuples so the payload
    pickles cheaply.
    """
    out: list[tuple[int, str, bool]] = []
    with fitz.open(pdf_path) as doc:
        for pno in range(first_page - 1, min(last_page, doc.page_count)):
            page = doc.load_page(pno)
            text = page.get_text("text") or ""
            text = text.replace("\x00", "")
            usable = len(text.strip())
            needs_ocr = usable < MIN_USABLE_CHARS
            out.append((pno + 1, text, needs_ocr))
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


def _commit_batch(doc_id: str, job_id: str, batch_no: int, rows: list[tuple[int, str, bool]]) -> None:
    """Persist one batch and advance the checkpoint atomically."""
    conn = connect()
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO pages
               (document_id, page_no, text, char_count, needs_ocr, batch_no)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(doc_id, p, t, len(t.strip()), int(o), batch_no) for p, t, o in rows],
        )
        done = conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(needs_ocr),0) AS o FROM pages WHERE document_id = ?",
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
                "pages_extracted": 0, "needs_ocr": 0, "seconds": 0.0,
                "pages_per_sec": None, "resumed_from_batch": 0, "error": "stored file is missing"}

    total = doc["page_count"] or page_count(pdf_path)
    if doc["page_count"] is None:
        with conn:
            conn.execute("UPDATE documents SET page_count = ? WHERE id = ?", (total, doc_id))
            conn.execute("UPDATE jobs SET pages_total = ? WHERE id = ?", (total, job["id"]))

    start_batch = 0 if job["last_completed_batch"] is None else job["last_completed_batch"] + 1
    todo = _batches(total, settings.page_batch_size, start_batch)
    started = time.perf_counter()

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
                if progress:
                    cur = conn.execute(
                        "SELECT pages_done FROM documents WHERE id = ?", (doc_id,)
                    ).fetchone()["pages_done"]
                    progress(cur, total)

    elapsed = time.perf_counter() - started
    final = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(needs_ocr),0) AS o FROM pages WHERE document_id = ?",
        (doc_id,),
    ).fetchone()
    with conn:
        # Extraction complete; chunking is step 3, so the document is not
        # "ready" - it has no searchable chunks yet.
        conn.execute(
            "UPDATE documents SET pages_done = ?, needs_ocr_pages = ?, status = 'chunking' WHERE id = ?",
            (final["c"], final["o"], doc_id),
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
        "seconds": round(elapsed, 2),
        "pages_per_sec": round(final["c"] / elapsed, 2) if elapsed > 0 else None,
        "resumed_from_batch": start_batch,
    }
