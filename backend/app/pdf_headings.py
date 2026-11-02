"""Section headings of a PDF read from how the line is SET, not only from its words.

#1476 / #1522 (owner, 1 Nov): the Word copy of a procedure gives section headings
from its paragraph styles, the PDF copy of the same procedure gave none - its
headings are "1. SCOPE" (a bare integer with a dot, which the text
rules refuse because "1. Close the valve." has the same shape) and unnumbered
bold lines - so every playbook element on the PDF was "could not be checked".

A line is a heading here only when ALL of these hold; every signal is true of any
document, none names a layout (CLAUDE.md rule 13):

  * it is SET apart: a font clearly larger than the body text (the character-
    weighted mode of the document's sizes), or bold / heavier where the body is
    not - or, in body type, it opens with a DOTTED section number (1.2, 4.5.1.3,
    A.1);
  * it is a short line: it stops well before the column's right edge (a line that
    fills the column is a wrapped sentence);
  * it reads as a title: 1-12 words, at most 90 characters, a capital first
    letter, no sentence or list ending (. ; , :), mostly letters, not a figure or
    table caption or a date, not a number with a unit or a value ("4.2 MPa"), not a
    requirement or a limit ("Bolts Must Be Torqued", "Maximum 10 Bar");
  * it stands alone: no other line shares its height on the page (a table row or a
    form field does), and it is not a running header or footer (the same words in
    the top or bottom band of 3 or more pages);
  * body text follows it: the next line is not another heading-like line, unless
    this one is numbered ("4. GENERAL" then "4.1 Scope"); a line right under a
    heading-like line is the second line of a wrapped title unless it is numbered;
    a body-type numbered line is not followed by text resuming in lower case (the
    first line of a numbered requirement).

A heading never removes its words: the chunker carries the line into the text of the
next block, so a wrong heading costs a label, never a requirement.
A single number in body type ("1. Close the valve", a list item) is never a heading.
Switch `pdf_heading_detection_enabled`, OFF by default: nothing here runs and the
chunk signature is unchanged. ON: `chunker.segment_document` treats these lines as
headings where its text rules found none, and the switch is part of the chunk
signature so every stored PDF is stale until re-chunked.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from . import claims, numparse, pdf_guard
from .config import settings
from .quality import normalise_text

log = logging.getLogger(__name__)

#: Part of the chunk signature while the switch is on; bump when detection changes.
SIGNATURE_TAG = "pdf-headings:1"
#: A size this much above the body text is set apart on its own.
SIZE_RATIO = 1.15
#: A line is bold when this share of its letters is bold.
BOLD_SHARE = 0.9
MAX_WORDS = 12
MAX_CHARS = 90
#: The top and bottom share of the page where running headers and footers sit.
EDGE_BAND = 0.15
RUNNING_PAGES = 3
#: A heading is a short line: it ends before this share of the column's width.
SHORT_LINE = 0.8
_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demibold|extrabold", re.I)
#: A section label at the start of a line (1, 1.2, A.1, Appendix B): where a line sits,
#: never a value read from the document. Values go through `app.numparse`.
_SECTION_NO = re.compile(
    r"^(?:(?:Appendix|APPENDIX|Annex|ANNEX|Section|SECTION|Chapter|CHAPTER|Part|PART)"
    r"\s+(?:[A-Z]|[IVX]+|\d{1,2})\b"
    r"|[A-Z]\.\d{1,2}(?:\.\d{1,2})*\b"
    r"|\d{1,2}(?:\.\d{1,2})*\.?(?=\s))"
)
#: A dotted section number: 1.2, 4.5.1.3, A.1 - never a lone list number.
_DOTTED = re.compile(r"^(?:[A-Z]\.\d{1,2}(?:\.\d{1,2})*|\d{1,2}(?:\.\d{1,2})+)\.?\s")
_REQUIREMENT_WORD = re.compile(
    r"\b(?:must|shall|should|will|is to|are to|do not|not exceed|not to exceed)\b",
    re.I,
)
_ENDINGS = (".", ";", ",", ":")
#: A figure or table caption names a picture or a table, not a section.
_CAPTION = re.compile(
    r"^(?:figure|fig\.?|table|chart|exhibit|plate)\s*[A-Z]?[\d.-]*\d\b", re.I
)
#: A date ("7 January 2020") is a revision stamp, not a section.
_DATE = re.compile(r"^\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}$")


@dataclass
class Line:
    text: str
    size: float
    bold: bool
    top: float
    bottom: float
    page_height: float
    styled: bool = False
    left: float = 0.0
    right: float = 0.0


def _norm(text: str) -> str:
    return " ".join(normalise_text(text).split())


def _is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & 16) or bool(
        _BOLD_NAME.search(span.get("font", ""))
    )


def _page_lines(pdf, n: int) -> tuple[float, list[tuple[str, list[dict], tuple]]]:
    """(page height, its lines) - one short PyMuPDF block under the process lock (order 252)."""
    with pdf_guard.held():
        page = pdf[n - 1]
        height, blocks = float(page.rect.height) or 1.0, page.get_text("dict")["blocks"]
    out = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            text = _norm("".join(s["text"] for s in line["spans"]))
            if spans and text:
                out.append((text, spans, tuple(line["bbox"])))
    return height, out


def _body_style(raw: dict) -> tuple[float, bool]:
    """(body size, body is bold): the character-weighted mode of the sizes."""
    sizes: Counter[float] = Counter()
    for lines in raw.values():
        for _, spans, _ in lines:
            for s in spans:
                sizes[round(s["size"], 1)] += len(s["text"].strip())
    body = sizes.most_common(1)[0][0] if sizes else 0.0
    bold = every = 0
    for lines in raw.values():
        for _, spans, _ in lines:
            for s in spans:
                if abs(round(s["size"], 1) - body) < 0.05:
                    every += len(s["text"].strip())
                    bold += len(s["text"].strip()) if _is_bold(s) else 0
    return body, every > 0 and bold / every > 0.5


def read_lines(
    pdf, skip_pages: set[int] | frozenset[int] = frozenset()
) -> dict[int, list[Line]]:
    """{page number: its text lines, in reading order, with size and weight}."""
    with pdf_guard.held():
        count = pdf.page_count
    read = {n: _page_lines(pdf, n) for n in range(1, count + 1) if n not in skip_pages}
    raw = {n: lines for n, (_, lines) in read.items()}
    body, body_bold = _body_style(raw)
    out: dict[int, list[Line]] = {}
    for n, lines in raw.items():
        height = read[n][0]
        page: list[Line] = []
        for text, spans, box in lines:
            letters = sum(len(s["text"].strip()) for s in spans) or 1
            bold = (
                sum(len(s["text"].strip()) for s in spans if _is_bold(s)) / letters
                >= BOLD_SHARE
            )
            size = max(s["size"] for s in spans)
            styled = bool(body) and (
                size >= body * SIZE_RATIO or (bold and not body_bold)
            )
            page.append(
                Line(text, size, bold, box[1], box[3], height, styled, box[0], box[2])
            )
        out[n] = page
    return out


def states_a_value(text: str) -> bool:
    """A number followed by a value, or by a unit that opens no title ("4.2 MPa",
    "4.2 MPa at Inlet"; "4.2 Bar Screens" is a title that starts with a unit word)."""
    label = _SECTION_NO.match(text)
    if not label or label.group().split()[0].isalpha():
        return False
    rest = text[label.end() :].split()
    if not rest:
        return False
    if rest[0][0].isdigit() or rest[0][0] in "+-<>=~\u00b1":
        return True
    titled = len(rest) > 1 and rest[1][0].isupper()
    return claims.is_unit(rest[0].strip(",;()")) and not titled


def states_a_requirement(text: str) -> bool:
    """A requirement word, or a number with a unit past the section label: a limit.
    A bare integer is no label here: "10 Bar Maximum" is a value, "4.2 Bar Screens" is not."""
    if _REQUIREMENT_WORD.search(text):
        return True
    label = _SECTION_NO.match(text)
    bare = not label or label.group().isdigit()
    words = (text if bare else text[label.end() :]).split()
    return any(
        numparse.as_number(word) is not None and claims.is_unit(after.strip(",;()"))
        for word, after in pairwise(words)
    )


def numbered(text: str) -> bool:
    return bool(_SECTION_NO.match(text)) and not states_a_value(text)


def _reads_as_title(text: str) -> bool:
    words = text.split()
    if (
        not 1 <= len(words) <= MAX_WORDS
        or len(text) > MAX_CHARS
        or text.endswith(_ENDINGS)
    ):
        return False
    if _CAPTION.match(text) or _DATE.match(text) or text.count("(") != text.count(")"):
        return False  # a caption, a date, or a piece of a title wrapped over lines
    if states_a_value(text) or states_a_requirement(text):
        return False
    title = _SECTION_NO.sub("", text, count=1).strip(" .-\u2013\u2014")
    if not title and _SECTION_NO.match(text):
        return text.split()[0].isalpha()  # "Appendix B" alone; never "A.1" alone
    first = next((ch for ch in title if ch.isalpha()), "")
    if not first or not first.isupper():
        return False
    alnum = [ch for ch in title if ch.isalnum()]
    letters = sum(ch.isalpha() for ch in alnum)
    return letters >= 0.6 * max(1, len(alnum))


def _key(text: str) -> str:
    return re.sub(r"\d+", "#", text.casefold())


def _running(pages: dict[int, list[Line]]) -> set[str]:
    """Lines in the top or bottom band of RUNNING_PAGES or more pages."""
    seen: Counter[str] = Counter()
    for lines in pages.values():
        edge = {
            _key(ln.text)
            for ln in lines
            if ln.top < ln.page_height * EDGE_BAND
            or ln.bottom > ln.page_height * (1 - EDGE_BAND)
        }
        seen.update(edge)
    return {k for k, n in seen.items() if n >= RUNNING_PAGES}


def _shares_height(line: Line, lines: list[Line]) -> bool:
    """Another line beside it (same height band): a table row or form field."""
    tall = max(line.bottom - line.top, 1.0)
    for other in lines:
        if other is line:
            continue
        overlap = min(line.bottom, other.bottom) - max(line.top, other.top)
        if overlap > 0.5 * tall:
            return True
    return False


def _short(line: Line, lines: list[Line]) -> bool:
    """Does the line stop well before the column's right edge (a title, not a wrapped sentence)?"""
    left = min((ln.left for ln in lines), default=0.0)
    edge = max((ln.right for ln in lines if not ln.styled), default=0.0)
    return edge > left and line.right - left < SHORT_LINE * (edge - left)


