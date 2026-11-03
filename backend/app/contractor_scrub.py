"""Item 14c (owner 3 Nov 11:40), behind CRS_CONTRACTOR_NO_ENGINEER_WORDS_ENABLED: the contractor copy never tells the
contractor that an engineer must confirm or check anything. One scrub (`scrub_text`) for the text WE write; what the
contractor's own documents gave us (file names, tags, titles, references) stays verbatim; a code check lists what is
left and the internal copy's Review notes count it. Pure text rules: no layout, no model, no socket (rule 13).
"""

from __future__ import annotations

import re

from .config import settings

_ENGINEER_WORD = re.compile(
    r"\bengineers?\b|\bengr\b\.?|\beng\.|"
    r"\bengineering\s+(?:reviewers?|review|to\s+(?:confirm|check|tick))\b",
    re.IGNORECASE,
)
_PARTS = re.compile(r"(?<=[;\n])|(?<=[.!?])\s+")


def engineer_words_in(text) -> bool:
    """Whether a text the contractor reads names the engineer (item 14c, the code check)."""
    return bool(_ENGINEER_WORD.search(str(text or "")))


_ASK_TO_ENGINEER = re.compile(
    r"\s+(?:from|by|of|to)\s+the\s+engineers?\b", re.IGNORECASE
)


def scrub_text(text) -> str:
    """One scrub for the text WE write on the contractor copy. A request addressed to the engineer keeps its ask
    ("Clarification required from the Engineer." reads "Clarification required."); any part (between ; . ! ? and line
    ends) that still names the engineer, an abbreviation or the engineering reviewer is cut; a bare label that is
    nothing but the word reads "reviewer". Nothing else is reworded."""
    said = str(text if text is not None else "")
    if not engineer_words_in(said):
        return said
    parts = [_ASK_TO_ENGINEER.sub("", p).strip() for p in _PARTS.split(said)]
    parts = [p for p in parts if p and not engineer_words_in(p)]
    if parts:
        return " ".join(parts)
    short = len(said.split()) <= 3 and not re.search(r"[;.!?]\s*$", said.strip())
    return _ENGINEER_WORD.sub("reviewer", said) if short else ""


#: The columns that carry the contractor's own fields, copied from their documents: kept verbatim. Identified by the
#: column's header cell and the row's role (a table row), never by what the text says.
OWN_COLUMNS = ("Document Name", "Page No./Section", "Standard Reference")
#: Fields of a row dict that are the contractor's own, for the count of what is left.
OWN_KEYS = ("document_name", "page_section", "standard_reference")


def _own(ws, cell, header_row: int, table_rows: int, own_cols: set) -> bool:
    """Is this cell the contractor's own field: a table row of the CRS sheet in an own column, or a value of the header
    block (the submittal's numbers and title)? Never a note, a notice, Priority, the AI or trust columns."""
    if ws.title != ws.parent.worksheets[0].title:
        return False
    in_table = header_row < cell.row <= header_row + table_rows
    return (in_table and cell.column in own_cols) or (
        3 <= cell.row < header_row and cell.column == 3
    )


def contractor_words(row: dict) -> dict:
    """The contractor copy only, per row, on the text we write (the comment and who made it). Before the no-text rule,
    so a comment that is nothing but engineer wording is empty and its row is withheld and counted, never issued as an
    instruction. Switch off: the row as it was."""
    if not settings.crs_contractor_no_engineer_words_enabled:
        return row
    out = (
        {**row, "comment": scrub_text(row.get("comment"))}
        if "comment" in row
        else dict(row)
    )
    if engineer_words_in(row.get("comment_by")):
        out["comment_by"] = scrub_text(row["comment_by"])
    return out if out != row else row


def scrub_workbook(wb, table_rows: int = 0) -> None:
    """The contractor copy only, last: every string cell of every sheet, each sheet name and each document property
    goes through `scrub_text`, except the cells that carry the contractor's own field (`_own`), which stay as they
    wrote them. `table_rows` is the number of rows in the CRS table."""
    if not settings.crs_contractor_no_engineer_words_enabled:
        return
    from . import crs_export as ce

    header_row = ce.COLUMN_HEADER_ROW
    first = wb.worksheets[0]
    own_cols = {c.column for c in first[header_row] if c.value in OWN_COLUMNS}
    for ws in wb.worksheets:
        for line in ws.iter_rows():
            for cell in line:
                if not isinstance(cell.value, str) or not engineer_words_in(cell.value):
                    continue
                if not _own(ws, cell, header_row, table_rows, own_cols):
                    cell.value = scrub_text(cell.value) or None
        if engineer_words_in(ws.title):
            ws.title = scrub_text(ws.title) or "Sheet"
    for name in (
        "creator",
        "lastModifiedBy",
        "title",
        "subject",
        "description",
        "keywords",
        "category",
    ):
        value = getattr(wb.properties, name, None)
        if isinstance(value, str) and engineer_words_in(value):
            setattr(wb.properties, name, scrub_text(value))


NOTE_LEFT = "Contractor copy: cells that still name the engineer"


def left_over_cells(view: dict) -> list[str]:
    """After the scrub, the cells of these rows that still name the engineer: every string field of the row. An own
    field (file name, section, reference) is kept as the contractor wrote it, so a hit there is theirs; any other
    field that still hits means the scrub missed something we wrote. Names the field, never its text."""
    left = []
    for r in view["rows"]:
        for k, v in r.items():
            if not isinstance(v, str):
                continue
            kept = v if k in OWN_KEYS else scrub_text(v)
            if engineer_words_in(kept):
                left.append(k)
    return left


def note_left_over(view: dict) -> dict:
    """Internal copy, switch on: a Review note counting those cells, so the engineer sees what the scrub left."""
    left = left_over_cells(view)
    if not left:
        return view
    detail = (
        f"{len(left)} cells ({', '.join(sorted(set(left)))}) keep wording that names the engineer: the contractor's own "
        "file name, tag or title copied from the source, or hand-typed text. They are not changed."
    )
    note = {"note": NOTE_LEFT, "standard": "", "count": len(left), "detail": detail}
    return {**view, "review_notes": [*view["review_notes"], note]}
