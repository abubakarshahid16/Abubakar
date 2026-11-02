"""What a reviewer may be told about a Word file's pages and contents
(WORD_PAGE_MARKERS_ENABLED; `docx_reader` reads the file).

One home for the words, so the CRS, the review notes, the ledger and the audit say
the same thing:

  * markers: "p.12", a real page.
  * partial: "p.12 (page marks partial)": Word saved more pages than its markers
    prove, so the number may be low. Never extrapolated.
  * none: the section heading, and plainly no page, in the cells this module
    writes. KNOWN GAP: comment text built elsewhere can still say "page N" and mean
    a reading part, so the switch must not go on for a Word file with no marks.

Off, or not a Word file: `page_cell` returns what it was given and the rest return
nothing. Reads the file (cached); no model, no socket, nothing written.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

from . import docx_reader, errors, stored_paths
from .config import settings
from .datasheet_inputs import KIND_DOCX, InputError, office_kind
from .db import connect
from .docx_pages import PAGES_MARKERS, PAGES_NONE, PAGES_PARTIAL
from .docx_reader import Structure

NO_PAGE = "no page number: this Word file saved no page marks"
PARTIAL = "page marks partial"
NOTE_NO_PAGES = "Word file with no page numbers"
NOTE_PARTIAL_PAGES = "Word file with partial page numbers"
NOTE_NOT_READ = "Word tables or pictures not read"

#: A lead `page_cell` writes, other than a plain "p.3".
_LEAD = re.compile(
    rf"^(?:p\.[\d, -]+ \({PARTIAL}\)|Section .*? \({NO_PAGE}\)|No page number: [^-]*?marks)(?: - |$)"
)

_PAGE_WORD_LEAD = re.compile(rf"^pages? \d+(?:-\d+)?(?: \({PARTIAL}\))?(?:, | - |$)")

#: Parsed files, by path, its state and how many readings it has. Small: one review
#: reads one submittal, and a parse is cheap beside a CRS row per finding.
_CACHE: dict[tuple, Structure] = {}
_CACHE_MAX = 8


def _structure(document_id: str | None) -> Structure | None:
    """The file behind this document, read; None when off or not a Word file."""
    if not settings.word_page_markers_enabled or not document_id:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    path = (
        stored_paths.local(row["stored_path"]) if row and row["stored_path"] else None
    )
    try:
        if not path or office_kind(path) != KIND_DOCX:
            return None
        state = Path(path).stat()
        readings = _readings(path)
        said = tuple(
            sorted((no, bool(r.text), r.reason or "") for no, r in readings.items())
        )
        key = (path, state.st_mtime_ns, state.st_size, said)
        if key not in _CACHE:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = docx_reader.read_structure(path, picture_readings=readings)
        return _CACHE[key]
    except (OSError, InputError) as exc:
        return errors.fell_back("word_pages: the file could not be read", exc, None)


def _readings(path: str) -> dict:
    from . import word_pictures

    return word_pictures.stored_readings(path)


def page_source(document_id: str | None) -> str | None:
    """ "markers", "partial" or "none" for a Word file; None for anything else."""
    structure = _structure(document_id)
    return structure.pagination.source if structure and structure.pagination else None


def unit(document_id: str | None) -> str:
    """What a progress line calls this file's numbered units: "part" only when a
    Word file has no pages to name. Switch off or a PDF: "page", as it always said."""
    return "part" if page_source(document_id) == PAGES_NONE else "page"


def _squash(text: str) -> str:
    return "".join(str(text).split()).lower()


def _section_of(structure: Structure, part: int, quotes: list[str]) -> str:
    """The heading a value on this reading part sits under: the block that holds
    its quote; else the part's first heading to its last, which is all that is known."""
    blocks = [b for b in structure.blocks if b.page == part]
    wanted = [_squash(q) for q in quotes if _squash(q)]
    for block in blocks:
        text = _squash(" ".join(docx_reader.block_lines(block)))
        if block.chain and any(q in text for q in wanted):
            return block.chain[-1]
    names = list(dict.fromkeys(b.chain[-1] for b in blocks if b.chain))
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{names[0]} to {names[-1]}"


def page_cell(plain: str, pages: list[int], group: list[dict]) -> str:
    """What a CRS row says for `plain` ("p.3"): itself, itself marked partial, or
    the section heading when the file has no pages. Display only."""
    if not plain or not settings.word_page_markers_enabled:
        return plain
    documents = {g.get("document_id") for g in group if g.get("document_id")}
    structure = _structure(next(iter(documents))) if len(documents) == 1 else None
    if structure is None or structure.pagination is None:
        return plain
    source = structure.pagination.source
    if source == PAGES_MARKERS:
        return plain
    if source == PAGES_PARTIAL:
        return f"{plain} ({PARTIAL})"
    quotes = [str(g.get("contractor_evidence_text") or "") for g in group]
    sections = list(
        dict.fromkeys(
            s for s in (_section_of(structure, p, quotes) for p in pages) if s
        )
    )
    return (
        f"Section {'; '.join(sections)} ({NO_PAGE})"
        if sections
        else NO_PAGE[0].upper() + NO_PAGE[1:]
    )


