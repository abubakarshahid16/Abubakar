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
    work, not 8 minutes. Which pages "need it" is `route_page`: no usable text
    layer, OR a page that is mostly raster image with only a thin text layer
    on it (a scan carrying a digital header, footer or stamp - audit F6). A
    normal text page is never recognised, and a page already recognised is
    never recognised again. The reason is recorded per page (`pages.ocr_route`).

  * **One page failing is one page failing** (audit F7). A page the
    recogniser cannot process is stored with its error and empty text, so it
    is consumed, shown as `ocr_failed`, and the rest of the document goes on
    to be embedded. It used to stay pending forever and fail the document.

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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

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


# ---------------------------------------------------------------- routing

#: Bumped whenever `route_decision` changes what it decides. Stored on every
#: page (`pages.ocr_route_version`); a page with an older or NULL version was
#: decided by an earlier rule and `scripts/reroute_ocr.py` re-decides it from
#: the stored PDF without re-extracting its text.
#:   1 - implicit, never stored: "fewer than 100 usable characters".
#:   2 - image coverage and text density (audit F6).
OCR_ROUTE_VERSION = "2"

#: One square inch in PDF user space (72 pt x 72 pt).
_SQ_INCH = 72.0 * 72.0

#: Above this many rectangles the exact union is skipped for a capped sum:
#: a page tiled into thousands of image strips is image-covered either way.
_UNION_EXACT_MAX = 400


@dataclass(frozen=True)
class Route:
    """One page's routing decision and the measurements behind it.

    `reason` is what the ledger shows: a code, then numbers. Never page text.
    """
    needs_ocr: bool
    code: str            # 'no_text_layer' | 'image_dominant' | 'text_layer'
    reason: str


def _union_area(rects: list[tuple[float, float, float, float]]) -> float:
    """Area covered by the union of axis-aligned rectangles.

    Coordinate compression over x, merged y-intervals per slab. Overlapping
    images (a scan laid over a background, strip-tiled scans) must not count
    twice, or a half-covered page would read as fully covered.
    """
    rects = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    if not rects:
        return 0.0
    if len(rects) > _UNION_EXACT_MAX:
        return sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((y0, y1) for x0, y0, x1, y1 in rects if x0 <= left and x1 >= right)
        covered, cur0, cur1 = 0.0, None, None
        for y0, y1 in spans:
            if cur1 is None or y0 > cur1:
                if cur1 is not None:
                    covered += cur1 - cur0
                cur0, cur1 = y0, y1
            else:
                cur1 = max(cur1, y1)
        if cur1 is not None:
            covered += cur1 - cur0
        area += covered * (right - left)
    return area


def _clip(rect, bounds) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    bx0, by0, bx1, by1 = bounds
    return (max(x0, bx0), max(y0, by0), min(x1, bx1), min(y1, by1))


def route_decision(chars: int, page_area: float, image_area: float,
                   text_area: float | None) -> Route:
    """The routing rule, pure, on measurements in PDF points.

    `text_area` may be None when the images do not cover enough of the page
    for it to matter - it is only measured when it can change the answer.
    """
    s = settings
    if chars < s.ocr_min_usable_chars:
        return Route(True, "no_text_layer",
                     f"no_text_layer: text layer has {chars} characters "
                     f"(under {s.ocr_min_usable_chars})")
    if page_area <= 0:
        return Route(False, "text_layer",
                     f"text_layer: {chars} characters; page has no area")
    coverage = min(1.0, image_area / page_area)
    density = chars / (page_area / _SQ_INCH)
    if coverage < s.ocr_image_coverage_min:
        return Route(False, "text_layer",
                     f"text_layer: {chars} characters ({density:.1f}/sq in); "
                     f"images cover {coverage:.0%} of the page")
    ratio = (text_area or 0.0) / image_area if image_area > 0 else 0.0
    thin = density < s.ocr_max_text_density or ratio < s.ocr_max_text_to_image_area
    measured = (f"images cover {coverage:.0%} of the page; text layer {chars} "
                f"characters ({density:.1f}/sq in), text blocks {ratio:.0%} of "
                "image area")
    if thin:
        return Route(True, "image_dominant", f"image_dominant: {measured}")
    return Route(False, "text_layer", f"text_layer: dense text over image - {measured}")


