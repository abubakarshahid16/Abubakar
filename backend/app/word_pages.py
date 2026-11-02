"""What a reviewer may be told about a Word file's pages and contents
(WORD_PAGE_MARKERS_ENABLED; `docx_reader` reads the file).

One home for the words, so the CRS, the review notes, the ledger and the audit say
the same thing:

  * markers: "p.12", a real page.
  * partial: "p.12 (page marks partial)": Word saved more pages than its markers
    prove, so the number may be low. Never extrapolated.
  * none: the section heading, and plainly no page, in the cells this module
    writes.
  * stale: the file has page marks, but what is stored was read before the switch,
    so a stored number is a reading part, not a page. Said as no page until re-read.
  * unreadable: the database calls it a Word file and the file cannot be opened, so
    no stored number can be shown to be a page. Said the same way.

Comment text is built in dozens of places, and a model can write "page 12" itself, so
the guard is where text reaches a reader: `no_false_pages`, called on what the CRS and
the findings screen print. What is stored keeps its number: the quote check and the
row's page are built on it. A sentence about ANOTHER document says so
(`other_document_page`) and keeps its number.

Off, or not a Word file: `page_cell` returns what it was given and the rest return
nothing. Reads the file (cached); no model, no socket, nothing written.
"""

from __future__ import annotations

import functools
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
#: The stored numbers are reading parts of a file that has page marks.
PAGES_STALE = "stale"
#: `page_source`: what a stored number of these files is not: a page.
NO_REAL_PAGE = (PAGES_NONE, PAGES_STALE)
READ_BEFORE_MARKS = "read before its page marks were used, so re-read it to get pages"
NO_PAGE_SHORT = "no page number"
NO_PAGE_UNREADABLE = (
    "No page number: this Word file could not be opened to find its pages"
)
_OTHER_DOCUMENT = "of that document"

