"""A page with no field because it is a cover or a notes page (order 235 item 3).

A datasheet's page 1 is often a cover: a title block, a revision table, a
document number, a list of notes. Both readers (the code readers and the AI
reader) read it and found no datasheet field. With the picture reader off, the
page ledger then called it "not read" ("the picture reader could not be asked"),
and every requirement the sheet did not state carried UNREAD_PAGES, which
blocked the CRS for a page that holds no values.

THE TEXT CHECK, general and code-only, two parts that must BOTH hold:
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
Nothing here is stored but the verdict's wording: no page text.
"""

from __future__ import annotations

import re

from . import claims, numparse, row_noise

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
    }
)


_NEXT_WORD = re.compile(
    r"\s*([A-Za-z\u00b0\u00b5%][A-Za-z0-9\u00b0\u00b5/\u00b2\u00b3.]*)"
)


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


def page_text(stored_path: str | None, page_no: int) -> str | None:
    """The page's own text layer, or None when it cannot be read (no file, an
    office input, an unopenable file, a page out of range)."""
    from . import datasheet_inputs

    if not stored_path or datasheet_inputs.is_office_input(stored_path):
        return None
    try:
        import pymupdf

        with pymupdf.open(stored_path) as doc:
            if not 1 <= page_no <= doc.page_count:
                return None
            return doc[page_no - 1].get_text()
    except Exception:  # noqa: BLE001 - the page then stays unread
        return None


def is_cover_or_notes(dropped: dict[str, int], text: str | None) -> bool:
    """Both parts of the text check hold. `text` None (unreadable) is never."""
    reasons = {reason for reason, n in dropped.items() if n}
    return (
        text is not None
        and bool(text.strip())
        and reasons <= FURNITURE
        and not has_measured_value(text)
    )


def checked(reason: str | None) -> bool:
    """Did the text check mark this ledger reason?"""
    return str(reason or "").startswith(MARK)
