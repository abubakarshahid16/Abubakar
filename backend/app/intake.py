"""One intake layer (W5b-01, #525, part 1; ONE_INTAKE_ENABLED, off by default).

Every file that reaches extraction is read here into ONE shape: pages
(page_no, text, source, tables, flags) and, for every page that holds no
reading, a stated reason. A file that cannot be read is REFUSED with a code and
a sentence; nothing is dropped in silence (CLAUDE.md rule 4).

Nothing here opens a socket or loads a model. The PDF and Word readers are the
existing ones (`extract.extract_batch`, `docx_reader`), so what is stored for
them is what is stored today. Excel reads one page per visible sheet
(`datasheet_inputs.read_xlsx`). An image is ONE page that still needs OCR: this
module does not recognise it and says so as the page's reason.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from .config import settings
from .quality import normalise_text

log = logging.getLogger(__name__)

KIND_PDF, KIND_WORD, KIND_SHEET, KIND_IMAGE = "pdf", "word", "xlsx", "image"
SOURCE_NATIVE, SOURCE_OCR, SOURCE_WORD, SOURCE_SHEET = "native", "ocr", "word", "sheet"

WHY_SCANNED = "no usable text layer (a scan or a blank page), waiting for OCR"
WHY_BLANK_PDF = "blank page: no text layer and no picture"
WHY_EMPTY_SHEET = "empty sheet: no cell holds a value"
WHY_EMPTY_WORD = "empty page: no text in this part of the document"

_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
MAX_IMAGE_PIXELS = 100_000_000


class IntakeRefused(ValueError):
    """A file intake will not read. `code` is a stable slug, the message the sentence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class IntakePage:
    page_no: int
    text: str
    source: str
    tables_json: str | None = None
    needs_ocr: bool = False
    equation_heavy: bool = False
    ocr_route: str | None = None
    #: None when the page holds a reading; else why it holds none.
    not_read_reason: str | None = None


@dataclass
class IntakeResult:
    kind: str
    pages: list[IntakePage]
    #: What was deliberately not read, in counts - never document text.
    notes: list[str] = field(default_factory=list)
    #: Word: pages are reading units, not print pages (documents.pagination = 'flow').
    flow: bool = False
    #: (page_no, code, sentence) for what was only partly read or skipped; page_no 0 = the whole file.
    reasons: list[tuple[int, str, str]] = field(default_factory=list)

    def not_read(self) -> dict[int, str]:
        return {p.page_no: p.not_read_reason for p in self.pages if p.not_read_reason}


def detect(path: str | os.PathLike) -> str:
    """`pdf`, `word`, `xlsx` or `image` from the file's bytes; else IntakeRefused."""
    import zipfile

    with Path(path).open("rb") as fh:
        head = fh.read(16)
    if head.startswith(b"%PDF-"):
        return KIND_PDF
    if head.startswith(_IMAGE_MAGIC):
        return KIND_IMAGE
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
        except (OSError, zipfile.BadZipFile) as exc:
            raise IntakeRefused(
                "corrupt_zip", "The file is a damaged zip, so it cannot be read."
            ) from exc
        if "xl/workbook.xml" in names:
            return KIND_SHEET
        if "word/document.xml" in names:
            return KIND_WORD
        if "ppt/presentation.xml" in names:
            raise IntakeRefused(
                "unsupported_office", "PowerPoint (.pptx) files are not read yet."
            )
        raise IntakeRefused(
            "unsupported_zip",
            "This zip is not a Word or Excel file, so it is not read.",
        )
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise IntakeRefused(
            "unsupported_office",
            "Legacy Office files (.doc, .xls, .ppt) are not read; save as .docx or .xlsx.",
        )
    raise IntakeRefused(
        "unsupported_type",
        "Only PDF, Word (.docx), Excel (.xlsx), PNG and JPEG are read.",
    )


def _reason(source: str, text: str, needs_ocr: bool) -> str | None:
    if needs_ocr:
        return WHY_SCANNED
    if text.strip():
        return None
    return {SOURCE_SHEET: WHY_EMPTY_SHEET, SOURCE_WORD: WHY_EMPTY_WORD}.get(
        source, WHY_BLANK_PDF
    )