def _candidate(line: Line, lines: list[Line]) -> bool:
    """Heading-like on its own: set apart (or a short dotted-number line), a title, alone."""
    if (
        not _reads_as_title(line.text)
        or _shares_height(line, lines)
        or not _short(line, lines)
    ):
        return False
    return line.styled or bool(_DOTTED.match(line.text))


def _resumes_lower(line: Line | None) -> bool:
    first = next((ch for ch in line.text if ch.isalpha()), "") if line else ""
    return first.islower()


def _level(text: str) -> int | None:
    """The depth of a line's section number (1. = 0, 1.2 = 1); None without one."""
    label = _SECTION_NO.match(text)
    if not label or label.group().split()[0].isalpha():
        return None
    return label.group().rstrip(".").count(".")


def _in_a_list(i: int, lines: list[Line], like: list[bool]) -> bool:
    """Numbered lines of one level right next to each other are a list, not headings."""
    level = _level(lines[i].text)
    if level is None:
        return False
    return any(
        0 <= j < len(lines) and like[j] and _level(lines[j].text) == level
        for j in (i - 1, i + 1)
    )


def detect(pages: dict[int, list[Line]]) -> dict[int, list[str]]:
    """{page number: the heading lines on it, as normalised text}."""
    running = _running(pages)
    found: dict[int, list[str]] = {}
    for n, lines in pages.items():
        lines = [ln for ln in lines if _key(ln.text) not in running]
        like = [_candidate(ln, lines) for ln in lines]
        heads = []
        for i, ln in enumerate(lines):
            if not like[i] or i + 1 >= len(lines):
                continue
            if like[i + 1] and not numbered(ln.text):
                continue  # a title wrapped over lines, or a run of styled lines
            if i and (like[i - 1] or lines[i - 1].styled) and not numbered(ln.text):
                continue  # the second line of a wrapped title
            if not ln.styled and _resumes_lower(lines[i + 1]):
                continue  # the first line of a numbered requirement
            if _in_a_list(i, lines, like):
                continue
            heads.append(ln.text)
        if heads:
            found[n] = heads
    return found