def route_page(page, text: str) -> Route:
    """Decide whether this PyMuPDF page goes to recognition.

    `text` is the page's normalised text layer, as `pages.text` stores it.
    Cheap on the common path: a text page with no large image costs one
    `get_image_info` call; text blocks are measured only when images cover
    enough of the page for them to matter.
    """
    chars = len(text.strip())
    # Unrotated page space: both get_image_info and get_text report there.
    base = page.rect * page.derotation_matrix
    bounds = (min(base.x0, base.x1), min(base.y0, base.y1),
              max(base.x0, base.x1), max(base.y0, base.y1))
    page_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    if chars < settings.ocr_min_usable_chars:
        return route_decision(chars, page_area, 0.0, None)
    try:
        images = [_clip(tuple(i["bbox"]), bounds)
                  for i in page.get_image_info(hashes=False, xrefs=False)]
    except Exception:  # noqa: BLE001 - a malformed image stream is not a scan
        images = []
    image_area = _union_area(images)
    text_area = None
    if page_area > 0 and image_area / page_area >= settings.ocr_image_coverage_min:
        blocks = [_clip(tuple(b[:4]), bounds) for b in page.get_text("blocks")
                  if len(b) > 6 and b[6] == 0 and str(b[4]).strip()]
        text_area = _union_area(blocks)
    return route_decision(chars, page_area, image_area, text_area)


# ------------------------------------------------------------------ merge

_NON_ALNUM = re.compile(r"[^0-9a-z]+")

#: An OCR line this similar to a text-layer line is the same line misread.
_DUP_RATIO = 0.85


def _norm(line: str) -> str:
    return _NON_ALNUM.sub(" ", line.casefold()).strip()


def merge_page_text(native: list[tuple[float, float, str]],
                    recognised: list[tuple[float, float, str]]) -> tuple[str, int]:
    """Merge a page's text layer with what recognition read from its image.

    Both lists are (y, x, line) in the SAME image coordinates. The text layer
    is kept whole - it is exact where OCR is a guess - and a recognised line
    is added only when the text layer does not already say it: its words
    appear there in order, or it is a near-identical misreading of one of its
    lines. Lines are then laid out top to bottom, left to right, so a digital
    header stays above the scanned body and a footer or stamp below it.

    Returns (merged text, number of recognised lines added). Zero added means
    recognition contributed nothing new on this page.
    """
    native_norms = [n for n in (_norm(t) for _, _, t in native) if n]
    haystack = f" {' '.join(native_norms)} "
    added: list[tuple[float, float, str]] = []
    for y, x, line in recognised:
        n = _norm(line)
        if not n:
            continue
        if f" {n} " in haystack:
            continue
        if any(SequenceMatcher(None, n, m).ratio() >= _DUP_RATIO for m in native_norms):
            continue
        added.append((y, x, line))
    items = [(y, x, t) for y, x, t in native if t.strip()] + added
    items.sort(key=lambda it: (round(it[0] / 6.0), it[1]))
    return "\n".join(t for _, _, t in items), len(added)


def _native_lines(stored_path: str, page_no: int, scale: float) -> list[tuple[float, float, str]]:
    """The page's text-layer lines as (y, x, text) in rendered-image pixels."""
    import pymupdf

    out: list[tuple[float, float, str]] = []
    with pymupdf.open(stored_path) as doc:
        page = doc.load_page(page_no - 1)
        m = page.rotation_matrix * pymupdf.Matrix(scale, scale)
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(sp.get("text", "") for sp in line.get("spans", []))
                if not text.strip():
                    continue
                r = pymupdf.Rect(line["bbox"]) * m
                out.append((min(r.y0, r.y1), min(r.x0, r.x1), text))
    return out


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
    low_conf_boxes: int
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


def _box_origin(box) -> tuple[float, float]:
    """(y, x) of a recogniser box: its top-left over the four corners."""
    try:
        return (float(min(pt[1] for pt in box)), float(min(pt[0] for pt in box)))
    except Exception:  # noqa: BLE001 - a box of unexpected shape sorts first
        return (0.0, 0.0)