def _page(
    page_no,
    text,
    source,
    tables=None,
    needs_ocr=False,
    eq=False,
    route=None,
    empty=False,
) -> IntakePage:
    # `empty`: a sheet's text is its title line, so emptiness is judged on its rows.
    return IntakePage(
        page_no,
        text,
        source,
        tables,
        needs_ocr,
        eq,
        route,
        _reason(source, "" if empty else text, needs_ocr),
    )


def read_pdf(path: str | os.PathLike) -> IntakeResult:
    from . import extract

    rows = extract.extract_batch(str(path), 1, extract.page_count(str(path)))
    return IntakeResult(
        KIND_PDF,
        [
            _page(p, t, SOURCE_NATIVE, tb, bool(o), bool(e), r)
            for p, t, o, e, r, tb in rows
        ],
    )


def read_word(path: str | os.PathLike) -> IntakeResult:
    from . import datasheet_inputs, docx_reader

    # The datasheet reader's own pages, as today, unless the file's own pages decide.
    if settings.datasheet_office_input and not settings.word_page_markers_enabled:
        reading = datasheet_inputs.read(path)
        pages = []
        for p in reading.pages:
            text = normalise_text(p.text)
            pages.append(
                _page(
                    p.page_no, text, SOURCE_WORD, datasheet_inputs.tables_json(p, text)
                )
            )
        return IntakeResult(KIND_WORD, pages, list(reading.notes))
    if not settings.docx_input_enabled:
        raise IntakeRefused(
            "word_not_enabled", "Word input is switched off (DOCX_INPUT_ENABLED)."
        )
    structure = docx_reader.read_structure(path)
    return IntakeResult(
        KIND_WORD,
        [
            _page(i, normalise_text(t), SOURCE_WORD)
            for i, t in enumerate(structure.pages, 1)
        ],
        list(structure.notes),
        flow=True,
    )


_CUT_ROWS = re.compile(r"sheet (\d+) cut at (\d+) rows")
_CUT_COLS = re.compile(r"sheet (\d+) cut at (\d+) columns")
_CUT_CELL = re.compile(r"sheet (\d+): a cell cut at (\d+) characters")
_HIDDEN = re.compile(r"hidden sheet (\d+) skipped")


def _formula_gaps(path: str | os.PathLike) -> dict[int, int]:
    """Per workbook sheet position: formula cells whose result was never stored.

    `data_only=True` shows such a cell as empty; this counts them so they are named."""
    import openpyxl

    from . import datasheet_inputs as di

    gaps: dict[int, int] = {}
    kw = {"read_only": True, "keep_links": False}
    wf = openpyxl.load_workbook(path, data_only=False, **kw)
    wv = openpyxl.load_workbook(path, data_only=True, **kw)
    try:
        for i, (sf, sv) in enumerate(
            zip(wf.worksheets, wv.worksheets, strict=False), start=1
        ):
            if getattr(sf, "sheet_state", "visible") != "visible":
                continue
            n = 0
            rows = zip(
                sf.iter_rows(values_only=True),
                sv.iter_rows(values_only=True),
                strict=False,
            )
            for r, (rf, rv) in enumerate(rows, start=1):
                if r > di.MAX_SHEET_ROWS:
                    break
                n += sum(
                    1
                    for f, v in zip(rf[: di.MAX_SHEET_COLS], rv, strict=False)
                    if isinstance(f, str) and f.startswith("=") and v is None
                )
            if n:
                gaps[i] = n
    finally:
        wf.close()
        wv.close()
    return gaps


