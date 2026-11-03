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


def scrub_text(text, keep=frozenset()) -> str:
    """One scrub for the text WE write on the contractor copy. A request addressed to the engineer keeps its ask
    ("Clarification required from the Engineer." reads "Clarification required."); any part (between ; . ! ? and line
    ends) that still names the engineer, an abbreviation or the engineering reviewer is cut; a bare label that is
    nothing but the word reads "reviewer". A part that is one of the `keep` values (the contractor's own file name,
    tag, title or reference, copied from the source) is left verbatim. Nothing else is reworded."""
    said = str(text if text is not None else "")
    if not engineer_words_in(said) or said.strip() in keep:
        return said
    parts = []
    for p in _PARTS.split(said):
        q = p.strip() if p.strip() in keep else _ASK_TO_ENGINEER.sub("", p).strip()
        if q and (q in keep or not engineer_words_in(q)):
            parts.append(q)
    if parts:
        return " ".join(parts)
    short = len(said.split()) <= 3 and not re.search(r"[;.!?]\s*$", said.strip())
    return _ENGINEER_WORD.sub("reviewer", said) if short else ""


def protected_values(view: dict) -> frozenset:
    """What the contractor's own documents gave us, kept verbatim by the scrub: file names, sections and tags, standard
    references, the header values and the title lines."""
    found = {
        str(r.get(k) or "").strip()
        for r in view.get("rows", [])
        for k in ("document_name", "page_section", "standard_reference")
    }
    found |= {str(h.get("value") or "").strip() for h in view.get("header", [])}
    found |= {x.strip() for x in str(view.get("title") or "").split("\n")}
    return frozenset(found - {""})


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


def scrub_workbook(wb, keep=frozenset()) -> None:
    """The contractor copy only, last: every string cell of every sheet, each sheet name and each document property
    goes through `scrub_text`, so a note, a header or a meta value we wrote is covered by the one rule. Values in
    `keep` stay as the contractor wrote them."""
    if not settings.crs_contractor_no_engineer_words_enabled:
        return
    for ws in wb.worksheets:
        for line in ws.iter_rows():
            for cell in line:
                if isinstance(cell.value, str) and engineer_words_in(cell.value):
                    cell.value = scrub_text(cell.value, keep) or None
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
    """After the scrub, the contractor-copy cells of these rows that still name the engineer: the contractor's own text
    kept verbatim (a file name, tag, title) or hand-typed wording. Names the cell, never its text."""
    keep = protected_values(view)
    return [
        k
        for r in view["rows"]
        for k in (
            "comment",
            "comment_by",
            "document_name",
            "page_section",
            "standard_reference",
        )
        if engineer_words_in(scrub_text(r.get(k), keep))
    ]


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