def recognise_batch(stored_path: str, sha256: str, page_nos: list[int]) -> list[tuple]:
    """Recognise the given 1-based pages. Runs in a WORKER PROCESS.

    Returns plain tuples so the payload pickles cheaply, the same contract
    extract_batch uses. The engine is built per worker call rather than held:
    the whole point of the subprocess is that its footprint is reclaimed.

    A page that also has a text layer (routed as `image_dominant`) is MERGED:
    the text layer is kept and only what it does not already say is added
    from recognition (`merge_page_text`). When recognition adds nothing, the
    stored text is empty, so the page keeps its text layer and is not claimed
    as recognised. A page that raises is returned with its error, never
    dropped: one bad page must not kill a batch or hold the document.
    """
    from .pageimage import render_page

    import time

    ocr = _build_engine()
    out: list[tuple] = []
    doc = {"sha256": sha256, "stored_path": stored_path}
    scale = settings.ocr_dpi / 72.0
    for pno in page_nos:
        t0 = time.perf_counter()
        try:
            image = render_page(doc, pno, dpi=settings.ocr_dpi)
            res = ocr(str(image))
            texts = list(res.txts) if res.txts else []
            scores = [float(s) for s in res.scores] if res.scores is not None else []
            boxes = getattr(res, "boxes", None)
            boxes = list(boxes) if boxes is not None else []
            native = _native_lines(stored_path, pno, scale)
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill a batch
            out.append((pno, "", None, None, 0, 0, round(time.perf_counter() - t0, 3), 0, "",
                        f"{type(exc).__name__}: {exc}"[:500]))
            continue
        if any(t.strip() for _, _, t in native):
            origins = [_box_origin(boxes[i]) if i < len(boxes) else (float("inf"), float(i))
                       for i in range(len(texts))]
            merged, added = merge_page_text(
                native, [(y, x, t) for (y, x), t in zip(origins, texts)])
            raw = merged if added else ""
        else:
            raw = "\n".join(texts)
        # Through normalise_text, exactly as extraction does, so symbol-font
        # control characters cannot reach chunking.
        text = normalise_text(raw)
        viol, sample = alphabet_violations(text, settings.ocr_expected_script)
        # mean/min collapse a whole page to one number each; a page with one
        # bad word among 200 and a page with fifty bad words can share the
        # same min. This counts individual boxes below the threshold, which
        # neither the mean nor the min can tell apart (settings.ocr_low_conf_threshold).
        low_conf = sum(1 for s in scores if s < settings.ocr_low_conf_threshold)
        out.append((
            pno, text,
            round(sum(scores) / len(scores), 4) if scores else None,
            round(min(scores), 4) if scores else None,
            len(texts), low_conf, round(time.perf_counter() - t0, 3), viol, sample, None,
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
                  rows: list[tuple], model: str) -> dict:
    """Persist one batch and advance the checkpoint atomically.

    A page whose recognition raised is stored too - empty text, `error` set -
    so it is CONSUMED: `pending_pages` no longer returns it, the ledger shows
    it as `ocr_failed` with the reason, and the rest of the document goes on
    to embedding (audit F7). Skipping it left the page pending forever, and
    the ingest loop failed the whole document on the churn guard.

    Returns this batch's own counts: rows stored, pages that produced text,
    pages that failed.
    """
    conn = connect()
    now = _now()
    payload = []
    with_text = failed = 0
    for (pno, text, mean_c, min_c, boxes, low_conf, secs, viol, sample, err) in rows:
        if err is not None:
            failed += 1
            text, mean_c, min_c, boxes, low_conf, viol, sample = "", None, None, 0, 0, 0, ""
        elif text.strip():
            with_text += 1
        payload.append((doc_id, pno, text, len(text.strip()), ENGINE, model,
                        settings.ocr_dpi, mean_c, min_c, boxes, low_conf, viol, sample,
                        secs or 0.0, now, batch_no, err))
    with conn:
        if payload:
            conn.executemany(
                """INSERT OR REPLACE INTO page_ocr
                   (document_id, page_no, text, char_count, engine, model, dpi,
                    mean_conf, min_conf, box_count, low_conf_boxes, alphabet_violations,
                    alphabet_sample, seconds, recognised_at, batch_no, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
    return {"stored": len(payload) - failed, "with_text": with_text, "failed": failed}


def retry_failed(doc_id: str) -> int:
    """Make this document's FAILED pages pending again. Returns how many.

    A failed page is consumed so it cannot block the document; this is the
    deliberate way back, for after the cause (a missing model file, a
    corrupt render cache) is fixed. Successful and blank pages are kept.
    """
    conn = connect()
    with conn:
        return conn.execute(
            "DELETE FROM page_ocr WHERE document_id = ? AND error IS NOT NULL",
            (doc_id,)).rowcount


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
                "pages_remaining": 0, "pages_failed": 0,
                "alphabet_violations": 0, "seconds": 0.0, "batches": 0,
                "model": model_signature()}

    size = settings.ocr_batch_size
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    model = model_signature()
    recognised = with_text = failed = 0

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
            counts = _commit_batch(doc_id, None, nxt, rows, model)
            recognised += counts["stored"]
            with_text += counts["with_text"]
            failed += counts["failed"]
            if progress:
                progress(recognised, len(todo))

    remaining = len(pending_pages(doc_id))
    stats = conn.execute(
        "SELECT COALESCE(SUM(alphabet_violations),0) viol FROM page_ocr WHERE document_id = ?",
        (doc_id,),
    ).fetchone()
    return {
        "document_id": doc_id, "filename": doc["filename"],
        "pages_pending": len(todo), "pages_recognised": recognised,
        "pages_remaining": remaining,
        # THIS ROUND's pages that produced text, not the document's running
        # total: the ingest loop re-chunks when this is non-zero, and a
        # cumulative count re-chunked after every round that added nothing.
        "pages_with_text": with_text,
        "pages_failed": failed,
        "alphabet_violations": stats["viol"],
        "seconds": timer.seconds(), "batches": len(batches),
        "model": model,
    }