def _sheet_reasons(path, reading) -> list[tuple[int, str, str]]:
    """Stored reasons for what a workbook read left out (hidden, cut, uncached)."""
    notes = reading.notes
    hidden = {int(m.group(1)) for n in notes if (m := _HIDDEN.search(n))}
    total = len(reading.pages) + len(hidden)
    # Pages are the visible sheets in workbook order.
    visible = [i for i in range(1, total + 1) if i not in hidden]
    page_of = {
        pos: page.page_no for pos, page in zip(visible, reading.pages, strict=False)
    }
    reasons: list[tuple[int, str, str]] = [
        (0, "hidden_sheet", f"not read: hidden sheet {i} (workbook position)")
        for i in sorted(hidden)
    ]
    cells: dict[int, int] = {}
    for n in notes:
        if m := _CUT_ROWS.search(n):
            reasons.append(
                (
                    page_of[int(m[1])],
                    "row_limit",
                    f"rows after row {m[2]} not read: row limit {m[2]}",
                )
            )
        elif m := _CUT_COLS.search(n):
            reasons.append(
                (
                    page_of[int(m[1])],
                    "column_limit",
                    f"columns after column {m[2]} not read: column limit {m[2]}",
                )
            )
        elif m := _CUT_CELL.search(n):
            cells[page_of[int(m[1])]] = cells.get(page_of[int(m[1])], 0) + 1
    for page_no, count in cells.items():
        reasons.append(
            (
                page_no,
                "cell_limit",
                f"{count} cell(s) cut at the character limit: the rest is not read",
            )
        )
    for pos, count in _formula_gaps(path).items():
        reasons.append(
            (
                page_of[pos],
                "formula_no_result",
                f"{count} formula cell(s) with no stored result - not read",
            )
        )
    return reasons


def read_sheet(path: str | os.PathLike) -> IntakeResult:
    """One page per visible sheet; its cells are the page's table.

    Nothing is lost without a reason: a hidden sheet, rows or columns past the
    limit, a cut cell and a formula with no stored result each become a stored
    reason on the page (or on the file, page 0, for a hidden sheet)."""
    from . import datasheet_inputs

    reading = datasheet_inputs.read_xlsx(path)
    notes = list(reading.notes)
    reasons = _sheet_reasons(path, reading)
    partly = {}
    for page_no, _code, why in reasons:
        if page_no:
            partly.setdefault(page_no, []).append(why)
    pages = []
    for p in reading.pages:
        text = normalise_text(p.text)
        page = _page(
            p.page_no,
            text,
            SOURCE_SHEET,
            datasheet_inputs.tables_json(p, text),
            empty=not p.rows,
        )
        if (
            p.page_no in partly
        ):  # partly read: still a reading, with what is missing named
            why = "; ".join(partly[p.page_no])
            page = replace(
                page,
                not_read_reason=(
                    page.not_read_reason + "; "
                    if page.not_read_reason
                    else "partly read: "
                )
                + why,
            )
        pages.append(page)
    if not pages:
        reasons.append(
            (0, "no_visible_sheet", "not read: the workbook has no visible sheet")
        )
    return IntakeResult(KIND_SHEET, pages, notes, reasons=reasons)


def check_image(path: str | os.PathLike) -> tuple[int, int]:
    """(width, height) of an image that opens and is within the pixel limit; else IntakeRefused."""
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            w, h = img.size
    except Exception as exc:
        raise IntakeRefused(
            "bad_image", f"The image cannot be opened ({type(exc).__name__})."
        ) from exc
    if w * h > MAX_IMAGE_PIXELS:
        raise IntakeRefused(
            "image_too_large", f"The image is {w}x{h} pixels, over the limit."
        )
    return w, h


def read_image(path: str | os.PathLike) -> IntakeResult:
    """A PNG or JPEG reaching extraction as itself is REFUSED, with the reason.

    The OCR stage renders pages of a stored PDF only. An image UPLOAD (slice 2,
    `uploads_enabled()`) never reaches here: it is stored with `image_to_pdf`
    pages beside it, and those pages are what extraction reads."""
    check_image(path)
    raise IntakeRefused(
        "image_not_read_yet",
        "Image files (PNG, JPEG) are not read yet: the OCR stage reads PDF pages only. "
        "Put the picture in a PDF. Reading images is the next slice of #525.",
    )


# ------------------------------------------------- slice 2 (INTAKE_IMAGES_XLSX_ENABLED)

_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
#: A multi-page TIFF is read page by page; past this many frames it is refused.
MAX_IMAGE_FRAMES = 500


def uploads_enabled() -> bool:
    """#525 slice 2: images and workbooks are accepted and indexed through intake.

    Needs INTAKE_IMAGES_XLSX_ENABLED and ONE_INTAKE_ENABLED both on (slice 2
    reads through the slice 1 layer). Either off: uploads behave as today."""
    return bool(settings.intake_images_xlsx_enabled and settings.one_intake_enabled)


