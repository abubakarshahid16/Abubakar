"""Step 2b - resumable page-batch recognition for scanned pages.

Runs AFTER the keyword index, never before it. A text document must stay
answerable in ~13 seconds; recognition is a background stage that makes a
scanned document *progressively* more searchable, not a gate in front of the
first answer.

Three things about this module are architectural rather than tuning:

  * **It runs in a subprocess.** Not for thread-safety - for memory. The API
    process peaks at 3,247 MB with both ONNX arenas on and Ollama holds
    ~3,400 MB beside it; measured free RAM at demo time was 1.15 GiB. An ONNX
    session in the API process would not fit. In a child, the session, the
    image buffers and the arena all return to the OS on exit and the parent's
    footprint is never touched. `extract.py` already dispatches to workers
    because PyMuPDF is not thread-safe; this takes the same treatment and the
    memory problem dissolves as a side effect.

  * **Only pages that need it are recognised.** `idx_pages_ocr` exists for
    exactly this. A 500-page document with 12 scanned pages is 12 seconds of
    work, not 8 minutes. A page that already has extractable text is never
    recognised, and a page already recognised is never recognised again.

  * **Recognised text goes to `page_ocr`, which extraction cannot reach.**
    `pages` is written with INSERT OR REPLACE, so a re-extraction - which
    states.py permits from both no_searchable_content and failed - would
    otherwise overwrite recognition with the empty extraction that triggered
    it. See ADR-0006.

Batches are committed strictly in order so `jobs.last_completed_batch` stays a
contiguous high-water mark a restart can trust, exactly as extraction does.
"""

from __future__ import annotations

import concurrent.futures as cf
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings
from .db import connect
from .quality import normalise_text
from .rates import Timer

#: What the recogniser produced, and what it ran against. Kept as one string
#: so a stored row can always answer "which model wrote this".
ENGINE = "rapidocr-3.9.2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def model_signature() -> str:
    return f"{settings.ocr_det_model}+{settings.ocr_rec_model}"


# --------------------------------------------------------------- alphabet

#: Codepoint ranges a Latin-script document cannot legitimately contain, and
#: that this recogniser demonstrably CAN emit. Written as a blocklist rather
#: than an allowlist on purpose: an allowlist of "acceptable" characters is
#: the wrong shape for a specification, which is full of legitimate
#: non-ASCII - °, ±, µm, Ω, Δ, ½, §. A first attempt allow-listed Unicode
#: categories and immediately flagged DEGREE SIGN (So), MICRO SIGN and GREEK
#: CAPITAL OMEGA, which are exactly the characters an engineering document is
#: supposed to have. Naming the scripts we know are wrong is both narrower and
#: more honest than guessing at what is right.
_BLOCKED_RANGES = (
    (0x2E80, 0x2EFF),    # CJK radicals
    (0x3000, 0x303F),    # CJK symbols and punctuation
    (0x3040, 0x30FF),    # Hiragana, Katakana
    (0x3100, 0x312F),    # Bopomofo
    (0x3130, 0x318F),    # Hangul compatibility jamo
    (0x3400, 0x4DBF),    # CJK unified ideographs extension A
    (0x4E00, 0x9FFF),    # CJK unified ideographs  - 凤 日 区 园
    (0xA000, 0xA4CF),    # Yi
    (0xAC00, 0xD7AF),    # Hangul syllables
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0xFF00, 0xFFEF),    # Halfwidth and fullwidth forms
    (0x0400, 0x04FF),    # Cyrillic
    (0x0590, 0x05FF),    # Hebrew
    (0x0600, 0x06FF),    # Arabic
    (0x0900, 0x097F),    # Devanagari
    (0x0E00, 0x0E7F),    # Thai
)

#: CJK-style lookalikes that sit OUTSIDE those ranges and would otherwise pass
#: as ordinary mathematics. This is the dangerous class: U+2266 rendered small
#: is indistinguishable from U+2264 to a reader skimming a specification, and
#: it was measured coming out of the multilingual recogniser in place of
#: "Save". A wrong 凤 is obvious; a wrong ≦ is not.
_LOOKALIKES = {
    "≦": "≤",   # ≦ LESS-THAN OVER EQUAL TO   -> ≤
    "≧": "≥",   # ≧ GREATER-THAN OVER EQUAL TO -> ≥
    "∥": "‖",   # ∥ PARALLEL TO
    "，": ",",        # ， fullwidth comma
    "．": ".",        # ． fullwidth full stop
}