def _section_number(text: str) -> str | None:
    """ "4.1" of "4.1 Scope", "1" of "1. Scope"; None for "Appendix B" or no number."""
    label = _SECTION_NO.match(text)
    if not label or label.group().split()[0].isalpha():
        return None
    return label.group().rstrip(".")


def _rising(bold: list[tuple[str, str]], numbers: list[str]) -> set[str]:
    """Which (line text, number) in document order fit the document's numbering: the
    chunker's own test (`plausible_heading_numbers`, and a bare number must rise AT THIS
    POSITION, as in `segment_document`). A bare number also needs a sibling or a child: a
    lone "1." is a caption or a list as easily as a section."""
    from . import chunker

    allowed = chunker.plausible_heading_numbers(numbers)
    kept: dict[str, str] = {}
    last = 0
    for text, number in bold:
        if number not in allowed:
            continue
        if number.isdigit():
            if int(number) <= last:
                continue
            last = int(number)
        kept[text] = number
    bare = [n for n in kept.values() if n.isdigit()]
    children = {n.split(".")[0] for n in numbers if "." in n}
    return {
        text
        for text, n in kept.items()
        if not n.isdigit() or len(bare) > 1 or n in children
    }


def numbered_bold(pages: dict[int, list[Line]]) -> frozenset[str]:
    """Headings bold as a whole line whose section number fits the document's numbering:
    independent signals, so the owner counts them as found (2 Nov, #1522). Large but not
    bold, a bold number before a body sentence, a restarted number and a lone row number
    are not. "Appendix B" and its like carry their word instead of a rising number."""
    heads = detect(pages)
    labelled, bold, numbers = set(), [], []
    for n in sorted(pages):
        for ln in pages[n]:
            if not numbered(ln.text):
                continue
            number = _section_number(ln.text)
            is_head = ln.bold and ln.styled and ln.text in heads.get(n, ())
            if is_head and number is None:
                labelled.add(ln.text)
            elif is_head:
                bold.append((ln.text, number))
                numbers.append(number)
            elif number and "." in number and _reads_as_title(ln.text):
                numbers.append(number)  # a body-type sub-heading vouches for its parent
    return frozenset(labelled | _rising(bold, numbers))