def at(finding: dict) -> str:
    """`page_cell` of one finding's own page."""
    page = finding.get("contractor_page")
    return page_cell(f"p.{page}", [page], [finding])


def at_pages(pages: list[int], group: list[dict]) -> str:
    """`page_cell` of a CRS row's pages."""
    from .crs_blank_fields import page_list

    return page_cell(f"p.{page_list(pages)}", pages, group)


def without_lead(section: str, document_id: str | None) -> str:
    """A Word file's page cell with this module's lead, or a page already named in
    words ("page 2", a locator's "page 2, 4.2 > para 1"), taken off, so it can be set
    once. Switch off, or not a Word file: the cell as it was."""
    if page_source(document_id) is None:
        return section
    return _PAGE_WORD_LEAD.sub("", _LEAD.sub("", section))


def no_image_words(default: str) -> str:
    """Why a Word page has no picture to show. It may well have a page number now,
    so "no printed pages" would be false with the switch on."""
    if settings.word_page_markers_enabled:
        return (
            "a Word file's page cannot be drawn here; open the file itself at that page"
        )
    return default


def read_proof(document_id: str | None) -> dict | None:
    """The tables and pictures in the file against what reached the reader, with
    those not read by place and reason. None when off or not a Word file. Counts
    and headings, never the content of a table or picture."""
    structure = _structure(document_id)
    if structure is None or structure.proof is None:
        return None
    page = structure.pagination
    proof = structure.proof
    return {
        "page_source": page.source,
        "saved_markers": page.saved_markers,
        "typed_breaks": page.typed_breaks,
        "word_saved_pages": page.word_pages,
        # None: no page is available; a part count is not a page count.
        "pages": None if page.source == PAGES_NONE else page.last_page,
        "tables_in_file": proof.tables_in_file,
        "tables_read": proof.tables_read,
        "pictures_in_file": proof.pictures_in_file,
        "pictures_read": proof.pictures_read,
        "furniture_pictures": proof.furniture_pictures,
        "media_files": proof.media_files,
        "not_read": [asdict(n) for n in proof.not_read],
    }


def coverage_part(document_id: str | None) -> dict:
    """What `page_ledger.coverage` adds for a Word file; nothing when off."""
    word_read = read_proof(document_id)
    return {} if word_read is None else {"word_read": word_read}


def place(item: dict) -> str:
    """Where a not-read table or picture sits: its page, else its heading."""
    if item.get("page"):
        return f"page {item['page']}"
    return f"under {item['heading']}" if item.get("heading") else "place not known"


def review_notes(findings: list[dict]) -> list[dict]:
    """The Review notes of the submittal behind these findings, with what was read of it
    (`reading_state`, its own switch). Nothing when both are off."""
    from . import reading_state

    notes: list[dict] = reading_state.review_notes(findings)
    if not settings.word_page_markers_enabled:
        return notes
    for document_id in sorted(
        {f.get("document_id") for f in findings if f.get("document_id")}
    ):
        proof = read_proof(document_id)
        if proof is None:
            continue
        if proof["page_source"] == PAGES_NONE:
            notes.append(
                {
                    "note": NOTE_NO_PAGES,
                    "standard": "",
                    "count": None,
                    "detail": (
                        "This Word file saved no page marks, so no page number is available: rows name the "
                        "section heading instead."
                    ),
                }
            )
        elif proof["page_source"] == PAGES_PARTIAL:
            notes.append(
                {
                    "note": NOTE_PARTIAL_PAGES,
                    "standard": "",
                    "count": None,
                    "detail": (
                        f"This Word file's page marks reach page {proof['pages']} and Word saved "
                        f"{proof['word_saved_pages'] if proof['word_saved_pages'] is not None else 'no'} pages"
                        " in all, so the page numbers on these rows may be off; check them in the file."
                    ),
                }
            )
        unread = proof["not_read"]
        if unread:
            where = "; ".join(
                f"{n['kind']} ({place(n)}): {n['reason']}" for n in unread
            )
            notes.append(
                {
                    "note": NOTE_NOT_READ,
                    "standard": "",
                    "count": len(unread),
                    "detail": (
                        f"Of {proof['tables_in_file']} tables, {proof['tables_read']} were read; of "
                        f"{proof['pictures_in_file']} pictures, {proof['pictures_read']} gave text. "
                        f"Not read: {where}."
                    ),
                }
            )
    return notes