def alphabet_violations(text: str, script: str = "latin") -> tuple[int, str]:
    """Characters the expected script cannot contain, and a sample of them.

    Flags and counts. Never deletes - recognised text that might be wrong is
    labelled, not hidden. Under a Latin-only recogniser this should always
    return zero, which makes a non-zero count a signal that the wrong model
    was loaded rather than a signal about the page.
    """
    if script != "latin" or not text:
        return 0, ""
    bad: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp < 128:
            continue
        if ch in _LOOKALIKES or any(lo <= cp <= hi for lo, hi in _BLOCKED_RANGES):
            bad.append(ch)
    if not bad:
        return 0, ""
    return len(bad), "".join(sorted(set(bad))[:20])


# ----------------------------------------------------------------- worker

@dataclass
class PageOCR:
    page_no: int
    text: str
    mean_conf: float | None
    min_conf: float | None
    box_count: int
    seconds: float
    violations: int
    violation_sample: str


def _build_engine():
    """Construct RapidOCR from VENDORED paths. Runs in a worker process.

    Every path is explicit. An unset model_path makes RapidOCR download from
    modelscope.cn on first construction, which on an air-gapped machine fails
    at the first recognition rather than at install.
    """
    from rapidocr import RapidOCR

    d = settings.ocr_model_dir
    return RapidOCR(params={
        "Det.model_path": str(d / settings.ocr_det_model),
        "Rec.model_path": str(d / settings.ocr_rec_model),
        "Cls.model_path": str(d / settings.ocr_cls_model),
        "Global.use_cls": settings.ocr_use_cls,
        "Global.max_side_len": settings.ocr_max_side_len,
        "Global.log_level": "error",
        "Rec.rec_batch_num": settings.ocr_rec_batch,
        # Never -1. See config.
        "EngineConfig.onnxruntime.intra_op_num_threads": settings.ocr_threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
    })


def recognise_batch(stored_path: str, sha256: str, page_nos: list[int]) -> list[tuple]:
    """Recognise the given 1-based pages. Runs in a WORKER PROCESS.

    Returns plain tuples so the payload pickles cheaply, the same contract
    extract_batch uses. The engine is built per worker call rather than held:
    the whole point of the subprocess is that its footprint is reclaimed.
    """
    from .pageimage import render_page

    import time

    ocr = _build_engine()
    out: list[tuple] = []
    doc = {"sha256": sha256, "stored_path": stored_path}
    for pno in page_nos:
        t0 = time.perf_counter()
        try:
            image = render_page(doc, pno, dpi=settings.ocr_dpi)
            res = ocr(str(image))
            texts = list(res.txts) if res.txts else []
            scores = [float(s) for s in res.scores] if res.scores is not None else []
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill a batch
            out.append((pno, "", None, None, 0, time.perf_counter() - t0, 0, "",
                        f"{type(exc).__name__}: {exc}"))
            continue
        # Through normalise_text, exactly as extraction does, so symbol-font
        # control characters cannot reach chunking.
        text = normalise_text("\n".join(texts))
        viol, sample = alphabet_violations(text, settings.ocr_expected_script)
        out.append((
            pno, text,
            round(sum(scores) / len(scores), 4) if scores else None,
            round(min(scores), 4) if scores else None,
            len(texts), round(time.perf_counter() - t0, 3), viol, sample, None,
        ))
    return out


# ------------------------------------------------------------------ stage

def pending_pages(doc_id: str) -> list[int]:
    """Pages flagged needs_ocr that have not been recognised yet.

    This is lever 1, and it is worth more than the rest combined: a page with
    extractable text is never recognised, and a page already in page_ocr is
    never recognised twice. Served by idx_pages_ocr.
    """
    conn = connect()
    rows = conn.execute(
        """SELECT p.page_no FROM pages p
           LEFT JOIN page_ocr o
             ON o.document_id = p.document_id AND o.page_no = p.page_no
           WHERE p.document_id = ? AND p.needs_ocr = 1 AND o.page_no IS NULL
           ORDER BY p.page_no""",
        (doc_id,),
    ).fetchall()
    return [r["page_no"] for r in rows]


