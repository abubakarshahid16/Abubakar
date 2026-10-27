"""A page with no field because it is a cover or a notes page (order 235 item 3).

A datasheet's page 1 is often a cover: a title block, a revision table, a
document number, a list of notes. Both readers (the code readers and the AI
reader) read it and found no datasheet field. With the picture reader off, the
page ledger then called it "not read" ("the picture reader could not be asked"),
and every requirement the sheet did not state carried UNREAD_PAGES, which
blocked the CRS for a page that holds no values.

THE TEXT CHECK, general and code-only; every part must hold:
1. the readers record WHY each recovered label/value pair was dropped; every
   one was dropped as page furniture (a title block, a revision table, a ruler,
   column headings, a note or clause reference, a job or order number, a header
   or footer, the tag, a date). One pair dropped for a reason that could hide a
   value (the value gate, a merged block, a fragment label, a form label with no
   answer) means the page stays unread.
2. the page's own text holds no measured value: no number followed by a unit
   the system knows (`claims.normalise`). A drawing, a table or a data page has
   one; a cover or a notes page does not. A page with no text layer is the OCR
   tier's, never a cover page here.
3. no picture covers a tenth of the page (`IMAGE_SHARE`): values may sit in the
   picture, which only the picture reader could read.
4. no line of the text reads "label: value" unless its label is a title-block
   word (document no, revision, date, sheet...): a cover page that also carries
   a missed field ("Casing material: Duplex") stays unread.
At least one furniture pair is REQUIRED: a page where both readers recovered no
pair at all proves nothing about what it holds, so it stays unread.
Nothing here is stored but the verdict's wording: no page text.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

from . import claims, numparse, row_noise

log = logging.getLogger(__name__)

#: The stored file of the sheet being read, set by `remember` where extraction
#: opens it. A ContextVar, like `datasheets._PAGE_FAILURES`: a concurrent
#: extraction in another thread must not see this one's file.
_STORED_PATH: ContextVar[str | None] = ContextVar("cover_page_path", default=None)

#: The page's own words in the ledger, so the coverage can tell the check ran.
MARK = "No fields, cover/notes page (text checked)."

#: Drop reasons that are page furniture, never a value.
FURNITURE = frozenset(
    {
        row_noise.RULER,
        row_noise.REVISION,
        row_noise.DOCUMENT_ID,
        row_noise.HEADER_AS_VALUE,
        row_noise.REFERENCE_ONLY,
        row_noise.IDENTIFIER_NUMBER,
        "furniture",
        "tag row",
        "date",
        "furniture, tag, date or blank",
        "geometry: furniture, tag or date",
    }
)


_NEXT_WORD = re.compile(
    r"\s*([A-Za-z\u00b0\u00b5%][A-Za-z0-9\u00b0\u00b5/\u00b2\u00b3.]*)"
)


#: A printed "label: value" line. On a cover page only the title block's own
#: labels may look like this; any other label with an answer beside it is a
#: field the readers may have missed ("Casing material: Duplex", "Flange
#: rating: Class 300", "Size: DN 50"), and the page stays unread.
_FIELD_LINE = re.compile(r"^\s*([A-Za-z][\w ./()#-]{1,40}?)\s*[:=]\s*\S", re.MULTILINE)
#: Words of a title block's labels (document number, revision, date, sheet...).
TITLE_BLOCK_WORDS = frozenset(
    {
        "document",
        "doc",
        "drawing",
        "dwg",
        "no",
        "number",
        "rev",
        "revision",
        "date",
        "sheet",
        "page",
        "of",
        "project",
        "title",
        "client",
        "company",
        "job",
        "order",
        "contract",
        "status",
        "issue",
        "issued",
        "approved",
        "checked",
        "prepared",
        "by",
        "tag",
        "item",
        "unit",
        "area",
        "site",
        "purchase",
        "po",
    }
)
)


def has_field_line(text: str) -> bool:
    """True when some line reads as a "label: value" whose label is not made
    only of title-block words."""
    for found in _FIELD_LINE.finditer(text):
        words = re.findall(r"[a-z]+", found.group(1).lower())
        if words and not set(words) <= TITLE_BLOCK_WORDS:
            return True
    return False


def has_measured_value(text: str) -> bool:
    """True when `text` holds a number followed by a unit the system knows.
    A unit word that happens to be a known unit ("3 in the notes") counts: the
    mistake is on the safe side, the page stays unread."""
    for found in numparse.find_numbers(text):
        if found.value is None:
            continue
        word = _NEXT_WORD.match(text, found.end)
        if (
            word
            and claims.normalise(found.raw, word.group(1)).normalized_value is not None
        ):
            return True
    return False


def remember(stored_path: str | None) -> str | None:
    """Note the file being read (returns it unchanged, so it wraps the line
    that resolves it)."""
    _STORED_PATH.set(stored_path)
    return stored_path


#: A page whose images cover at least this share of it may hold values only in
#: the picture (a scanned insert, a nameplate photo): the picture reader was
#: needed and could not be asked, so the page is never called a cover page.
#: A logo is far below this.
IMAGE_SHARE = 0.10


def page_view(page_no: int) -> tuple[str, bool] | None:
    """(the page's own text, whether pictures cover at least `IMAGE_SHARE` of
    it) in the file being read; None when it cannot be read (no file, an
    office input, an unopenable file, a page out of range). Opens the file per
    call: asked only for pages both readers found no field on."""
    from . import datasheet_inputs, datasheets

    stored_path = _STORED_PATH.get()
    # Only while an extraction is running (its page-failure record is set and
    # is reset in its `finally`): a path left over from an earlier sheet is
    # never read for a later one.
    if datasheets._PAGE_FAILURES.get() is None:
        return None
    if not stored_path or datasheet_inputs.is_office_input(stored_path):
        return None
    try:
        import pymupdf

        with pymupdf.open(stored_path) as doc:
            if not 1 <= page_no <= doc.page_count:
                return None
            page = doc[page_no - 1]
            covered = 0.0
            for image in page.get_image_info():
                x0, y0, x1, y1 = image["bbox"]
                covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
            area = page.rect.width * page.rect.height
            return page.get_text(), bool(area) and covered / area >= IMAGE_SHARE
    except Exception as exc:  # noqa: BLE001 - the page then stays unread
        log.info("cover_page: the page could not be read (%s)", type(exc).__name__)
        return None


def is_cover_or_notes(dropped: dict[str, int], view: tuple[str, bool] | None) -> bool:
    """All parts of the text check hold: the page could be read, it has text
    and no large picture, every dropped pair was page furniture AND at least
    one pair was (an empty page of recovered pairs is not evidence of furniture:
    a notes or data page whose values are words would pass), and the text holds
    no measured value."""
    if view is None:
        return False
    text, picture = view
    reasons = {reason for reason, n in dropped.items() if n}
    return (
        bool(text.strip())
        and not picture
        and bool(reasons)
        and reasons <= FURNITURE
        and not has_measured_value(text)
        and not has_field_line(text)
    )


def checked(reason: str | None) -> bool:
    """Did the text check mark this ledger reason?"""
    return str(reason or "").startswith(MARK)