#: A lead `page_cell` writes, other than a plain "p.3".
_LEAD = re.compile(
    rf"^(?:p\.[\d, -]+ \({PARTIAL}\)|Section .*? \((?:{NO_PAGE}|{READ_BEFORE_MARKS})\)"
    rf"|\({READ_BEFORE_MARKS}\)|No page number: [^-]*?(?:marks|pages))(?: - |$)"
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


#: How much of a page's start is compared: enough to tell one cut from another.
_HEAD = 40


@functools.lru_cache(maxsize=_CACHE_MAX)
def _page_heads(path: str, _mtime_ns: int, _size: int) -> tuple[str, ...]:
    """The start of each page of the file, with no picture's text: a picture's reading
    can come later than the read, and must not look like another cut."""
    from .extract import normalise_text

    pages = docx_reader.read_structure(path, picture_readings={}).pages
    return tuple(_squash(normalise_text(text))[:_HEAD] for text in pages)


#: (document, its stored pages' count and size, the file's state) -> read as parts.
_PARTS: dict[tuple, bool] = {}


def _read_as_parts(document_id: str) -> bool:
    """The stored pages are not this file's own pages: read before the switch. Each
    page's start must be in the stored page of that number: another cut shows. Nothing
    stored yet: nothing to be wrong."""
    conn = connect()
    count, chars = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(char_count), 0) FROM pages WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not count:
        return False
    row = conn.execute(
        "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    path = stored_paths.local(row["stored_path"])
    state = Path(path).stat()
    key = (document_id, count, chars, path, state.st_mtime_ns, state.st_size)
    if key not in _PARTS:
        if len(_PARTS) >= _CACHE_MAX:
            _PARTS.pop(next(iter(_PARTS)))
        heads = _page_heads(path, state.st_mtime_ns, state.st_size)
        stored = conn.execute(
            "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        ).fetchall()
        _PARTS[key] = len(stored) != len(heads) or any(
            head not in _squash(r["text"])
            for r, head in zip(stored, heads, strict=True)
        )
    return _PARTS[key]


def page_source(document_id: str | None) -> str | None:
    """ "markers", "partial", "none" or "stale" for a Word file; None for anything else."""
    structure = _structure(document_id)
    if structure is None or structure.pagination is None:
        return None
    source = structure.pagination.source
    if source != PAGES_NONE and _read_as_parts(document_id):
        return PAGES_STALE
    return source


def _is_flow(document_id: str | None) -> bool:
    if not document_id:
        return False
    row = (
        connect()
        .execute("SELECT pagination FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    return row is not None and row["pagination"] == "flow"


def numbers_are_not_pages(document_id: str | None) -> bool:
    """A stored page number of this document must never be printed as a page: a Word
    file with no marks, one read before them, or one whose file cannot be opened."""
    if not settings.word_page_markers_enabled or not document_id:
        return False
    return page_source(document_id) in NO_REAL_PAGE or (
        _structure(document_id) is None and _is_flow(document_id)
    )


def unit(document_id: str | None) -> str:
    """What a progress line calls this file's numbered units: "part" only when a
    Word file has no pages to name. Switch off or a PDF: "page", as it always said."""
    return "part" if page_source(document_id) in NO_REAL_PAGE else "page"


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


def _section_by_quote(structure: Structure, quotes: list[str]) -> str:
    """ "Section X " when a quote sits under heading X; "" when nothing places it."""
    wanted = [_squash(q) for q in quotes if _squash(q)]
    for block in structure.blocks:
        text = _squash(" ".join(docx_reader.block_lines(block)))
        if block.chain and any(q in text for q in wanted):
            return f"Section {block.chain[-1]} "
    return ""


def page_cell(plain: str, pages: list[int], group: list[dict]) -> str:
    """What a CRS row says for `plain` ("p.3"): itself, itself marked partial, or
    the section heading when the file has no pages. Display only."""
    if not plain or not settings.word_page_markers_enabled:
        return plain
    documents = {g.get("document_id") for g in group if g.get("document_id")}
    document = next(iter(documents)) if len(documents) == 1 else None
    if numbers_are_not_pages(document) and _structure(document) is None:
        return NO_PAGE_UNREADABLE
    source = page_source(document)
    if source is None or source == PAGES_MARKERS:
        return plain
    if source == PAGES_PARTIAL:
        return f"{plain} ({PARTIAL})"
    structure = _structure(document)
    quotes = [str(g.get("contractor_evidence_text") or "") for g in group]
    if source == PAGES_STALE:
        # The numbers are from another cut: only a quote can place the row.
        return f"{_section_by_quote(structure, quotes)}({READ_BEFORE_MARKS})"
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


#: Words that hold a document's own text: a stored quote is the document's, as printed.
_QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|(?<!\w)'[^']*'(?!\w)")
_NUMBERS = r"\d+(?:\s*(?:-|\u2013|to)\s*\d+)?(?:\s*(?:,|and|&)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?)*"
#: "page 12", "pages 1-3, 7", "p.12", "pp. 3-4", "pg 12", with what leads into it.
_PAGE_WORDS = re.compile(
    r"(?P<clause>\b(?:cl\.|clause)\s+\S+\s+\(?)?"
    r"(?P<lead>\b(?:on|at|in)\s+)?"
    rf"\b(?P<word>pages?\s+|pp?\.\s*|pgs?\.?\s*)(?P<numbers>{_NUMBERS})"
    # "of 25" is the count of parts; "of SAES-L-100" names another document.
    rf"(?P<of>\s+of\s+\d+\b)?(?P<other>\s+{_OTHER_DOCUMENT}|\s+of\s+[A-Z][\w./]*[-\d][\w./-]*)?",
    re.IGNORECASE,
)


def other_document_page(page) -> str:
    """How a sentence about a Word file names a page of ANOTHER document, so its number
    is not taken for one of that file's. Off: "page N", as it always said."""
    if settings.word_page_markers_enabled:
        return f"page {page} {_OTHER_DOCUMENT}"
    return f"page {page}"


def _no_page_words(match: re.Match, structure: Structure | None) -> str:
    if match["clause"] or match["other"]:
        return match[0]  # a clause's page or a named document's: not this file's
    lead = "in " if match["lead"] else ""
    numbers = match["numbers"]
    if numbers.isdigit() and structure is not None:
        section = _section_of(structure, int(numbers), [])
        if section:
            return f'{lead}section "{section}"'
    many = match["word"].lower().startswith("pp") or not numbers.isdigit()
    return f"{lead}{'parts' if many else 'a part'} with {NO_PAGE_SHORT}"


def no_false_pages(text, document_id: str | None):
    """`text` as a reader may see it: a page number of a Word file whose numbers are
    not pages becomes the section it sits under, or plainly no page. A quoted passage
    is the document's own words and stays. Anything else, and off: `text` itself."""
    if not text or not isinstance(text, str) or not numbers_are_not_pages(document_id):
        return text
    # The numbers of a stale file are from another cut, so they name no section.
    structure = (
        _structure(document_id) if page_source(document_id) == PAGES_NONE else None
    )
    out, at = [], 0
    for quoted in _QUOTED.finditer(text):
        out.append(
            _PAGE_WORDS.sub(
                lambda m: _no_page_words(m, structure), text[at : quoted.start()]
            )
        )
        out.append(quoted[0])
        at = quoted.end()
    out.append(_PAGE_WORDS.sub(lambda m: _no_page_words(m, structure), text[at:]))
    return "".join(out)


#: What a findings screen shows of a stored finding. Engineer's own words are not here.
_FINDING_TEXT = ("finding", "ai_rationale", "required_action")


def finding_for_reader(finding: dict) -> dict:
    """A copy of a stored finding, its machine text safe to show. Off: the finding."""
    document_id = finding.get("document_id")
    if not numbers_are_not_pages(document_id):
        return finding
    shown = {**finding, "contractor_page": None}
    for key in _FINDING_TEXT:
        shown[key] = no_false_pages(finding.get(key), document_id)
    return shown


#: The CRS cells built from machine text. `engineer_worded` rows are the engineer's.
_CRS_TEXT = ("comment", "ai_review_comment", "reasoning", "page_section")


def crs_rows_for_reader(rows: list[dict], document_id: str | None) -> list[dict]:
    """Every CRS row of this document, its machine text safe to print, as the last step
    before it is drawn. Off or a document with real pages: the rows as they came."""
    if not numbers_are_not_pages(document_id):
        return rows
    for row in rows:
        keys = _CRS_TEXT[-1:] if row.get("engineer_worded") else _CRS_TEXT
        for key in keys:
            if key in row:
                row[key] = no_false_pages(row[key], document_id)
    return rows


def notes_for_reader(notes: list[dict], document_id: str | None) -> list[dict]:
    """The CRS review notes of this document, safe to print."""
    if not numbers_are_not_pages(document_id):
        return notes
    return [
        {**note, "detail": no_false_pages(note.get("detail"), document_id)}
        for note in notes
    ]


#: The sheet's sentences beside its rows, each built from machine text.
_META_TEXT = ("run_status_note", "incomplete_notice", "recommended_code_reason")


def crs_for_reader(rows: list[dict], meta: dict) -> tuple[list[dict], dict]:
    """The CRS as it is drawn: every comment, cell and note of a Word file whose numbers
    are not pages says no number as a page, whichever module or model wrote the words.
    The LAST step, after numbering and carry-over, which compare the stored words. Off
    or a document with real pages: as they came."""
    if not settings.word_page_markers_enabled:
        return rows, meta
    run = (
        connect()
        .execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?",
            (meta.get("review_run_id"),),
        )
        .fetchone()
    )
    document_id = run["submittal_document_id"] if run else None
    if not numbers_are_not_pages(document_id):
        return rows, meta
    shown = {
        **meta,
        "review_notes": notes_for_reader(meta.get("review_notes") or [], document_id),
        "unchecked_parts": [
            no_false_pages(line, document_id)
            for line in meta.get("unchecked_parts") or []
        ],
    }
    for key in _META_TEXT:
        if key in shown:
            shown[key] = no_false_pages(shown[key], document_id)
    return crs_rows_for_reader(rows, document_id), shown


def for_screen(findings: list[dict]) -> list[dict]:
    """The stored findings as the findings screen shows them."""
    return [finding_for_reader(f) for f in findings]


def text_only_answer(document_id: str, status: str) -> str | None:
    """What a full-document answer must say about a held Word file whose text is all
    searchable and whose only gap is pictures with no answer: the answer goes ahead on
    its text, and says so. None for anything else, and with the switches off."""
    from . import reading_state, states

    if status != states.PARTIALLY_SEARCHABLE or not reading_state._any_switch():
        return None
    saved = reading_state.stored(document_id)
    if not saved or not saved["unaccounted"] or not saved["unaccounted_list"]:
        return None
    if any(i.get("kind") != "picture" for i in saved["unaccounted_list"]):
        return None
    row = (
        connect()
        .execute("SELECT stored_path FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    path = row["stored_path"] if row else None
    if not path or office_kind(path) != KIND_DOCX:
        return None
    return saved["line"]


def not_answerable(documents: list[dict]) -> list[dict]:
    """The documents a full-document answer must stop for. A held Word file that can
    be answered on its text is marked, and goes ahead."""
    from . import states

    out = []
    for doc in documents:
        if doc["status"] == states.READY:
            continue
        line = text_only_answer(doc["document_id"], doc["status"])
        if line:
            doc["read_in_part"] = line
        else:
            out.append(doc)
    return out


def text_only_notice(documents: list[dict]) -> str:
    """What an answer says about each document it could use only the text of."""
    return "".join(
        f" {d['filename']} is not fully accounted for, so this covers its text only. "
        f"{d['read_in_part']}."
        for d in documents
        if d.get("read_in_part")
    )


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
    source = page_source(document_id)
    return {
        "page_source": source,
        "saved_markers": page.saved_markers,
        "typed_breaks": page.typed_breaks,
        "word_saved_pages": page.word_pages,
        # None: no page is available; a part count is not a page count.
        "pages": None if source in NO_REAL_PAGE else page.last_page,
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
        if proof["page_source"] == PAGES_STALE:
            notes.append(
                {
                    "note": NOTE_NO_PAGES,
                    "standard": "",
                    "count": None,
                    "detail": (
                        f"This Word file was {READ_BEFORE_MARKS}: its rows name a section "
                        "where a quote places one."
                    ),
                }
            )
        elif proof["page_source"] == PAGES_NONE:
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