def image_suffix(head: bytes) -> str | None:
    """`.png`, `.jpg` or `.tif` from a file's first bytes; None for anything else."""
    if head.startswith(_IMAGE_MAGIC[0]):
        return ".png"
    if head.startswith(_IMAGE_MAGIC[1]):
        return ".jpg"
    if head.startswith(_TIFF_MAGIC):
        return ".tif"
    return None


def image_to_pdf(src: str | os.PathLike, dst: str | os.PathLike) -> int:
    """Write an image (every frame of a TIFF) as a PDF of picture-only pages; the page count.

    The page is sized so the OCR stage, rendering at `ocr_dpi`, sees the
    image's own pixels, neither scaled up nor down. The pages hold no text
    layer, so extraction routes each to OCR exactly as it routes a scanned PDF
    page, and the page ledger, page images and citations work unchanged. The
    picture is stored lossless (PNG); a JPEG's EXIF rotation is applied first.
    Local only: Pillow and PyMuPDF, no model, no socket."""
    import io

    import pymupdf
    from PIL import Image, ImageOps, ImageSequence

    from . import pdf_guard

    check_image(src)
    scale = 72.0 / settings.ocr_dpi
    frames: list[tuple[bytes, int, int]] = []
    pixels = 0
    try:
        with Image.open(src) as img:
            # Every page's DECLARED size first, read from its header without
            # decoding a pixel: a small first page cannot hide a huge later one.
            for n, frame in enumerate(ImageSequence.Iterator(img), start=1):
                if n > MAX_IMAGE_FRAMES:
                    raise IntakeRefused(
                        "image_too_many_frames",
                        f"The image has more than {MAX_IMAGE_FRAMES} pages, over the limit.",
                    )
                pixels += frame.size[0] * frame.size[1]
                if pixels > MAX_IMAGE_PIXELS:
                    raise IntakeRefused(
                        "image_too_large", "The image's pages are over the pixel limit."
                    )
            for frame in ImageSequence.Iterator(img):
                page = ImageOps.exif_transpose(frame)
                if page.mode not in ("1", "L", "RGB", "RGBA"):
                    page = page.convert("RGB")
                buf = io.BytesIO()
                page.save(buf, "PNG")
                frames.append((buf.getvalue(), page.width, page.height))
    except IntakeRefused:
        raise
    except Exception as exc:
        raise IntakeRefused(
            "bad_image", f"The image cannot be opened ({type(exc).__name__})."
        ) from exc
    with pdf_guard.held():
        out = pymupdf.open()
        try:
            for data, w, h in frames:
                page = out.new_page(width=w * scale, height=h * scale)
                page.insert_image(page.rect, stream=data)
            out.save(str(dst))
        finally:
            out.close()
    return len(frames)


_READERS = {
    KIND_PDF: read_pdf,
    KIND_WORD: read_word,
    KIND_SHEET: read_sheet,
    KIND_IMAGE: read_image,
}


def read(path: str | os.PathLike) -> IntakeResult:
    """Every page of the file, whatever it is, with a reason for each unread one."""
    result = _READERS[detect(path)](Path(path))
    if result.notes:  # counts and positions only
        log.info(
            "intake: %s read with %d note(s): %s",
            result.kind,
            len(result.notes),
            "; ".join(result.notes[:10]),
        )
    return result


def as_rows(result: IntakeResult) -> list[tuple]:
    """`extract_batch`-shaped rows: (page_no, text, needs_ocr, equation_heavy, route, tables)."""
    return [
        (p.page_no, p.text, p.needs_ocr, p.equation_heavy, p.ocr_route, p.tables_json)
        for p in result.pages
    ]