def enabled() -> bool:
    return bool(settings.pdf_heading_detection_enabled)


def signature_key(sha: str, pagination: str | None) -> str:
    """The document part of the chunk signature: its sha, plus a tag for a PDF while
    the switch is on, so switching on marks every stored PDF stale (a Word file is not)."""
    return sha + ":" + SIGNATURE_TAG if enabled() and pagination != "flow" else sha


def font_only_headings(document_id: str) -> frozenset[str] | None:
    """The guesses among a PDF's font headings; see `font_headings`."""
    both = font_headings(document_id)
    return None if both is None else both[0]


def font_headings(document_id: str) -> tuple[frozenset[str], frozenset[str]] | None:
    """The stored section titles of a PDF that only the font says are headings: what is
    left once the text rules are replayed on its pages and the numbered bold headings are
    taken out. Returns (guesses, numbered bold). A guess is rule 4's guess; every font heading
    is one when the file cannot be read. None with the switch off or for a Word file."""
    if not enabled():
        return None
    from . import chunker
    from .db import connect

    conn = connect()
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None or dict(row).get("pagination") == "flow":
        return None
    pages, raw_tables, page_rows = chunker._load_pages(conn, document_id)
    if not pages:
        return frozenset(), frozenset()
    recognised = {r["page_no"] for r in page_rows if r["recognised"]}
    lines = _font_pages(row["stored_path"], recognised)
    confirmed = numbered_bold(lines) if lines else frozenset()
    kinds = chunker.classify_document_pages(pages, row["page_count"] or len(pages))
    running = chunker.detect_running_lines(pages)
    masked = chunker.mask_tables(pages, chunker._decode_tables(raw_tables), running)
    blocks, _ = chunker.segment_document(masked, running, kinds)
    stored = conn.execute(
        "SELECT DISTINCT section FROM chunks WHERE document_id = ? AND section IS NOT NULL",
        (document_id,),
    ).fetchall()
    every = frozenset({r[0] for r in stored} - {b.section for b in blocks})
    return every - confirmed, every & confirmed


def _font_pages(
    stored_path: str | None, skip_pages: set[int]
) -> dict[int, list[Line]] | None:
    """A stored PDF's lines with size and weight; None when it cannot be opened.
    Recognised (OCR) pages carry no font and are skipped."""
    from . import stored_paths

    path = stored_paths.local(stored_path)
    if not path or Path(path).suffix.lower() != ".pdf" or not Path(path).is_file():
        return None
    import pymupdf

    try:
        with pdf_guard.held():
            pdf = pymupdf.open(path)
        try:
            return read_lines(pdf, skip_pages)
        finally:
            with pdf_guard.held():
                pdf.close()
    except (RuntimeError, ValueError, OSError) as exc:
        log.warning(
            "pdf_headings: font read failed, text rules only (%s)", type(exc).__name__
        )
        return None


def for_document(
    stored_path: str | None, skip_pages: set[int]
) -> dict[int, set[str]] | None:
    """The styled heading lines of a stored PDF, by page; None when the switch is
    off or the file cannot be opened (the text rules then decide alone, as before)."""
    if not enabled() or not stored_path:
        return None
    lines = _font_pages(stored_path, skip_pages)
    if lines is None:
        return None
    return {n: set(heads) for n, heads in detect(lines).items()}