def _commit_batch(doc_id: str, job_id: str | None, batch_no: int,
                  rows: list[tuple], model: str) -> int:
    """Persist one batch and advance the checkpoint atomically."""
    conn = connect()
    now = _now()
    payload = []
    for (pno, text, mean_c, min_c, boxes, secs, viol, sample, err) in rows:
        if err is not None:
            continue
        payload.append((doc_id, pno, text, len(text.strip()), ENGINE, model,
                        settings.ocr_dpi, mean_c, min_c, boxes, viol, sample,
                        secs, now, batch_no))
    with conn:
        if payload:
            conn.executemany(
                """INSERT OR REPLACE INTO page_ocr
                   (document_id, page_no, text, char_count, engine, model, dpi,
                    mean_conf, min_conf, box_count, alphabet_violations,
                    alphabet_sample, seconds, recognised_at, batch_no)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                payload,
            )
        # Only pages that actually produced text count as recognised. A blank
        # page is not a recognised page, and conflating them would put a false
        # number on the document record.
        n = conn.execute(
            "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ? AND char_count > 0",
            (doc_id,),
        ).fetchone()["c"]
        conn.execute(
            "UPDATE documents SET recognised_pages = ? WHERE id = ?", (n, doc_id))
        if job_id is not None:
            conn.execute(
                "UPDATE jobs SET last_completed_batch = ?, updated_at = ? WHERE id = ?",
                (batch_no, now, job_id))
    return len(payload)


def round_size(recognised_so_far: int) -> int:
    """How many pages the next round should recognise before re-indexing.

    Doubling, starting at one batch. The point is to make a scanned document
    progressively searchable without paying O(n^2) for it: re-chunking is
    whole-document, so re-indexing after every batch would cost more than the
    recognition. Doubling gives BOTH properties - page 40 is answerable within
    a couple of rounds while page 900 is still being read, and the total
    re-index cost converges to about twice one full chunk pass rather than
    growing with the page count.
    """
    return max(settings.ocr_batch_size, recognised_so_far)


def recognise_document(doc_id: str, progress=None, max_pages: int | None = None) -> dict:
    """Recognise pending scanned pages of one document.

    Batches are dispatched to at most `ocr_processes` workers but committed
    strictly in order, so the high-water mark stays contiguous.

    `max_pages` bounds one round so the caller can re-index between rounds.
    """
    conn = connect()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError(f"unknown document {doc_id}")

    todo = pending_pages(doc_id)
    if max_pages is not None:
        todo = todo[:max_pages]
    timer = Timer()
    if not todo:
        return {"document_id": doc_id, "filename": doc["filename"],
                "pages_pending": 0, "pages_recognised": 0, "pages_with_text": 0,
                "pages_remaining": 0,
                "alphabet_violations": 0, "seconds": 0.0, "batches": 0,
                "model": model_signature()}

    size = settings.ocr_batch_size
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    model = model_signature()
    recognised = 0

    with cf.ProcessPoolExecutor(max_workers=settings.ocr_processes) as pool:
        inflight: dict[int, cf.Future] = {}
        queue = list(enumerate(batches))
        while queue or inflight:
            while queue and len(inflight) < settings.ocr_processes:
                bno, pages = queue.pop(0)
                inflight[bno] = pool.submit(
                    recognise_batch, doc["stored_path"], doc["sha256"], pages)
            nxt = min(inflight)
            rows = inflight.pop(nxt).result()
            recognised += _commit_batch(doc_id, None, nxt, rows, model)
            if progress:
                progress(recognised, len(todo))

    remaining = len(pending_pages(doc_id))
    stats = conn.execute(
        """SELECT COUNT(*) n,
                  COALESCE(SUM(CASE WHEN char_count > 0 THEN 1 ELSE 0 END),0) with_text,
                  COALESCE(SUM(alphabet_violations),0) viol
           FROM page_ocr WHERE document_id = ?""",
        (doc_id,),
    ).fetchone()
    return {
        "document_id": doc_id, "filename": doc["filename"],
        "pages_pending": len(todo), "pages_recognised": recognised,
        "pages_remaining": remaining,
        "pages_with_text": stats["with_text"],
        "alphabet_violations": stats["viol"],
        "seconds": timer.seconds(), "batches": len(batches),
        "model": model,
    }