def store(doc_id: str, result: IntakeResult) -> int:
    """Keep what was not read (or only partly) where the document record can show it.

    Page 0 is the whole file. Replaces any earlier rows of this document, so a
    re-run states the same reasons once. Counts and positions only, no text."""
    from .db import connect

    rows = {(n, c, w) for n, c, w in result.reasons}
    rows |= {(n, "page_not_read", w) for n, w in result.not_read().items()}
    conn = connect()
    with conn:
        conn.execute("DELETE FROM intake_reasons WHERE document_id = ?", (doc_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO intake_reasons (document_id, page_no, code, reason)"
            " VALUES (?, ?, ?, ?)",
            [(doc_id, n, c, w) for n, c, w in sorted(rows)],
        )
    return len(rows)


def reasons_for(doc_id: str) -> list[dict]:
    """The stored reasons of a document, page by page (page 0 = the whole file).

    A database made before the table existed (init_db has not run on it yet)
    holds no reasons: [] , and a read never creates schema."""
    import sqlite3

    from .db import connect

    try:
        return [
            dict(r)
            for r in connect().execute(
                "SELECT page_no, code, reason FROM intake_reasons WHERE document_id = ?"
                " ORDER BY page_no, code",
                (doc_id,),
            )
        ]
    except sqlite3.OperationalError as exc:
        if "no such table: intake_reasons" not in str(exc):
            raise
        return []


def refusal_of(exc: BaseException, last_error: dict) -> tuple[str, str]:
    """(code, sentence) to record for a failed document: the refusal's own when
    intake refused the file, else the internal code and the redacted message."""
    from . import errors

    if isinstance(exc, IntakeRefused):
        return exc.code, exc.message
    return errors.INTERNAL, last_error["message"]


def coverage_part(document_id: str) -> dict:
    """What `page_ledger.coverage` adds: `_reasons_part`, and a Word file's read
    proof (`word_pages`, WORD_PAGE_MARKERS_ENABLED; off, nothing)."""
    from . import reading_state, word_pages

    part = _reasons_part(document_id) | word_pages.coverage_part(document_id)
    return part | reading_state.coverage_part(document_id)


def _reasons_part(document_id: str) -> dict:
    """What `page_ledger.coverage` adds for a document read through intake:
    `intake_reasons` = {page_no: [reason, ...]}, page "0" = the whole file.

    ONE_INTAKE_ENABLED off, or nothing stored: {} (nothing changes). A page
    states its own full reason once; file-level reasons (a hidden sheet) are
    kept apart."""
    if not settings.one_intake_enabled:
        return {}
    by_page: dict[str, list[str]] = {}
    own = {
        r["page_no"] for r in reasons_for(document_id) if r["code"] == "page_not_read"
    }
    for r in reasons_for(document_id):
        if r["page_no"] in own and r["code"] != "page_not_read":
            continue
        by_page.setdefault(str(r["page_no"]), []).append(r["reason"])
    if not by_page:
        return {}
    partly = {
        str(r["page_no"]): r["reason"]
        for r in reasons_for(document_id)
        if r["code"] == "page_not_read" and r["reason"].startswith("partly read:")
    }
    return {
        "intake_reasons": by_page,
        **({"pages_partly_read": partly} if partly else {}),
    }


def partly_part(coverage: dict) -> dict:
    """`pages_partly_read` for a summary, only when a page was read in part."""
    partly = coverage.get("pages_partly_read")
    return {"pages_partly_read": sorted(partly, key=int)} if partly else {}


def pages_read_count(coverage: dict | None) -> int:
    """Pages read into fields, NOT counting a page intake read only in part.

    The one count every summary of "pages read" uses (coverage consumers, the
    readiness strip, the CRS sentence, the review trace), so they cannot drift.
    Switch off, or nothing partly read: len(fact_pages) as before."""
    cov = coverage or {}
    partly = cov.get("pages_partly_read") or {}
    return sum(1 for p in cov.get("fact_pages") or [] if str(p) not in partly)


def split_partly(coverage: dict) -> dict:
    """A page intake read only in part is not fully read: it leaves `pages_read`
    (and `pages_not_read`, a reading did come back) for `pages_partly_read`, with
    its reason. `pages_total` stays the denominator, so read + partly read + not
    read add up to it."""
    partly = coverage.get("pages_partly_read")
    if not partly or "pages_read" not in coverage:
        return coverage
    out = dict(coverage)
    for key in ("pages_read", "pages_not_read"):
        out[key] = [p for p in coverage.get(key, []) if str(p) not in partly]
    out["pages_not_read_why"] = {
        p: w
        for p, w in coverage.get("pages_not_read_why", {}).items()
        if p not in partly
    }
    return out
