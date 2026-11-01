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
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .quality import normalise_text

log = logging.getLogger(__name__)

KIND_PDF, KIND_WORD, KIND_SHEET, KIND_IMAGE = "pdf", "word", "xlsx", "image"
SOURCE_NATIVE, SOURCE_OCR, SOURCE_WORD, SOURCE_SHEET, SOURCE_IMAGE = (
    "native",
    "ocr",
    "word",
    "sheet",
    "image",
)

WHY_SCANNED = "no usable text layer (a scan or a blank page), waiting for OCR"
WHY_IMAGE = "image file: waiting for OCR, no text read yet"
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
        return WHY_IMAGE if source == SOURCE_IMAGE else WHY_SCANNED
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

    if settings.datasheet_office_input:  # the datasheet reader's own pages, as today
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


def read_sheet(path: str | os.PathLike) -> IntakeResult:
    """One page per visible sheet; its cells are the page's table."""
    from . import datasheet_inputs

    reading = datasheet_inputs.read_xlsx(path)
    pages = []
    for p in reading.pages:
        text = normalise_text(p.text)
        pages.append(
            _page(
                p.page_no,
                text,
                SOURCE_SHEET,
                datasheet_inputs.tables_json(p, text),
                empty=not p.rows,
            )
        )
    notes = list(reading.notes)
    if not pages:
        notes.append("no visible sheet to read")
    return IntakeResult(KIND_SHEET, pages, notes)


def read_image(path: str | os.PathLike) -> IntakeResult:
    """A PNG or JPEG is ONE page that needs OCR. Not recognised here."""
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
    return IntakeResult(
        KIND_IMAGE, [_page(1, "", SOURCE_IMAGE, needs_ocr=True, route="image_file")]
    )


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
