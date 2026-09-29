"""Step 3 - structure-aware chunking.

Token counts come from the real e5-small tokenizer, never a word-count
approximation: e5-small silently truncates above 512 tokens, so an
over-length chunk would lose its tail without any visible error.

The document is flattened into a stream of blocks that carry their page
number, so a chunk may span pages and records a page RANGE. Running headers
and footers are detected across the document and removed before chunking,
because a running title repeated in every chunk poisons every search result.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from tokenizers import Tokenizer

from .config import settings
from .db import connect
from .rates import Timer, rate
from . import states
from . import keyword
from . import orphan_guard
from .quality import MIN_CLAUSE_WORDS, assess, longest_clause
from . import tables as tables_mod

# ---------------------------------------------------------------- tokenizer


@lru_cache(maxsize=1)
def get_tokenizer() -> Tokenizer:
    path = settings.embed_model_dir / "tokenizer.json"
    if not path.exists():
        raise FileNotFoundError(f"e5-small tokenizer not staged at {path}")
    return Tokenizer.from_file(str(path))


def count_tokens(text: str) -> int:
    return len(get_tokenizer().encode(text, add_special_tokens=False).ids)


# ------------------------------------------------- running headers/footers

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def normalise_line(line: str) -> str:
    """Collapse whitespace and mask digits, so 'Page 12' and 'Page 13' match."""
    return _WS.sub(" ", _DIGITS.sub("#", line)).strip().lower()


#: Markers carried INSIDE the running-line set (strings no real line can
#: normalise to, because extraction replaces control characters). The set is
#: also read by `classification.title_block_lines`, which only ever asks
#: `norm in running`, so extra members are invisible to it.
_PAGENO_MARK = "\x00pageno:"
_EXACT_MARK = "\x00exact:"
_HAS_LETTER = re.compile(r"[^\W\d_]")
_ONE_NUMBER = re.compile(r"^\D*(\d{1,4})\D*$")


def _exact_line(line: str) -> str:
    return _WS.sub(" ", line).strip().lower()


def detect_running_lines(pages: list[tuple[int, str]]) -> set[str]:
    """Normalised lines that repeat at the top or bottom of most pages.

    Only the first and last few lines of each page are considered, so a
    sentence that legitimately recurs in body text is never removed.

    The window is twice the strip window: a PDF often emits its whole header
    AND footer before the body ("Document Responsibility" / "SAES-H-101V" /
    "Issue Date" / title / "Company General Use" / "Page 3 of 9" is six lines
    at the TOP of the extracted text), and a footer counted only when it sits
    in the first five lines was never detected. Stripping still happens only
    inside the edge window or in a run of furniture contiguous with the page
    edge (see strip_running_lines), so the wider count cannot reach the body.

    Two kinds of marker are added (see _PAGENO_MARK): the page-number offsets
    the document actually uses, so a bare number is stripped only when it IS
    the page number, and the exact (unmasked) lines that repeat, so a heading
    that merely shares a digit-masked shape is not taken for furniture.
    """
    if len(pages) < 5:
        return set()
    n = settings.running_line_scan_lines * 2
    counts: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    offsets: Counter[int] = Counter()
    for page_no, text in pages:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        edge = lines[:n] + lines[-n:]
        for norm in {normalise_line(line) for line in edge if line.strip()}:
            if norm and len(norm) <= 120:
                counts[norm] += 1
        for form in {_exact_line(line) for line in edge if line.strip()}:
            if form and len(form) <= 120:
                exact[form] += 1
        page_offsets = set()
        for line in edge:
            m = _ONE_NUMBER.match(line.strip())
            if m and not _HAS_LETTER.search(line):
                page_offsets.add(int(m.group(1)) - page_no)
        for off in page_offsets:
            offsets[off] += 1
    # A running head repeats within a CHAPTER, not across the whole book, so a
    # "most pages" threshold misses it entirely. Use an absolute floor instead:
    # appearing at the edge of many pages is already strong evidence.
    floor = max(5, int(len(pages) * settings.running_line_threshold))
    found = {line for line, c in counts.items() if c >= floor}
    found |= {_EXACT_MARK + form for form, c in exact.items() if c >= floor}
    found |= {f"{_PAGENO_MARK}{off}" for off, c in offsets.items() if c >= floor}
    return found


def _is_running(line: str, running: set[str], page_no: int | None) -> bool:
    """Whether one line is page furniture under the document's running set.

    A line with NO LETTERS normalises to '#' - which is a page number, and
    also every numeric table cell in the document (audit F2: a table's last
    row, CS-23's "69 / 222 / 200", vanished from the foot of page 9, and
    nothing recorded it). Such a line is furniture only when its number is
    this page's number under an offset the document repeatedly uses. Without
    a page number there is no evidence, and the line is kept.
    """
    stripped = line.strip()
    if not stripped:
        return False
    norm = normalise_line(stripped)
    if norm not in running:
        return False
    if not _HAS_LETTER.search(stripped):
        m = _ONE_NUMBER.match(stripped)
        return bool(m and page_no is not None
                    and f"{_PAGENO_MARK}{int(m.group(1)) - page_no}" in running)
    # Matched only after masking its digits. "Page 3 of 9" is furniture that
    # way; "A.4 Coating system no. 4" at the top of four annex pages is a
    # HEADING that shares a shape with its siblings. A heading is kept unless
    # its exact text repeats.
    if (_DIGITS.search(stripped)
            and (_EXACT_MARK + _exact_line(stripped)) not in running
            and (looks_like_heading(stripped) or _CLAUSE_NUMBER_LEAD.match(stripped))):
        return False
    return True


def strip_running_lines(text: str, running: set[str],
                        page_no: int | None = None) -> tuple[str, int]:
    """Remove running lines from the page edges only. Returns (text, removed).

    The edge is the first/last `running_line_scan_lines` lines, EXTENDED by
    any run of furniture contiguous with the page edge: a six-line header
    block is removed whole, while a recurring line in the body is never
    reached because a body line breaks the run.
    """
    if not running:
        return text, 0
    lines = text.splitlines()
    # On a short page every line would fall inside the edge window, which would
    # strip body text. Shrink the window so the middle of a page is always safe.
    n = settings.running_line_scan_lines
    # The contiguous-furniture extension is for FULL pages only; a short page
    # keeps the one-line window, where everything is near an edge. A masked
    # table counts as the lines it stands for: a page that is one long table
    # is not a short page.
    size = sum(len((_sentinel_table(line) or {}).get("raw") or [line]) for line in lines)
    limit = 3 * n
    if size < 2 * n + 2:
        n = 1
        limit = 1
    top = 0
    while top < min(len(lines), limit) and (
            not lines[top].strip() or _is_running(lines[top], running, page_no)):
        top += 1
    bottom = 0
    while bottom < min(len(lines) - top, limit) and (
            not lines[-1 - bottom].strip()
            or _is_running(lines[-1 - bottom], running, page_no)):
        bottom += 1
    keep: list[str] = []
    removed = 0
    last = len(lines) - 1
    for i, line in enumerate(lines):
        at_edge = i < max(n, top) or i > last - max(n, bottom)
        if at_edge and line.strip() and _is_running(line, running, page_no):
            # A bare number normalises to "#", which is a page number in a
            # book and a CLAUSE NUMBER in a specification - and in a spec the
            # number sits on its own line with the title beneath it. Both
            # forms recur across pages, so both get flagged as running lines,
            # and stripping the clause numbers removes every heading in the
            # document. Protected only when this line and the next actually
            # form a heading, which is narrow enough to leave real page
            # numbers being stripped as before.
            if _CLAUSE_NUMBER_ONLY.match(line) and _split_line_heading(
                [ln.strip() for ln in lines], i
            )[0]:
                keep.append(line)
                continue
            # B6B E4: the same for a numbered paragraph's clause number
            # ('6.2.1' above its requirement) - dotted, so never a page number.
            if _numbered_paragraph([ln.strip() for ln in lines], i):
                keep.append(line)
                continue
            removed += 1
            continue
        keep.append(line)
    return "\n".join(keep), removed


# ------------------------------------------------------------- structure

# 5.1 Introduction / 2.2.3 Location Tracking / CHAPTER 9
_HEADING = re.compile(
    r"^\s*(?:(?:CHAPTER|Chapter|SECTION|Section)\s+)?"
    r"((?:[A-Z]\.)?\d+(?:\.\d+){0,3})\s+([A-Z][^\n]{2,70})\s*$"
)
_CHAPTER_PREFIX = re.compile(r"^\s*(?:CHAPTER|Chapter|SECTION|Section)\s+")
#: The obligation word of a specification. "shall" only: "must" and "should"
#: head real sections in the textbooks this chunker also reads.
_OBLIGATION = re.compile(r"\bshall\b", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\([^()]*\)")
_ALLCAPS_HEADING = re.compile(r"^\s*([A-Z][A-Z \-&/]{6,60})\s*$")
_TABLE_CAPTION = re.compile(r"^\s*(?:TABLE|Table|FIGURE|Figure)\s+\d+")
#: Stands in the page text for a ruled table read by geometry (see
#: mask_tables). \x02 cannot occur in extracted text - normalise_text turns
#: control characters into spaces - and, unlike \x1e, it is not a line
#: boundary for str.splitlines. The table itself follows as JSON on the same
#: line, so every pass that walks the lines can decode it without a registry.
_TABLE_SENTINEL = "\x02TABLE:"
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
_TRAILING_PAGE_NO = re.compile(r"\s\d{1,4}$")
#: A trailing number that belongs to the TITLE rather than being a page
#: reference: "A.4 Coating system no. 4", "System 3B", "Type 2".
_DESIGNATOR_TAIL = re.compile(
    r"(?i)\b(?:no\.?|number|system|type|class|grade|level|group)\s+\d+[A-Za-z]?\s*$"
)
_NUMERIC_TOKEN = re.compile(r"[-+]?\d[\d.,%/:-]*")

_MIN_TABLE_LINES = 4
# A table smaller than this is not worth isolating; it reads better as prose.
_MIN_TABLE_TOKENS = 40
# Chunks below this are merged into a neighbour IN THE SAME SECTION rather than
# published on their own (22% of the owner's retrievable chunks were under 30
# tokens). Never across sections: a chunk's section is the clause every
# requirement read from it is filed under.
_MIN_CHUNK_TOKENS = 40
# More heading-like lines than this on one page means it is a contents page.
_CONTENTS_PAGE_HEADINGS = 4
# Section numbers are small; anything larger is an address or a measurement.
_MAX_SECTION_NUMBER = 99
_ANY_DIGIT = re.compile(r"\d")
_MATH_PUNCT = re.compile(r"[()\[\]{}=+*/\<>|^_~]")
# As above but without parentheses, which specification headings do use.
_MATH_PUNCT_STRICT = re.compile(r"[\[\]{}=+*/\<>|^_~]")

# A clause number alone on its line, with the title on the NEXT line. This is
# how NORSOK and most engineering specifications lay out headings:
#     '4.6 '
#     'Steel materials '
# A single-line "4.6 Steel materials" is the textbook convention. Both occur,
# so both are detected. Annex numbering (A.1, A.5.1) is included because
# engineers cite annex clauses exactly as they cite body clauses.
_CLAUSE_NUMBER_ONLY = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s*$")
#: The clause number part of a heading, body or annex.
_CLAUSE_NUMBER = r"(?:[A-Z]\.)?\d+(?:\.\d+){0,3}"
#: A line that opens with a dotted clause number and words: "4.3.1 Abrasive".
_CLAUSE_NUMBER_LEAD = re.compile(r"^\s*(?:[A-Z]\.)?\d+(?:\.\d+){1,4}\s+[A-Z]")

# ------------------------------------------------------ page classification

# A contents line: "5.3.1 Identity Theft 257"
_TOC_LINE = re.compile(r"^\s*\S.*\s\d{1,4}\s*$")
# An index line: "identity theft, 257, 261-263"
_INDEX_LINE = re.compile(r"^\s*\S[^,]{2,60},\s*\d{1,4}(\s*[-,]\s*\d{1,4})*\s*$")
# A page number alone on its line - the right-hand column of a two-column TOC.
_BARE_NUMBER = re.compile(r"^\d{1,4}$")
_MIN_TOC_NUMBER_LINES = 10
# Overlap may never exceed this multiple of the configured budget.
_MAX_OVERLAP_FACTOR = 1.5

_FRONTMATTER_MARKERS = (
    "isbn", "all rights reserved", "library of congress", "cataloging-in-publication",
    "printed in the united states", "copyright ©", "no part of this publication",
    "pearson education", "cengage", "wiley", "mcgraw-hill",
    "photo credit", "cover credit", "fotolia", "shutterstock", "getty images",
    "acquisitions editor", "managing editor", "production editor",
    "editor in chief", "editorial director", "portfolio manager",
    "marketing manager", "marketing assistant", "cover design", "cover art",
    "rights and permissions", "manufacturing buyer",
    "vice president", "typeset in", "www.pearson", "permissions department",
)

#: Markers that are ordinary words in engineering prose and only mean front
#: matter in their publishing sense. "composition" cost NORSOK its entire
#: Clause 8: the page says metal shall be "marked with composition", which
#: tripped a single-marker match and classified 3,197 characters of thermally
#: sprayed coating requirements as front matter. Requiring the publishing
#: context keeps the credit page and keeps the specification.
_AMBIGUOUS_FRONTMATTER_MARKERS = (
    # "composition and" was here and matched "marked with composition and
    # batch number" - the same mistake as the original marker, one layer down.
    # Only a form that cannot occur in engineering prose belongs in this list.
    "composition:", "composition services", "composition by",
)

_BACKMATTER_MARKERS = ("bibliography", "references", "works cited")


def _is_page_number_column(lines: list[str], total_pages: int) -> bool:
    """Do the bare numbers on this page behave like a column of page numbers?

    A contents or index column is bounded by the length of the document and
    runs largely in ascending order. A rubric's marks (60, 20, 40, 45) and an
    engineering table's codes and values are neither, which is what keeps a
    real table from being mistaken for an index and dropped.
    """
    numbers = [int(line) for line in lines if _BARE_NUMBER.match(line)]
    if len(numbers) < _MIN_TOC_NUMBER_LINES:
        return False

    ceiling = max(total_pages, 1) * 1.2
    in_range = [n for n in numbers if 1 <= n <= ceiling]
    if len(in_range) < len(numbers) * 0.9:
        return False

    if len(in_range) < 2:
        return False
    ascending = sum(1 for a, b in zip(in_range, in_range[1:]) if b >= a)
    return ascending >= (len(in_range) - 1) * 0.75


_REFERENCE_HEADING = re.compile(
    r"(?i)\b(?:references|bibliography|works\s+cited|further\s+reading|"
    r"selected\s+readings)\b"
)


def _only_reference_headings(text: str) -> bool:
    """Is every numbered heading on this page a references heading?

    Used to keep the dropped-real-content alert sharp. A page whose only
    numbered heading is "9.15 References" is a bibliography, not body text
    that went missing - but a page classified as references while carrying a
    heading like "9.15 Mass balance" is a misclassification worth an alert.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    stripped = [line.strip() for line in lines]
    found: list[str] = []
    i = 0
    while i < len(lines):
        head = looks_like_heading(lines[i])
        consumed = 1
        if head is None:
            head, consumed = _split_line_heading(stripped, i)
        if head:
            found.append(head)
        i += consumed
    if not found:
        return False
    return all(_REFERENCE_HEADING.search(h) for h in found)


def count_clause_headings(text: str) -> int:
    """How many validated numbered clause headings this page carries.

    Uses the same detector the chunker uses, single-line and split-line forms
    both, so "a page with clause headings" means exactly what it means
    everywhere else rather than being a second, drifting definition.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    stripped = [line.strip() for line in lines]
    found = 0
    i = 0
    while i < len(lines):
        head = looks_like_heading(lines[i])
        consumed = 1
        if head is None:
            head, consumed = _split_line_heading(stripped, i)
        if head:
            found += 1
        i += consumed
    return found


def classify_page(text: str, page_no: int, total_pages: int) -> str:
    """Classify a page as prose / toc / frontmatter / index / references.

    Contents and index pages are dense keyword lists with no content. Indexed
    as prose they outscore the body: a contents chunk containing
    "5.3.1 Identity Theft 257" beats page 257 where the answer actually is.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "prose"

    early = page_no <= max(12, total_pages * 0.05)

    # A half-title, dedication or epigraph: a nearly empty page at the front.
    # The line count matters as well as the word count - a short contents page
    # is also brief, but it is many short lines rather than one or two.
    #
    # A page carrying a genuine clause is CONTENT however short it is. Without
    # that guard a 39-word page of real specification prose was discarded as
    # front matter, which would silently drop a short specification or a first
    # page that happens to contain a real requirement.
    if (
        early
        and len(text.split()) < 40
        and len(lines) < 6
        and longest_clause(text) < MIN_CLAUSE_WORDS
    ):
        return "frontmatter"

    low = text.lower()
    marker_hits = sum(1 for m in _FRONTMATTER_MARKERS if m in low)
    marker_hits += sum(1 for m in _AMBIGUOUS_FRONTMATTER_MARKERS if m in low)

    # A PAGE CONTAINING NUMBERED CLAUSE HEADINGS AND REAL PROSE IS BODY TEXT.
    # This is the guard that matters most in the whole classifier. NORSOK page
    # 11 carries clauses 8.1 through 8.4 and 9.1, 9.2 - the entire section on
    # thermally sprayed metallic coatings - and was dropped as front matter.
    # The consequence was not a missing answer: asked for the maximum operating
    # temperature of a zinc metal coating (clause 8.2, 120 C) the system
    # answered "<= 80 C" from a different clause on another page, labelled
    # QUOTED VERBATIM with a page and a clause. A specification error with
    # money attached and no signal it happened.
    #
    # Both halves are required. A contents page has headings without
    # sentences; a copyright page has sentences without numbered clauses. Only
    # body text has both.
    if count_clause_headings(text) >= 1 and longest_clause(text) >= MIN_CLAUSE_WORDS:
        marker_hits = 0

    # Front matter markers are decisive wherever they appear.
    if marker_hits >= 2 or (marker_hits >= 1 and page_no <= max(12, total_pages * 0.05)):
        return "frontmatter"

    # An explicitly captioned table is never contents or index, wherever it sits.
    if _TABLE_CAPTION.search(text):
        return "prose"

    toc_lines = sum(1 for line in lines if _TOC_LINE.match(line))
    if len(lines) >= 6 and toc_lines >= len(lines) * 0.4 and toc_lines >= 5:
        # An index has the same shape but sits at the back of the book.
        if page_no > total_pages * 0.85:
            return "index"
        return "toc"

    # Two-column contents: the title and its page number extract as SEPARATE
    # lines, so the single-line pattern above never fires. Such a page is a
    # third or more bare page numbers stacked in their own column.
    #
    # Restricted to the front and back of the document on purpose. A body page
    # in a maths textbook also stacks bare numbers - equation numbers, answer
    # lists - and wrongly excluding real body text from search is far worse
    # than indexing a contents page.
    front = page_no <= max(20, total_pages * 0.06)
    back = page_no > total_pages * 0.85
    if front or back:
        bare_numbers = sum(1 for line in lines if _BARE_NUMBER.match(line))
        if (
            len(lines) >= 20
            and bare_numbers >= _MIN_TOC_NUMBER_LINES
            and bare_numbers >= len(lines) * 0.25
            # ...and the numbers must actually behave like PAGE numbers. A
            # marks rubric has the same shape - criteria against a numeric
            # column - but its numbers are scores, not a page sequence. So do
            # the codes and values in an engineering table.
            and _is_page_number_column(lines, total_pages)
        ):
            return "index" if back else "toc"

    index_lines = sum(1 for line in lines if _INDEX_LINE.match(line))
    if len(lines) >= 6 and index_lines >= len(lines) * 0.35:
        return "index"

    if page_no > total_pages * 0.85:
        head = " ".join(lines[:3]).lower()
        if any(m in head for m in _BACKMATTER_MARKERS):
            return "references"

    return "prose"


# Only these kinds are searchable. The rest are kept for inspection.
RETRIEVABLE_KINDS = frozenset({"prose", "table"})

# ------------------------------------------------------- content quality gate

_CONTROL_CHARS = re.compile("[" + "".join(chr(c) for c in list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127]) + "]")
_WORD_EDGE_PUNCT = ".,;:!?()[]{}\"'‘’“”"
# A real word starts with a letter and is letters/digits/hyphens throughout.
# Edge punctuation is stripped first so "Study:" and "Therac-25" both count.
_WORDISH = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


def _is_wordish(token: str) -> bool:
    return bool(_WORDISH.match(token.strip(_WORD_EDGE_PUNCT)))


def content_quality(text: str) -> dict:
    """Signals describing whether a chunk reads like natural language.

    This is the generic safety net. Individual detectors catch failure modes
    we predicted; this one catches the ones we did not. A symbol-font table
    that extracts as "eabeb2terfcb 1t a 2 1t ea1s 1s(1s b)" passes every
    structural check and is still worthless to retrieve.
    """
    stripped = text.strip()
    if not stripped:
        return {"ok": False, "reasons": ["empty"]}

    words = stripped.split()
    n = len(words)

    control = len(_CONTROL_CHARS.findall(stripped))
    letters = sum(1 for ch in stripped if ch.isalpha())
    spaces = sum(1 for ch in stripped if ch.isspace())
    symbols = len(stripped) - letters - spaces - sum(1 for ch in stripped if ch.isdigit())

    alpha_ratio = letters / len(stripped)
    symbol_ratio = symbols / len(stripped)
    avg_word_len = sum(len(w) for w in words) / max(n, 1)
    wordish = sum(1 for w in words if _is_wordish(w))
    wordish_ratio = wordish / max(n, 1)
    longest_run = max((len(w) for w in words), default=0)

    reasons = []
    if control > settings.quality_max_control_chars:
        reasons.append(f"control_chars={control}")
    if alpha_ratio < settings.quality_min_alpha_ratio:
        reasons.append(f"alpha_ratio={alpha_ratio:.2f}")
    if symbol_ratio > settings.quality_max_symbol_ratio:
        reasons.append(f"symbol_ratio={symbol_ratio:.2f}")
    if wordish_ratio < settings.quality_min_wordish_ratio:
        reasons.append(f"wordish_ratio={wordish_ratio:.2f}")
    if avg_word_len < settings.quality_min_avg_word_len:
        reasons.append(f"avg_word_len={avg_word_len:.2f}")
    if longest_run > settings.quality_max_unbroken_run:
        reasons.append(f"longest_run={longest_run}")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "alpha_ratio": round(alpha_ratio, 3),
        "symbol_ratio": round(symbol_ratio, 3),
        "wordish_ratio": round(wordish_ratio, 3),
        "avg_word_len": round(avg_word_len, 2),
        "longest_run": longest_run,
        "control_chars": control,
    }


def reads_like_language(text: str) -> bool:
    return content_quality(text)["ok"]


def looks_like_heading(line: str) -> str | None:
    """Return a section heading, or None.

    Deliberately strict. A wrong heading is worse than no heading: a citation
    reading "page 24, section: 330 Hudson Street, NY, NY 10013" - the
    publisher's address, lifted off the copyright page - looks broken to a
    reader and is inherited by every chunk that follows.

    Only an unambiguous numbered section pattern qualifies. An ALL-CAPS line
    is NOT enough; it matches addresses, credits and running heads. When in
    doubt the section stays null.
    """
    line = line.strip()
    if not line or len(line) > 90:
        return None
    m = _HEADING.match(line)
    if not m:
        return None
    # A contents line ends in a page number - but so does a legitimate
    # specification heading like "A.4 Coating system no. 4". The difference is
    # what precedes the number: a designator word means it is part of the
    # title, anything else means it is a page reference.
    if _TRAILING_PAGE_NO.search(line) and not _DESIGNATOR_TAIL.search(line):
        return None

    number, title = m.group(1), m.group(2).strip()
    if _CHAPTER_PREFIX.match(line) and "." not in number:
        # "CHAPTER 9 Numerical Solutions" - the word makes it unambiguous
        return f"{number} {title}" if len(title.split()) >= 2 else None
    return _validate_heading(number, title)


def _validate_heading(
    number: str, title: str, allow_bare_integer: bool = False
) -> str | None:
    """Shared checks for both the single-line and split-line heading forms."""
    # Kept before the trailing period is stripped: for a bare integer, whether
    # the title ENDS like a sentence is the discriminator between a clause
    # title and a general-note item, and stripping it first destroys the only
    # evidence available.
    raw_title = title.strip()
    title = raw_title.rstrip(".")
    if not title or len(title) > 90:
        return None

    # An annex clause (A.4) carries a letter prefix; body clauses do not.
    parts = [p for p in number.split(".") if p]
    numeric = [p for p in parts if p.isdigit()]
    lettered = [p for p in parts if not p.isdigit()]

    if lettered:
        # exactly one single-letter annex prefix, and it must come first
        if len(lettered) != 1 or parts[0] != lettered[0] or len(lettered[0]) != 1:
            return None
    if not numeric:
        return None

    # A section number is small and non-zero. "330 Hudson Street" is a street
    # address; "0 K(s, t) f(t) dt" is an integral, not section zero.
    if any(int(p) > _MAX_SECTION_NUMBER for p in numeric):
        return None
    if int(numeric[0]) < 1:
        return None

    # Maths and code punctuation never appears in a section title. Parentheses
    # are allowed because specification headings use them:
    # "A.1 Coating system no. 1 (shall be pre-qualified)".
    if _MATH_PUNCT_STRICT.search(title):
        return None
    # A real title is mostly letters, digits and spaces. Titles legitimately
    # carry numbers - "Coating system no. 4", "System 3B" - so digits are no
    # longer disqualifying; the address case is caught by the size guard above.
    allowed = sum(
        1 for ch in title if ch.isalnum() or ch.isspace() or ch in "()-,/&'."
    )
    if allowed < len(title) * 0.9:
        return None
    if not any(ch.isalpha() for ch in title):
        return None

    # A BARE integer is ambiguous: "1 Acceptance criteria are considered
    # acceptable" is a footnote, "15 Proper use of mutexes" is a rubric row,
    # "1 (a) Cosine integral" is an equation label. A dotted number
    # ("5.1 Introduction") or an annex letter ("A.1 ...") is unambiguous, and
    # every real heading in the four documents examined uses one. Bare
    # integers are therefore only accepted with an explicit CHAPTER/SECTION
    # prefix, handled by the caller.
    if "." not in number and not allow_bare_integer:
        return None

    if "." not in number:
        # A top-level clause on its own line, with its title on the next:
        #
        #     11
        #     Inspection and testing
        #
        # This is how NORSOK numbers its top-level clauses, and refusing it
        # meant clause 11 was never detected at all - so Table 3 and the whole
        # of Inspection and testing were filed under "10.3 Qualification of
        # procedures", making every citation into that region a wrong clause
        # even when the passage was right.
        #
        # Much stricter than a dotted number, because the same shape is a
        # general-note item ("1" then "Light colour non-skid aggregates shall
        # be used."). A note is a sentence and ends like one; a clause title
        # does not. Whether the number is REAL is then decided across the whole
        # document - see plausible_heading_numbers.
        words = title.split()
        if not 1 <= len(words) <= 8:
            return None
        if raw_title.endswith((".", ";", ":", ",")):
            return None
        if not title[:1].isupper():
            return None
        if len(words) == 1:
            # NORSOK's clause 1 is titled "Scope", and clauses titled with a
            # single word - Scope, References, Definitions, General - are the
            # norm at the top of a specification. A lone word is weaker
            # evidence than a phrase, so it has to be a real word rather than
            # a code or a fragment.
            if not words[0].isalpha() or len(words[0]) < 4:
                return None

    return f"{number} {title}"


def numericness(line: str) -> float:
    toks = line.split()
    if not toks:
        return 0.0
    numeric = sum(1 for t in toks if _NUMERIC_TOKEN.fullmatch(t))
    return numeric / len(toks)


@dataclass
class Block:
    kind: str  # "prose" | "table"
    text: str
    page_start: int
    page_end: int
    section: str | None = None
    tokens: int = 0
    #: A STRUCTURED block - a ruled table read by geometry, or a run of
    #: data-sheet rows - keeps its lines apart: `lead` (caption and header
    #: row, repeated at the top of every piece it is split into) and `rows`,
    #: with the page each row came from. None for ordinary prose/table text.
    lead: list[str] | None = None
    rows: list[str] | None = None
    row_pages: list[int] | None = None
    #: The header row as a tuple, so a table continued on the next page (its
    #: header reprinted) is recognised and joined to its first part.
    header: tuple[str, ...] | None = None


def _table_run_length(lines: list[str], i: int, stop=None) -> int:
    """How many lines from i form a table-like run. 0 if it is not one.

    Deliberately conservative. An earlier version treated any short line as
    tabular, which turned every equation in a maths textbook into its own
    tiny "table" chunk. A run must now be either introduced by an explicit
    TABLE/FIGURE caption, or be strongly numeric throughout.

    `stop(lines, j)` ends the run at a line the caller knows is a heading.
    AUDIT F5: a short non-numeric line may continue a run as a column header,
    and that rule consumed "6 Coating" and "6.1 Surface Preparation" after a
    table - clause 6.1 was then published under "5.2 Heat Treatment".
    """
    is_caption = bool(_TABLE_CAPTION.match(lines[i]))
    if not is_caption and numericness(lines[i]) < 0.6:
        return 0

    j = i
    counted = 0
    numeric_lines = 0
    while j < len(lines):
        line = lines[j]
        if not line.strip():
            if counted >= _MIN_TABLE_LINES:
                break
            j += 1
            continue
        if len(line.strip()) >= 60:
            break
        if j > i and stop is not None and stop(lines, j):
            break
        if _TABLE_CAPTION.match(line):
            counted += 1
            j += 1
            continue
        if numericness(line) >= 0.6:
            counted += 1
            numeric_lines += 1
            j += 1
            continue
        # a short non-numeric line is a column header - allowed, but only
        # while the run is still mostly numeric
        if len(line.strip()) < 25 and numeric_lines >= counted // 2:
            counted += 1
            j += 1
            continue
        break

    if counted < _MIN_TABLE_LINES:
        return 0
    # the run must actually contain numbers, not just short lines
    if not is_caption and numeric_lines < counted * 0.6:
        return 0
    return j - i


def _split_line_heading(lines: list[str], i: int) -> tuple[str | None, int]:
    """A clause number alone on its line, with the title on the next.

        '4.6 '
        'Steel materials '

    Returns (heading, lines_consumed). The title must look like a title and
    not like body text, or a numbered list item would swallow the sentence
    after it.
    """
    m = _CLAUSE_NUMBER_ONLY.match(lines[i])
    if not m:
        return None, 1

    for j in range(i + 1, min(i + 3, len(lines))):
        title = lines[j].strip()
        if not title:
            continue
        # A title is short and is not a sentence.
        if len(title) > 90 or title.endswith((".", ";", ":")) and len(title.split()) > 8:
            return None, 1
        if len(title.split()) > 12:
            return None, 1
        head = _validate_heading(m.group(1), title, allow_bare_integer=True)
        return (head, j - i + 1) if head else (None, 1)
    return None, 1


#: A DOTTED clause number (never a bare integer - that is a page number).
_DOTTED_CLAUSE_ONLY = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+){1,4})\.?\s*$")


def _numbered_paragraph(lines: list[str], i: int) -> str | None:
    """B6B E4: a clause number alone on its line, its REQUIREMENT on the next.

        '6.2.1 '
        'The unit shall be located so that ... '

    _split_line_heading rejects this on purpose - the next line is a sentence,
    not a title - so a standard laid out as numbered paragraphs had no clause
    state at all and every chunk inherited one early heading (measured: one
    real standard, 25 chunks, 2 clause labels). The number IS the clause a
    citation must name, so it becomes the section, as the number alone - no
    title is invented. Dotted numbers only; the document's own plausibility
    filter still decides whether the number belongs to its hierarchy.
    """
    m = _DOTTED_CLAUSE_ONLY.match(lines[i])
    if not m:
        return None
    for j in range(i + 1, min(i + 3, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        # the requirement starts as a sentence: a capital letter and words
        return m.group(1) if nxt[:1].isupper() and len(nxt.split()) >= 4 else None
    return None


# ------------------------------------------------ data-sheet rows (F1/P0)
#
# A paint-system data sheet is a column of "Label : value" rows:
#     4.1 Mixing Ratio
#     : 4:1 by Volume
#     4.5 Approved Color/s : Yellow (RAL 1023)
# Its numbered labels are heading-shaped, so "4.1 Mixing Ratio" became a
# clause, ": 4:1 by Volume" became that clause's whole text, and the quality
# gate dropped it as debris - measured on the owner's corpus: 3,761 chunks,
# 65% of one data-sheet standard. The rows are read here as DATA: one block of
# rows under the sheet's own title, never as headings.

#: "Approved Color/s : Yellow (RAL 1023)" - a SPACED colon. Prose writes
#: "Note: the ...", a data sheet puts the colon in a column of its own.
_FIELD_INLINE = re.compile(r"^\s*(?P<label>[^:]{1,60}?\S)\s+:\s+\S")
#: The value on a line of its own: ": 4:1 by Volume".
_FIELD_VALUE = re.compile(r"^\s*:\s*\S")
_SENTENCE_ENDINGS = (".", ";", ":", "!", "?")
#: A body line wraps at the text width; one this long that does not end a
#: sentence is continued by the next line, which is therefore not a new row.
_WRAPPED_LINE_CHARS = 70


def _prev_nonblank(lines: list[str], i: int) -> str | None:
    j = i - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    return lines[j].strip() if j >= 0 else None


def _next_nonblank(lines: list[str], i: int) -> int | None:
    j = i
    while j < len(lines) and not lines[j].strip():
        j += 1
    return j if j < len(lines) else None


def _wrapped_from_previous(lines: list[str], i: int) -> bool:
    prev = _prev_nonblank(lines, i)
    return bool(prev) and len(prev) >= _WRAPPED_LINE_CHARS and not prev.endswith(
        _SENTENCE_ENDINGS)


def _label_like(line: str) -> bool:
    """A field label or group label on its own line: short, not a sentence."""
    t = line.strip()
    return (
        0 < len(t) <= 60 and len(t.split()) <= 8
        and bool(_HAS_LETTER.search(t))
        and not t.endswith((".", ",", ";", ":"))
        and not t.startswith(":")
        and not t.startswith(_TABLE_SENTINEL)
    )


def _field_row(lines: list[str], i: int) -> tuple[str | None, int]:
    """One data-sheet row starting at line i: (row text, lines consumed)."""
    t = lines[i].strip()
    if not t or t.startswith(_TABLE_SENTINEL) or _wrapped_from_previous(lines, i):
        return None, 1
    inline = _FIELD_INLINE.match(t)
    if (inline and _HAS_LETTER.search(inline.group("label")) and len(t) <= 75) or \
            _FIELD_VALUE.match(t):
        j = i + 1
    elif _label_like(t):
        k = _next_nonblank(lines, i + 1)
        if k is None or k > i + 2 or not _FIELD_VALUE.match(lines[k]):
            return None, 1
        j = k
    else:
        return None, 1
    parts = [t]
    while j < len(lines) and _FIELD_VALUE.match(lines[j]):
        parts.append(lines[j].strip())
        j += 1
    return " ".join(parts), j - i


def _field_run(lines: list[str], i: int) -> tuple[list[str], int]:
    """A run of data-sheet rows from line i: (rows, lines consumed).

    A short label between rows ("4 Mixing and Curing") is a GROUP label and
    stays in the run as a row of its own, so one sheet stays one block. Empty
    when line i does not start a run.
    """
    rows: list[str] = []
    j = i
    while j < len(lines):
        if not lines[j].strip():
            k = _next_nonblank(lines, j)
            if k is None or not rows or _field_row(lines, k)[0] is None:
                break
            j = k
            continue
        row, used = _field_row(lines, j)
        if row:
            rows.append(row)
            j += used
            continue
        k = _next_nonblank(lines, j + 1)
        if _label_like(lines[j]) and k is not None and _field_row(lines, k)[0]:
            rows.append(lines[j].strip())
            j += 1
            continue
        break
    if not any(":" in r for r in rows):
        return [], 0
    return rows, j - i


#: A numbered requirement written as running text on a line too long to be a
#: heading: "4.2.1 Stud bolts for flanges in hydrocarbon service shall be ...".
_NUMBERED_SENTENCE = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+){1,4})\s+[A-Z(]")


def _numbered_requirement(lines: list[str], i: int) -> str | None:
    """AUDIT F8: the clause number of a numbered requirement paragraph.

    `looks_like_heading` refuses lines over 90 characters, so a requirement
    that opens its own paragraph with its number stayed under the PARENT
    clause - "4.2.1 Stud bolts ... 725 MPa" was cited as 4.2. The number is
    taken only when (a) the line opens a paragraph - the line before it ends
    a sentence or there is none - and (b) the sentence it starts contains
    "shall" within four lines. The document's plausibility filter still
    decides whether the number belongs to its hierarchy.
    """
    t = lines[i].strip()
    m = _NUMBERED_SENTENCE.match(t)
    if not m:
        return None
    prev = _prev_nonblank(lines, i)
    if prev is not None and not prev.endswith(_SENTENCE_ENDINGS) and not (
            looks_like_heading(prev) or prev.startswith(_TABLE_SENTINEL)):
        return None
    sentence = t
    k = i + 1
    while not sentence.rstrip().endswith((".", ";")) and k < len(lines) and k <= i + 3:
        sentence += " " + lines[k].strip()
        k += 1
    return m.group(1) if _OBLIGATION.search(sentence) else None


def _continues_as_sentence(lines: list[str], i: int) -> bool:
    """Does the text resume in lower case at line i? Then the "heading" above
    it was the first line of a wrapped numbered requirement, not a title."""
    k = _next_nonblank(lines, i)
    return k is not None and lines[k].strip()[:1].islower()


def _heading_number(heading: str) -> str:
    """The numbering off the front of a validated heading string."""
    return heading.split(" ", 1)[0]


def _obliges(heading: str) -> bool:
    """Whether a heading's "title" is really the first line of a requirement.

    "4.4 Design loads shall be as per the building code" passes every heading
    test - a dotted number, a capital, under 90 characters - and it is a
    numbered PARAGRAPH, not a titled clause. As a heading its line was consumed
    into the section label and never reached the chunk's text, so the
    requirement it states was never read: measured on one real standard, seven
    requirements disappeared this way once a change table stopped masking it
    (see revision_history_regions).

    It is still a clause NUMBER - page classification and the contents test
    count it as one, and must - so it is decided here, where a heading becomes
    the section, and nowhere earlier. A parenthetical is a note on a title, not
    the title: NORSOK heads a clause "A.1 Coating system no. 1 (shall be
    pre-qualified)", and that is a heading.
    """
    title = heading.split(" ", 1)[1] if " " in heading else ""
    return _OBLIGATION.search(_PARENTHETICAL.sub(" ", title)) is not None


def _bare_integer_clauses(numbers: list[str]) -> set[str]:
    """Which bare integers, in document order, behave like clause numbering.

    Clause numbering increases monotonically through a document. A general-note
    list restarts at 1 under every clause, so a bare integer that is not
    greater than the last accepted one is a restart, not a clause. Jumps are
    capped too: 1, 2, 3, 40 is not a hierarchy.

    Where the walk begins matters. Requiring it to start at 1, 2 or 3 works on
    a whole specification but fails on an extract that happens to open at
    clause 8 - so a bare integer is also accepted as a starting point when the
    document carries DOTTED headings under it. If 8.1 and 8.2 are headings,
    then 8 is a clause, wherever the document begins.
    """
    corroborated = {
        number.split(".")[0]
        for number in numbers
        if "." in number and number.split(".")[0].isdigit()
    }

    accepted: set[str] = set()
    last = 0
    for number in numbers:
        if "." in number or not number.isdigit():
            continue
        value = int(number)
        if last == 0:
            # the first one has to look like the start of a numbering scheme,
            # or be corroborated by its own subclauses
            if value > 3 and number not in corroborated:
                continue
        elif not last < value <= last + 3:
            # a jump is allowed when subclauses vouch for it
            if not (value > last and number in corroborated):
                continue
        accepted.add(number)
        last = value
    return accepted


def plausible_heading_numbers(numbers: list[str]) -> set[str]:
    # NOTE: ORDER MATTERS. Bare integers are judged by a monotonic walk in
    # DOCUMENT ORDER, so passing a set silently changes the answer - a test
    # that did exactly that passed for a while on the luck of set iteration
    # order. Typed as a list rather than an Iterable to make that a mistake
    # the reader can see.
    """Keep only numbering that fits the hierarchy the document actually has.

    Page 523 of the professional-practices textbook is a list of exercises -
    9.35, 9.36, 9.37, 9.40 - each opening a numbered paragraph. Every one of
    them matches the heading pattern perfectly, and the pattern that finally
    read NORSOK's clauses started inventing headings out of them. A citation
    reading "section: 9.33 In Section 9.3.12" is worse than no section at all.

    The discriminator is the document's own numbering. A real hierarchy is
    reachable by counting: if 9.1 through 9.5 are headings, 9.6 might be, but
    9.33 is not - there is no 9.6 to 9.32 for it to follow. An enumerated list
    gives itself away by starting somewhere the hierarchy never reaches.

    Deliberately conservative. When a group does not start at 1 the run cannot
    be established at all, so everything in it is kept: the cost of a missed
    rejection is one bad section label, and the cost of over-rejecting is a
    whole document losing its clauses.
    """
    ordered = list(numbers)
    by_parent: dict[str, set[int]] = {}
    for number in ordered:
        parent, _, last = number.rpartition(".")
        if last.isdigit():
            by_parent.setdefault(parent, set()).add(int(last))
    #: A number is VOUCHED FOR by its own children: if 4.5.1 is a heading
    #: candidate, 4.5 exists whatever came before it.
    parents_with_children = set(by_parent)

    allowed: set[str] = set()
    for parent, seen in by_parent.items():
        if parent == "":
            # Bare integers get a stricter test than contiguity. A general-note
            # list also runs 1, 2, 3 - and RESTARTS under the next clause,
            # which is what gives it away. Real top-level clause numbering only
            # ever increases through a document, so the accepted set is the
            # increasing walk taken in document order, and every restart is
            # rejected. See _bare_integer_clauses.
            continue
        def name(n: int, parent: str = parent) -> str:
            return f"{parent}.{n}" if parent else str(n)

        if min(seen) > 1:
            allowed |= {name(n) for n in seen}
            continue
        # AUDIT F4 (2026-09-27): the walk used to stop at the FIRST GAP, so
        # one missing sibling - a deleted "Not used" clause, a heading on a
        # scanned page - refused every later sibling, and a unit run with
        # 4.1, 4.3 ... 4.7 filed all six blocks under "4.1 Scope". A gap of
        # up to two missing numbers is accepted (the step `_bare_integer_
        # clauses` already allows), and so is any sibling its own children
        # vouch for. An exercise list that starts far beyond the hierarchy
        # (9.1 ... 9.5, then 9.33) still fails both tests.
        accepted: list[int] = []
        for n in sorted(seen):
            if not accepted or n <= accepted[-1] + 3 or name(n) in parents_with_children:
                accepted.append(n)
        allowed |= {name(n) for n in accepted}

    allowed |= _bare_integer_clauses(ordered)
    return allowed


def is_contents_page(lines: list[str]) -> bool:
    """Whether this page's headings should be ignored as a contents listing.

    Counting heading-like lines alone is not the test, and using it as one was
    the defect this function exists to fix. A DENSE SPECIFICATION BODY PAGE
    CARRIES MANY REAL HEADINGS. doc16 page 44 opens clause 5 and runs 5.1,
    5.2, 5.3, 5.3.1, 5.3.2, 5.4, 5.4.1, 5.4.2 - eight genuine headings with
    their requirement text under each. Above a bare count of four, every one of
    them was discarded, the page set no section state, and the label left in
    force was 4.4.2 from the previous page. The same happened on pages 46, 48
    and 49, so "8.3.2 DRAWING EXTRACTION REQUIREMENTS" was published as clause
    6.4.2: a citation pointing an engineer at a different requirement.

    The discriminator is the one classify_page already uses for the same
    distinction: a contents page is headings WITHOUT prose, body text is
    headings WITH prose. So the heading lines are set aside and what remains is
    asked whether it contains a clause-length run of real words. A contents
    page leaves behind titles and page numbers and fails that; a body page
    leaves behind its requirements and passes.
    """
    heading = [looks_like_heading(line) is not None for line in lines]
    if sum(heading) <= _CONTENTS_PAGE_HEADINGS:
        return False
    rest = " ".join(
        line
        for line, is_head in zip(lines, heading, strict=True)
        if not is_head and line.strip()
    )
    return longest_clause(rest) < MIN_CLAUSE_WORDS


#: THE TITLE OF A REVISION-HISTORY SECTION. Standards bodies print one of a
#: handful of names above the record of what changed between revisions - a
#: "Summary of Changes" table at the front, a dated "Document History" or
#: "Revision Summary" at the back. The vocabulary is that of document control,
#: not of any one standard, and the title must be the WHOLE line: "refer to
#: summary of changes" in a sentence is prose, not a section.
_REVISION_HISTORY_TITLE = re.compile(
    r"^\s*(?:summary\s+of\s+changes|revision\s+summary|revision\s+history"
    r"|document\s+history|record\s+of\s+revisions?|history\s+of\s+revisions?"
    r"|change\s+history|amendment\s+record)\s*:?\s*$",
    re.IGNORECASE,
)

#: How many lines under the title form the table's header row, and how far
#: into a following page that header has to reappear for the table to be
#: read as continuing there.
_HISTORY_HEADER_LINES = 2
_HISTORY_HEADER_WINDOW = 6


def is_revision_history(section: str | None) -> bool:
    """Whether a chunk's section is a revision-history record, not a clause.

    ONE HOME FOR THE QUESTION: the chunker files a history under its own title,
    and every consumer that must not treat that text as normative - the
    requirement extractor first - asks here rather than matching titles again.
    """
    return bool(section) and _REVISION_HISTORY_TITLE.match(section) is not None


def _history_key(line: str) -> str:
    return _WS.sub(" ", line).strip().casefold()


# ----------------------------------------------------- ruled tables (F1)


def _sentinel_table(line: str) -> dict | None:
    if not line.startswith(_TABLE_SENTINEL):
        return None
    try:
        return json.loads(line[len(_TABLE_SENTINEL):])
    except ValueError:
        return None


def _raw_table_lines(lines: list[str]) -> list[str]:
    """Lines with every table put back as the text lines it covered - for the
    passes (revision history) that read a table the way extraction wrote it."""
    out: list[str] = []
    for line in lines:
        table = _sentinel_table(line)
        out.extend(table["raw"] if table else [line])
    return out


def mask_tables(pages: list[tuple[int, str]],
                page_tables: dict[int, list[dict]] | None,
                running: set[str]) -> list[tuple[int, str]]:
    """Replace each ruled table's lines by ONE sentinel line carrying the table.

    Its cells then never reach the heading detector (AUDIT F1: "3.0" above
    "Hydrocarbon" was read as clause "3.0 Hydrocarbon"), the running-line
    stripper (F2) or the prose - a table's text appears once, as the table.

    A "table" whose every line is page furniture - the ruled header box a
    standard prints on every page - is left as text for the stripper to
    remove; emitting it would put the header on every page into search.
    """
    if not page_tables:
        return pages
    out: list[tuple[int, str]] = []
    for page_no, text in pages:
        found = page_tables.get(page_no)
        if not found:
            out.append((page_no, text))
            continue
        lines = text.split("\n")
        replace: dict[int, str | None] = {}
        for table in found:
            idx = sorted(i for i in table.get("lines", []) if 0 <= i < len(lines)
                         and i not in replace)
            if not idx or not table.get("rows"):
                continue
            raw = [lines[i] for i in idx]
            body = [r for r in raw if r.strip()]
            if body and all(_is_running(r, running, page_no) for r in body):
                continue
            payload = json.dumps({"rows": table["rows"], "raw": raw},
                                 ensure_ascii=False, separators=(",", ":"))
            replace[idx[0]] = _TABLE_SENTINEL + payload
            for i in idx[1:]:
                replace[i] = None
        kept = [replace.get(i, line) for i, line in enumerate(lines)
                if not (i in replace and replace[i] is None)]
        out.append((page_no, "\n".join(kept)))
    return out


def _table_header(rows: list[list[str]]) -> tuple[list[str] | None, list[list[str]]]:
    """(header, data rows). Row 0 is a header when every cell in it carries a
    letter - "Service | Material | CA (mm)" - and it is not a label/value pair
    ("Mixing Ratio | 4:1"). Multi-row headers fold as `tables._compose_header`
    folds them, so a spanning parent names each child column."""
    first = rows[0]
    cells = [c for c in first if c]
    if not cells or not all(_HAS_LETTER.search(c) for c in cells):
        return None, rows
    if len(first) == 2 and _DIGITS.search(first[1] or ""):
        return None, rows
    header, data = tables_mod._compose_header(rows)
    return header, data


def _md_row(cells: list[str], width: int) -> str:
    padded = [(c or "").strip() for c in cells] + [""] * (width - len(cells))
    return "| " + " | ".join(padded) + " |"


def table_block_parts(table: dict) -> tuple[list[str], list[str], tuple[str, ...] | None]:
    """(header lines, row lines, header key) for one recovered table: rows as
    markdown-like lines so a value is never separated from its row, and the
    header kept apart so it can be repeated on every piece of a split."""
    rows = table["rows"]
    width = max(len(r) for r in rows)
    header, data = _table_header(rows)
    lead = [_md_row(header, width)] if header else []
    return lead, [_md_row(r, width) for r in data], (tuple(header) if header else None)


def revision_history_regions(
    pages: list[tuple[int, str]],
    running: set[str],
    page_kinds: dict[int, str] | None = None,
) -> dict[int, tuple[int, str]]:
    """Where each page's revision-history record starts: {page: (line, title)}.

    THE DEFECT THIS FIXES. A standard's "Summary of Changes" is a table of
    (row, paragraph, change type, description): "14 / 5.1.4 / Deletion / No CSD
    recommendation is required ...". Its paragraph column is a column of clause
    NUMBERS, so the heading detector read every row as a clause heading. The
    rows ran the top-level numbering into the teens, the body's real "1 Scope",
    "2 Conflicts and Deviations", "3 References" then looked like a numbering
    restart and were refused, and the last row's "14.1.5 Editorial" stayed in
    force: requirements from the Scope were published as clause 14.1.5 - a
    citation to a clause the standard does not have. Its descriptions became
    requirements too ("is required" reads as an obligation), stating as a rule
    what is only a note about the previous revision.

    A REGION, BOUNDED BY PAGE LAYOUT, NOT BY NUMBERING. It opens at a line that
    is exactly a revision-history title and runs to the end of that page. It
    continues onto the next page only while that page REPEATS THE TABLE'S HEADER
    ROW (the first lines under the title) near its top - a multi-page change
    table reprints its column heads; a body page and a dated history do not.
    Numbering cannot bound it: some standards print no clause numbers in the
    text at all, and the change table itself starts at "1".

    Known limit, deliberately accepted: body text on the SAME page, after a
    history, is read as history. Ending mid-page would need the numbering this
    region exists to distrust; every standard measured starts its body on a new
    page, and a history at the back is followed by a page break or nothing.
    """
    kinds = page_kinds or {}
    regions: dict[int, tuple[int, str]] = {}
    active: tuple[str, list[str]] | None = None
    for page_no, raw in pages:
        if kinds.get(page_no, "prose") != "prose":
            active = None
            continue
        cleaned, _ = strip_running_lines(raw, running, page_no)
        lines = cleaned.splitlines()
        # Keys are read from the table AS EXTRACTED (one cell per line), so
        # a masked change table repeats its header exactly as it used to.
        keys = [_history_key(line) for line in _raw_table_lines(lines)]
        if active is not None:
            title, header = active
            top = [k for k in keys if k][:_HISTORY_HEADER_WINDOW]
            if len(header) == _HISTORY_HEADER_LINES and all(h in top for h in header):
                regions[page_no] = (0, title)
                continue
        active = None
        for index, line in enumerate(lines):
            if _REVISION_HISTORY_TITLE.match(line):
                title = _WS.sub(" ", line).strip().rstrip(":").strip()
                header = [k for k in (_history_key(x) for x in
                                      _raw_table_lines(lines[index + 1:])) if k
                          ][:_HISTORY_HEADER_LINES]
                regions[page_no] = (index, title)
                active = (title, header)
                break
    return regions


#: A dotted paragraph number at the start of a line.
_LEADING_DOTTED_NUMBER = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+){1,4})(?![\d.]*\d)")


def _history_paragraph_numbers(
    pages: list[tuple[int, str]],
    running: set[str],
    history: dict[int, tuple[int, str]],
) -> list[str]:
    """The DOTTED paragraph numbers a revision history names - as evidence only.

    A change table's paragraph column lists paragraphs of THIS revision, so it
    is the document's own statement of which clause numbers exist. The body
    does not always print a number in a form the heading detector collects:
    one real standard prints "6.2.2" alone on its line with the requirement
    beneath, so without this the 6.2 group read 1, 3, 4 ... and the gap
    refused 6.2.3 to 6.2.7 as headings. The history's numbers may therefore
    vouch for the hierarchy (`plausible_heading_numbers`), and still never set
    a section - see revision_history_regions.

    Dotted only. Bare integers are what ran the top-level walk into the teens;
    they are left out, so the body's own 1, 2, 3 decide its top level.
    """
    found: list[str] = []
    for page_no, raw in pages:
        if page_no not in history:
            continue
        cleaned, _ = strip_running_lines(raw, running, page_no)
        start = history[page_no][0]
        for line in _raw_table_lines(cleaned.splitlines()[start:]):
            match = _LEADING_DOTTED_NUMBER.match(line)
            if match:
                found.append(match.group(1))
    return found


def _candidate_headings(
    pages: list[tuple[int, str]],
    running: set[str],
    page_kinds: dict[int, str] | None,
    numbered_paragraphs: bool = False,
    history: dict[int, tuple[int, str]] | None = None,
) -> list[str]:
    """Every heading the detector would accept, before plausibility filtering.

    A pre-pass, because whether 9.33 is a heading cannot be decided from the
    line itself - it depends on what else the document numbers.
    """
    kinds = page_kinds or {}
    found: list[str] = []
    for page_no, raw in pages:
        if kinds.get(page_no, "prose") != "prose":
            continue
        cleaned, _ = strip_running_lines(raw, running, page_no)
        lines = cleaned.splitlines()
        if is_contents_page(lines):
            continue  # a contents page never sets heading state
        # A revision history's paragraph column is not the document's
        # numbering - see revision_history_regions.
        end = (history or {}).get(page_no, (len(lines), None))[0]
        i = 0
        while i < end:
            # data-sheet rows are data, never headings - see _field_run
            rows, used = _field_run(lines, i)
            if rows:
                i += used
                continue
            head = looks_like_heading(lines[i])
            consumed = 1
            if head is None:
                head, consumed = _split_line_heading(lines, i)
            if head is None and numbered_paragraphs:
                head = _numbered_paragraph(lines, i)
            if head is None:
                head = _numbered_requirement(lines, i)
            if head:
                found.append(head)
            i += consumed
    return found


def _pop_caption(buf: list[str], accept, most: int) -> list[str]:
    """Take up to `most` trailing lines of `buf` that `accept` - the caption
    above a table, the title lines above a data sheet. Mutates `buf`."""
    taken: list[str] = []
    while buf and len(taken) < most:
        if not buf[-1].strip():
            buf.pop()
            continue
        if not accept(buf[-1].strip()):
            break
        taken.insert(0, buf.pop().strip())
    return taken


def segment_document(
    pages: list[tuple[int, str]],
    running: set[str],
    page_kinds: dict[int, str] | None = None,
) -> tuple[list[Block], int]:
    """Flatten pages into blocks, carrying heading state across page boundaries."""
    blocks: list[Block] = []
    section: str | None = None
    removed_total = 0
    #: The highest top-level clause number accepted so far. Clause numbering
    #: only increases through a document, so anything at or below this is a
    #: figure in a table rather than a heading.
    last_bare_integer = 0

    # Decided across the whole document, not line by line - see
    # plausible_heading_numbers.
    history = revision_history_regions(pages, running, page_kinds)
    candidates = _candidate_headings(pages, running, page_kinds, history=history)
    # B6B E4: NUMBERED-PARAGRAPH ANCHORS ONLY WHERE THE DOCUMENT HAS NO OTHER
    # STRUCTURE. A standard whose titled headings the detector reads keeps
    # exactly the chunking it had - measured: switching the anchors on
    # everywhere split well-structured standards finer and lost recall on
    # reworded questions. Only a document with fewer detected headings than
    # half its prose pages is read as numbered paragraphs.
    prose_pages = sum(1 for p, _ in pages if (page_kinds or {}).get(p, "prose") == "prose")
    numbered_paragraphs = len(candidates) < max(1, prose_pages // 2)
    if numbered_paragraphs:
        candidates = _candidate_headings(pages, running, page_kinds,
                                         numbered_paragraphs=True, history=history)
    allowed_numbers = plausible_heading_numbers([
        *(_heading_number(h) for h in candidates),
        *_history_paragraph_numbers(pages, running, history),
    ])

    kinds = page_kinds or {}

    def heading_stops_table(lines: list[str], j: int) -> bool:
        """A table-like run ends at a line that is a real heading here."""
        head = looks_like_heading(lines[j]) or _split_line_heading(lines, j)[0]
        if not head:
            return False
        number = _heading_number(head)
        if number not in allowed_numbers:
            return False
        return "." in number or not number.isdigit() or int(number) > last_bare_integer

    # A HEADING WITH NOTHING UNDER IT WAS KEPT NOWHERE. A heading's words live
    # in its chunks' `section`, not their text - so a heading followed straight
    # by the next heading ("5 GENERAL" / "5.1 Scope") produced no chunk at all
    # and its words reached neither search nor the exclusion ledger. Measured
    # on the owner's corpus (2026-09-29, counts only): 282 documents, about
    # 224,000 lines, ~200 heading lines in no chunk and no exclusion, in 150
    # documents. Such a heading is now CARRIED into the text of the next block
    # (a chapter title above its first subclause: "8 Thermally sprayed metallic
    # coatings" then "8.1 General" - the title reads with 8.1's text), never
    # made a passage of its own: a title alone answers nothing and, measured,
    # a title-only chunk took a retrieval slot from a real passage. Only at
    # the very end, with no block left to carry it, is it a block by itself.
    pending_heading: tuple[list[str], int, str] | None = None
    pending_mark = 0
    carry: list[str] = []
    carry_at: tuple[int, str | None] = (0, None)

    def settle_heading() -> None:
        nonlocal pending_heading, carry_at
        if pending_heading is not None and len(blocks) == pending_mark:
            head_lines, head_page, head_section = pending_heading
            if not carry:
                carry_at = (head_page, head_section)
            carry.extend(line.strip() for line in head_lines if line.strip())
        pending_heading = None

    def take_carry() -> list[str]:
        taken = list(carry)
        carry.clear()
        return taken

    for page_no, raw in pages:
        page_kind = kinds.get(page_no, "prose")
        cleaned, removed = strip_running_lines(raw, running, page_no)
        removed_total += removed
        lines = cleaned.splitlines()

        if page_kind != "prose":
            # Front matter, contents and index are kept whole for inspection
            # but never treated as prose, and never set heading state.
            body = cleaned.strip()
            if body:
                blocks.append(Block(page_kind, body, page_no, page_no, None))
            continue

        # A contents page is a wall of heading-like lines with no prose under
        # them. Letting it set the section state makes every later chunk
        # inherit a heading from the front matter, so headings from such a page
        # are ignored entirely - but see is_contents_page for why the count of
        # heading lines is NOT on its own the test.
        contents_page = is_contents_page(lines)

        buf: list[str] = []
        i = 0
        # Where this page's revision history starts, if it has one. Its lines
        # are filed under the history's own title, set no heading state and
        # move no numbering - the section in force before it resumes after it.
        history_start, history_title = history.get(page_no, (len(lines), None))

        # `page_no` is a default argument ON PURPOSE, and it is not redundant:
        # it makes the closure capture this page's VALUE instead of the loop
        # variable, so the function cannot mis-attribute a block if it is ever
        # called after the loop has moved on. Today every call sits inside the
        # iteration that defined it, which is a property of the CALL SITES and
        # not of the function - exactly the fragility ruff's B023 flags.
        #
        # `section` is deliberately NOT bound the same way. It is reassigned
        # while the page is walked, and each flush must use the section in
        # force at that moment: text before a heading belongs to the PREVIOUS
        # section, which is why the flush happens before the reassignment.
        # Freezing it as a default would silently mis-file every heading, so it
        # is passed in at each call instead of read from the enclosing scope.
        def flush_prose(current_section: str | None, page_no: int = page_no) -> None:
            nonlocal buf
            body = "\n".join(buf).strip()
            if body:
                body = "\n".join([*take_carry(), body])
                blocks.append(Block("prose", body, page_no, page_no, current_section))
            buf = []

        def emit_structured(lead: list[str], rows: list[str],
                            header: tuple[str, ...] | None,
                            current_section: str | None,
                            page_no: int = page_no) -> None:
            """Append a structured block - or extend the table it continues.
            `current_section` is passed at each call for the reason
            flush_prose documents above."""
            prev = blocks[-1] if blocks else None
            if (header and prev is not None and prev.rows is not None
                    and prev.header == header and prev.section == current_section
                    and page_no - 1 <= prev.page_end <= page_no):
                # The same table continued: its header reprinted on the next
                # page. One table, one block - split later on row boundaries.
                prev.rows.extend(rows)
                prev.row_pages.extend([page_no] * len(rows))
                prev.page_end = page_no
                prev.text = "\n".join(prev.lead + prev.rows)
                return
            lead = [*take_carry(), *lead]
            blocks.append(Block(
                "table", "\n".join(lead + rows), page_no, page_no, current_section,
                lead=list(lead), rows=list(rows), row_pages=[page_no] * len(rows),
                header=header))

        while i < len(lines):
            line = lines[i]

            if i >= history_start:
                flush_prose(section)
                rest: list[str] = []
                for rest_line in lines[i:]:
                    table = _sentinel_table(rest_line)
                    if table:
                        lead, rows, _ = table_block_parts(table)
                        rest.extend(lead + rows)
                    else:
                        rest.append(rest_line)
                body = "\n".join(rest).strip()
                if body:
                    body = "\n".join([*take_carry(), body])
                    blocks.append(Block("prose", body, page_no, page_no, history_title))
                break

            table = _sentinel_table(line)
            if table is not None:
                # A ruled table read by geometry: one structured block under
                # the section in force, its caption taken from the line above.
                caption = _pop_caption(buf, lambda t: bool(_TABLE_CAPTION.match(t)), 1)
                flush_prose(section)
                lead, rows, header = table_block_parts(table)
                if caption and not (blocks and blocks[-1].header == header and header
                                    and "continued" in caption[0].lower()):
                    lead = caption + lead
                if rows:
                    emit_structured(lead, rows, header, section)
                i += 1
                continue

            rows, used = _field_run(lines, i)
            if rows:
                # Data-sheet rows: data, not headings. The sheet's title lines
                # above them go with them, so "Mixing Ratio : 4:1 by Volume"
                # still says WHICH system it belongs to.
                caption = _pop_caption(
                    buf, lambda t: len(t) <= 80 and not t.endswith(_SENTENCE_ENDINGS), 3)
                flush_prose(section)
                emit_structured(caption, rows, None, section)
                i += used
                continue

            head = looks_like_heading(line)
            consumed = 1
            if head is None:
                # The split-line form: a clause number alone, its title on the
                # next line. This is how NORSOK and most engineering
                # specifications lay headings out, and it is why every chunk
                # in such a document had section: null.
                head, consumed = _split_line_heading(lines, i)
            if head is None and numbered_paragraphs:
                # B6B E4: a numbered paragraph - the clause number alone, the
                # requirement sentence (not a title) beneath it.
                head = _numbered_paragraph(lines, i)
            numbered_requirement = False
            if head is None:
                # AUDIT F8: a numbered requirement too long to be a heading.
                head = _numbered_requirement(lines, i)
                numbered_requirement = head is not None

            if head is not None:
                number = _heading_number(head)
                if number not in allowed_numbers:
                    # numbering the document's hierarchy never reaches: an
                    # enumerated exercise or requirement list, not a heading
                    head, consumed = None, 1
                elif "." not in number and number.isdigit():
                    # A BARE integer has to be monotonic AT THIS POSITION, not
                    # merely a number the document uses somewhere.
                    #
                    # Checking the allowed SET alone was per-number, so once
                    # clause 3 legitimately existed every later stray "3"
                    # passed too. NORSOK's A.1 table reads "Minimum number of
                    # coats:" / "3" / "MDFT of complete coating system: 60
                    # 280", and that 3 - the coat count - was read as clause
                    # 3. It mislabelled the chunk AND split the parent group,
                    # so small-to-big could not rejoin the table with its own
                    # figures and the answer stopped one line short of them.
                    if int(number) <= last_bare_integer:
                        head, consumed = None, 1
                    else:
                        last_bare_integer = int(number)

            if head and (_obliges(head) or numbered_requirement or (
                    "." in _heading_number(head)
                    and _continues_as_sentence(lines, i + consumed))):
                # A numbered requirement: its number is the clause, as
                # `_numbered_paragraph` makes it, and its sentence stays in the
                # text to be read as the requirement it is. A "title" whose
                # text carries on in lower case on the next line is the first
                # line of such a requirement too ("4.2.1 Stud bolts for
                # flanges" / "shall be ASTM A193 ...").
                flush_prose(section)
                settle_heading()
                if not contents_page:
                    section = _heading_number(head)
                buf.extend(lines[i:i + consumed])
                i += consumed
                continue

            if head:
                flush_prose(section)
                settle_heading()
                if contents_page:
                    # A contents page sets no heading state, but its lines are
                    # still text: they used to be consumed here and kept
                    # nowhere (backlog item 3, the chapter-opener list).
                    buf.extend(lines[i:i + consumed])
                else:
                    # heading state persists across pages until the next heading
                    section = head
                    pending_heading = (lines[i:i + consumed], page_no, head)
                    pending_mark = len(blocks)
                i += consumed
                continue

            run = _table_run_length(lines, i, stop=heading_stops_table)
            if run:
                flush_prose(section)
                body = "\n".join(lines[i:i + run]).strip()
                if body:
                    body = "\n".join([*take_carry(), body])
                    blocks.append(Block("table", body, page_no, page_no, section))
                i += run
                continue

            buf.append(line)
            i += 1

        flush_prose(section)

    settle_heading()
    if carry:
        blocks.append(Block("prose", "\n".join(take_carry()), carry_at[0], carry_at[0],
                            carry_at[1]))
    return blocks, removed_total


# --------------------------------------------------------------- chunking


def split_oversized(
    text: str, page_start: int, page_end: int, section: str | None, kind: str
) -> list[Block]:
    """Token-window a block that cannot fit, with overlap. Never truncate."""
    tok = get_tokenizer()
    ids = tok.encode(text, add_special_tokens=False).ids
    out: list[Block] = []
    step = max(1, settings.chunk_max_tokens - settings.chunk_overlap_tokens)
    for start in range(0, len(ids), step):
        window = ids[start:start + settings.chunk_max_tokens]
        if not window:
            break
        piece = tok.decode(window).strip()
        if piece:
            # decode -> encode is NOT the identity (notably on maths text), so
            # the window length is not the real token count. Measure the text.
            out.append(
                Block(kind, piece, page_start, page_end, section, count_tokens(piece))
            )
        if start + settings.chunk_max_tokens >= len(ids):
            break
    return out


#: A sentence ends at . ! or ? followed by space and a character that can
#: START a sentence. A lower-case letter after the stop means an abbreviation
#: ("e.g. the", "approx. twice") - splitting there started a chunk mid-sentence.
#: ";" and ":" no longer end a unit: a chunk that opened after "as follows:"
#: began in lower case (35% of the owner's chunks started that way). They are
#: still used to break a single sentence too long to fit - see _clause_units.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"'\u201d\u2019)\]]*\s+(?=[^a-z\s])")
_CLAUSE_SPLIT = re.compile(r"(?<=[;:,])\s+")
_ENDS_SENTENCE = re.compile(r"[.!?;:][\"'\u201d\u2019)\]]*\s*$")

#: A word broken at a line end: "galvan-" / "ized". Lower case on both sides
#: only: "Carbon-" / "Steel" or "API-" / "5L" are left exactly as written.
_LINE_HYPHEN = re.compile(r"([A-Za-z]*[a-z])-[ \t]*\n[ \t]*([a-z][a-z]*)")
#: Endings that are never words on their own, so "tempera-" + "ture" is one
#: word. Deliberately short: anything else keeps its hyphen (only the line
#: break is removed), because "carbon-" + "steel" is a real compound and
#: guessing wrong would change a term an engineer searches for.
_WORD_ENDINGS = frozenset("""
    tion tions sion sions ment ments ture tures ized ised izing ising ization
    isation ing ings ed ly ness ance ances ence ences ity ities ous ious able
    ible ical ically ive ives ative ation ations ure ures ist ists ism ant ants
    ent ents ary ory ery ages ful less ward wards ium ic ics ule ules ial ially
    tive tively ular ularly ural ated ating ator ators ately ment ely ery
""".split())


def _join_hyphenated(left: str, right: str, vocab: frozenset[str] | None) -> str:
    """"galvan" + "ized" -> "galvanized"; "carbon" + "steel" -> "carbon-steel".

    Evidence first: the document's own spelling, when it prints either form
    unbroken elsewhere. Otherwise only a fragment that cannot stand alone as
    a word (a suffix) is joined; everything else keeps the hyphen.
    """
    joined = left + right
    if vocab:
        if f"{left}-{right}".lower() in vocab:
            return f"{left}-{right}"
        if joined.lower() in vocab:
            return joined
    if right.lower() in _WORD_ENDINGS:
        return joined
    return f"{left}-{right}"


def dehyphenate(text: str, vocab: frozenset[str] | None = None) -> str:
    """Repair words hyphenated at a line break (AUDIT F10). Conservative: see
    _join_hyphenated. Only line-break hyphens are touched."""
    return _LINE_HYPHEN.sub(lambda m: _join_hyphenated(m.group(1), m.group(2), vocab), text)


def document_vocabulary(pages: list[tuple[int, str]]) -> frozenset[str]:
    """Every word (and hyphenated compound) a document prints unbroken - the
    evidence dehyphenate consults before guessing."""
    words: set[str] = set()
    for _, text in pages:
        for token in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", text):
            if len(token) >= 4:
                words.add(token.lower())
    return frozenset(words)


def sentences(text: str, vocab: frozenset[str] | None = None) -> list[str]:
    """Split prose into sentences, collapsing PDF line-wrap newlines.

    A PDF wraps mid-sentence, so the raw text is full of newlines that are
    layout, not meaning. Collapsing them makes a retrieved passage readable
    when it is quoted back to the user verbatim. Table blocks are handled
    separately and keep their line structure. Words hyphenated at a line
    break are rejoined first (see dehyphenate).
    """
    text = dehyphenate(text, vocab)
    parts = [_WS.sub(" ", p).strip() for p in _SENTENCE_SPLIT.split(text)]
    parts = [p for p in parts if p]
    if parts:
        return parts
    collapsed = _WS.sub(" ", text).strip()
    return [collapsed] if collapsed else []


def _ends_sentence(text: str) -> bool:
    return bool(_ENDS_SENTENCE.search(text))


def _join_across(left: str, right: str, vocab: frozenset[str] | None) -> str:
    """Join the end of one block to the start of the next (a page break)."""
    m = re.search(r"([A-Za-z]*[a-z])-$", left)
    n = re.match(r"([a-z]+)", right)
    if m and n:
        return (left[:m.start()] + _join_hyphenated(m.group(1), n.group(1), vocab)
                + right[n.end():])
    return f"{left} {right}"


def _clause_units(sentence: str, limit: int) -> list[str]:
    """A sentence longer than `limit` tokens, broken at ; : or , into pieces
    that fit - before the token-window fallback, which cuts mid-word."""
    pieces = [p for p in _CLAUSE_SPLIT.split(sentence) if p]
    out: list[str] = []
    cur = ""
    for piece in pieces:
        candidate = f"{cur} {piece}".strip()
        if cur and count_tokens(candidate) > limit:
            out.append(cur)
            cur = piece
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _split_structured(b: Block, target: int, ceiling: int) -> list[Block]:
    """A table or data-sheet block, split ON ROW BOUNDARIES with its caption
    and header repeated at the top of every piece. Pieces are balanced so the
    last is not a runt, and each carries the pages ITS rows came from."""
    lead = list(b.lead or [])
    rows = list(b.rows or [])
    pages = list(b.row_pages or [b.page_start] * len(rows))
    lead_tokens = count_tokens("\n".join(lead)) if lead else 0
    row_tokens = [count_tokens(r) + 1 for r in rows]
    budget = max(1, target - lead_tokens)
    total = sum(row_tokens)
    pieces = max(1, -(-total // budget))
    out: list[Block] = []

    def emit(idx: list[int]) -> None:
        text = "\n".join(lead + [rows[k] for k in idx])
        tokens = count_tokens(text)
        ps = min(pages[k] for k in idx)
        pe = max(pages[k] for k in idx)
        if tokens <= ceiling:
            out.append(Block(b.kind, text, ps, pe, b.section, tokens, lead=lead,
                             rows=[rows[k] for k in idx],
                             row_pages=[pages[k] for k in idx], header=b.header))
        else:
            # a single row longer than the ceiling: windowed, never dropped
            out.extend(split_oversized(text, ps, pe, b.section, b.kind))

    # Each row goes to the piece its token midpoint falls in, so there are
    # exactly `pieces` pieces of near-equal size - no runt left at the end.
    groups: list[list[int]] = [[] for _ in range(pieces)]
    before = 0
    for k, t in enumerate(row_tokens):
        groups[min(pieces - 1, int((before + t / 2) * pieces / max(total, 1)))].append(k)
        before += t
    for group in groups:
        # a piece can only overflow the ceiling through one enormous row;
        # re-cut greedily by the ceiling in that case
        cur: list[int] = []
        acc = 0
        for k in group:
            if cur and lead_tokens + acc + row_tokens[k] > ceiling:
                emit(cur)
                cur, acc = [], 0
            cur.append(k)
            acc += row_tokens[k]
        if cur:
            emit(cur)
    return out


def build_chunks(blocks: list[Block], vocab: frozenset[str] | None = None) -> list[Block]:
    """Accumulate blocks into ~target-token chunks on sentence boundaries."""
    target = settings.chunk_target_tokens
    ceiling = settings.chunk_max_tokens
    overlap = settings.chunk_overlap_tokens

    chunks: list[Block] = []
    cur: list[tuple[str, int, int, int]] = []  # (text, tokens, page_start, page_end)
    cur_tokens = 0
    cur_section: str | None = None
    #: The unfinished last sentence of the previous prose block, held back
    #: because the next block continues it: a sentence running over a page
    #: break used to become two chunks' worth of fragments - the second half
    #: starting a chunk in lower case.
    pending: tuple[str, int, int] | None = None

    def flush() -> None:
        nonlocal cur, cur_tokens
        if not cur:
            return
        # Sentences join with a space: a prose chunk is quoted back to the user
        # verbatim in the Tier 1 answer, so it must read as prose.
        text = " ".join(t for t, _, _, _ in cur).strip()
        if text:
            chunks.append(
                Block(
                    "prose",
                    text,
                    min(c[2] for c in cur),
                    max(c[3] for c in cur),
                    cur_section,
                    cur_tokens,
                )
            )
        cur = []
        cur_tokens = 0

    def add_unit(sent: str, page_start: int, page_end: int, section: str | None) -> None:
        nonlocal cur, cur_tokens
        st = count_tokens(sent)
        if st > ceiling:
            pieces = _clause_units(sent, target)
            if len(pieces) > 1:
                for piece in pieces:
                    add_unit(piece, page_start, page_end, section)
                return
            flush()
            chunks.extend(split_oversized(sent, page_start, page_end, section, "prose"))
            return
        if cur_tokens + st > target and cur:
            # Carry the trailing sentences forward as overlap, but never
            # more than the overlap budget allows. Text without sentence
            # terminators (a symbol-font table extracts as one enormous
            # "sentence") would otherwise carry the ENTIRE previous chunk
            # forward, making it a strict substring of the next one -
            # duplication, not overlap.
            tail: list[tuple[str, int, int, int]] = []
            acc = 0
            for item in reversed(cur):
                if acc >= overlap:
                    break
                if acc + item[1] > overlap * _MAX_OVERLAP_FACTOR:
                    break
                tail.insert(0, item)
                acc += item[1]
            flush()
            cur = list(tail)
            cur_tokens = sum(t for _, t, _, _ in cur)
        cur.append((sent, st, page_start, page_end))
        cur_tokens += st

    def release_pending() -> None:
        nonlocal pending
        if pending is not None:
            add_unit(pending[0], pending[1], pending[2], cur_section)
            pending = None

    for index, b in enumerate(blocks):
        b.tokens = count_tokens(b.text)

        if b.rows is not None:
            # A STRUCTURED table or data sheet: always a table, however
            # small, split on row boundaries with its header repeated.
            release_pending()
            flush()
            chunks.extend(_split_structured(b, target, ceiling))
            cur_section = b.section
            continue

        # a table stays whole when it fits; otherwise it is windowed, not dropped
        if b.kind == "table" and b.tokens < _MIN_TABLE_TOKENS:
            # too small to be a useful standalone chunk - treat it as prose
            b.kind = "prose"

        if b.kind not in ("prose", "table"):
            # toc / frontmatter / index / references: keep as its own chunk so
            # it can be inspected, but never blend it into retrievable prose.
            release_pending()
            flush()
            if b.tokens <= ceiling:
                chunks.append(Block(b.kind, b.text, b.page_start, b.page_end, None, b.tokens))
            else:
                chunks.extend(split_oversized(b.text, b.page_start, b.page_end, None, b.kind))
            continue

        if b.kind == "table":
            release_pending()
            flush()
            if b.tokens <= ceiling:
                chunks.append(
                    Block("table", b.text, b.page_start, b.page_end, b.section, b.tokens)
                )
            else:
                chunks.extend(
                    split_oversized(b.text, b.page_start, b.page_end, b.section, "table")
                )
            cur_section = b.section
            continue

        if b.section != cur_section:
            release_pending()
            flush()
            cur_section = b.section

        if b.tokens > ceiling and not _SENTENCE_SPLIT.search(b.text) \
                and not _CLAUSE_SPLIT.search(b.text):
            release_pending()
            flush()
            chunks.extend(
                split_oversized(b.text, b.page_start, b.page_end, b.section, "prose")
            )
            continue

        units = [(sent, b.page_start, b.page_end) for sent in sentences(b.text, vocab)]
        if pending is not None:
            if units:
                first = units[0]
                units[0] = (_join_across(pending[0], first[0], vocab), pending[1], first[2])
            else:
                units = [pending]
            pending = None
        nxt = blocks[index + 1] if index + 1 < len(blocks) else None
        if (units and not _ends_sentence(units[-1][0]) and nxt is not None
                and nxt.kind == "prose" and nxt.rows is None
                and nxt.section == b.section):
            pending = units.pop()
        for sent, page_start, page_end in units:
            add_unit(sent, page_start, page_end, b.section)

    release_pending()
    flush()
    # Ceiling enforcement first: splitting an oversized chunk can itself emit a
    # tiny trailing piece, so runt-merging has to run after it, not before.
    return _merge_runts(_enforce_ceiling([c for c in chunks if c.text.strip()]))


def _heading_prefix_length(text: str) -> int:
    """How many leading words belong to a heading that must not be split off.

    Returns 0 when the text does not begin with a heading.
    """
    lines = text.splitlines()
    if not lines:
        return 0
    first = lines[0].strip()
    head = looks_like_heading(first)
    if head is None and len(lines) > 1:
        head, consumed = _split_line_heading([line.strip() for line in lines], 0)
        if head:
            return len(" ".join(lines[:consumed]).split())
        return 0
    return len(first.split()) if head else 0


def _enforce_ceiling(chunks: list[Block]) -> list[Block]:
    """Final invariant: no chunk may exceed the ceiling, whatever produced it.

    Token-window splitting cannot guarantee this on its own because decoding a
    window and re-encoding the resulting text does not round-trip exactly. This
    pass measures the real text and splits on whitespace until every chunk fits,
    so e5-small can never silently truncate one.
    """
    ceiling = settings.chunk_max_tokens
    out: list[Block] = []
    for c in chunks:
        if c.tokens <= ceiling:
            out.append(c)
            continue
        # Only the rare oversized chunk reaches here, so measure exactly rather
        # than sampling - an approximate check is what let a 499-token chunk
        # through in the first place.
        # A heading must never be split from the block it introduces. Splitting
        # "A.5.1 Coating system no." from "5A (shall be pre-qualified)" left a
        # chunk starting mid-heading, which is unreadable as a citation and
        # unfindable by the clause it belongs to.
        words = c.text.split()
        protected = _heading_prefix_length(c.text)

        cur: list[str] = []
        for index, w in enumerate(words):
            cur.append(w)
            if index < protected:
                continue
            if count_tokens(" ".join(cur)) > ceiling:
                cur.pop()
                piece = " ".join(cur).strip()
                if piece:
                    out.append(
                        Block(c.kind, piece, c.page_start, c.page_end, c.section,
                              count_tokens(piece))
                    )
                cur = [w]
        piece = " ".join(cur).strip()
        if piece:
            out.append(
                Block(c.kind, piece, c.page_start, c.page_end, c.section,
                      count_tokens(piece))
            )
    return out


def _merge_runts(chunks: list[Block]) -> list[Block]:
    """Fold tiny chunks into a neighbour so no chunk is too small to retrieve.

    A 2-token chunk can never answer anything, but it can still win a search
    slot. Merge it into the previous chunk when they share a section and the
    result still fits; otherwise drop it if it carries no real content.
    """
    ceiling = settings.chunk_max_tokens
    out: list[Block] = []
    for c in chunks:
        if (
            c.tokens < _MIN_CHUNK_TOKENS
            and out
            and c.rows is None
            and out[-1].rows is None
            and out[-1].section == c.section
            and out[-1].kind == c.kind
            and out[-1].tokens + c.tokens <= ceiling
        ):
            prev = out[-1]
            merged = prev.text + "\n" + c.text
            merged_tokens = count_tokens(merged)
            if merged_tokens <= ceiling:
                prev.text = merged
                prev.tokens = merged_tokens
                prev.page_end = max(prev.page_end, c.page_end)
                prev.page_start = min(prev.page_start, c.page_start)
                continue
        if (
            c.kind in RETRIEVABLE_KINDS
            and c.rows is None
            and c.tokens < 5
            and not re.search(r"[A-Za-z]{3}", c.text)
        ):
            continue  # punctuation or a stray number - no retrievable content
        out.append(c)

    # Second pass: a runt at the START of a section cannot merge backwards, but
    # it belongs with what follows. Merge it forward instead of publishing a
    # chunk too small to answer anything.
    merged: list[Block] = []
    i = 0
    while i < len(out):
        c = out[i]
        nxt = out[i + 1] if i + 1 < len(out) else None
        if (
            c.tokens < _MIN_CHUNK_TOKENS
            and nxt is not None
            and c.rows is None
            and nxt.rows is None
            and nxt.section == c.section
            and nxt.kind == c.kind
        ):
            text = c.text + "\n" + nxt.text
            tokens = count_tokens(text)
            if tokens <= ceiling:
                merged.append(
                    Block(c.kind, text, min(c.page_start, nxt.page_start),
                          max(c.page_end, nxt.page_end), c.section, tokens)
                )
                i += 2
                continue
        merged.append(c)
        i += 1
    return merged


# --------------------------------------------------------------- persistence


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(doc_sha: str, page_start: int, ordinal: int, chash: str) -> str:
    """Deterministic: document hash + page + ordinal + content hash.

    A retry therefore REPLACES the same row rather than inserting a duplicate.
    """
    return f"{doc_sha[:12]}:p{page_start:05d}:c{ordinal:05d}:{chash[:8]}"


#: Bump when chunking behaviour changes, so a re-run rebuilds rather than
#: short-circuiting on stale output.
#:
#: 5 (2026-09-27, chunking-quality): ruled tables from `pages.tables_json`
#: as structured table chunks; data-sheet "Label : value" rows as data;
#: running lines by page-number evidence; numbering gaps accepted; long
#: numbered requirements keep their clause; sentences joined across page
#: breaks; line-break hyphens repaired; runts merged below 40 tokens;
#: duplicate chunks in one section kept once for search.
CHUNKER_VERSION = "6"


def _chunk_signature(doc_sha: str, pages: list[tuple[int, str]],
                     page_tables: dict[int, str] | None = None) -> str:
    """Identifies the input to chunking: the document, its extracted text, its
    extracted tables, and the chunker version. Unchanged signature means the
    output would be identical, so the work can be skipped."""
    h = hashlib.sha256()
    h.update(doc_sha.encode())
    h.update(CHUNKER_VERSION.encode())
    h.update(str(len(pages)).encode())
    tables = page_tables or {}
    for pno, text in pages:
        h.update(str(pno).encode())
        h.update(hashlib.sha256(text.encode("utf-8")).digest())
        if tables.get(pno):
            h.update(b"tables")
            h.update(hashlib.sha256(tables[pno].encode("utf-8")).digest())
    return h.hexdigest()


def is_stale(conn, doc_id: str) -> bool:
    """Whether a document's chunks were built by an older chunker or from
    older extracted input - the question a re-index asks per document."""
    doc = conn.execute("SELECT sha256, chunk_signature FROM documents WHERE id = ?",
                       (doc_id,)).fetchone()
    if doc is None:
        return False
    pages, raw_tables, _ = _load_pages(conn, doc_id)
    if not pages:
        return False
    return doc["chunk_signature"] != _chunk_signature(doc["sha256"], pages, raw_tables)


def _load_pages(conn, doc_id: str):
    """(pages, raw tables json by page, rows) - the one place pages are read.

    Recognised text overrides the empty extraction that triggered it, and a
    recognised page has no extracted tables: the geometry belongs to the
    extracted text, whose line numbers it addresses."""
    has_tables = "tables_json" in {r["name"] for r in conn.execute(
        "PRAGMA table_info(pages)")}
    page_rows = conn.execute(
        f"""SELECT p.page_no,
                  COALESCE(NULLIF(o.text, ''), p.text) AS text,
                  CASE WHEN o.page_no IS NULL OR o.text = '' THEN 0 ELSE 1 END
                      AS recognised,
                  o.min_conf AS min_conf,
                  o.alphabet_violations AS viol,
                  o.alphabet_sample AS viol_sample,
                  {"p.tables_json" if has_tables else "NULL"} AS tables_json
           FROM pages p
           LEFT JOIN page_ocr o
             ON o.document_id = p.document_id AND o.page_no = p.page_no
           WHERE p.document_id = ? ORDER BY p.page_no""",
        (doc_id,),
    ).fetchall()
    pages = [(r["page_no"], r["text"]) for r in page_rows]
    raw_tables = {r["page_no"]: r["tables_json"] for r in page_rows
                  if r["tables_json"] and not r["recognised"]}
    return pages, raw_tables, page_rows


def _decode_tables(raw_tables: dict[int, str]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for pno, raw in raw_tables.items():
        try:
            out[pno] = list(json.loads(raw).get("tables") or [])
        except (ValueError, AttributeError):
            continue  # an unreadable record is no tables, never a failure
    return out


def duplicate_of(chunks: list[Block]) -> dict[int, int]:
    """{ordinal: ordinal of the first identical chunk} within one document.

    Identical means same kind, same section AND same text. Two clauses that
    say the same thing are two citations and both stay searchable; the same
    text under the same clause twice (a repeated note, a reprinted table
    piece) is one passage, and a second copy only takes a search slot from a
    different answer. The copy is KEPT - not retrievable, recorded in the
    exclusion ledger with the ordinal it duplicates - so its page is still a
    page that produced a chunk and still citable.
    """
    first: dict[tuple, int] = {}
    dups: dict[int, int] = {}
    for ordinal, c in enumerate(chunks):
        if c.kind not in RETRIEVABLE_KINDS:
            continue
        key = (c.kind, c.section, c.text)
        if key in first:
            dups[ordinal] = first[key]
        else:
            first[key] = ordinal
    return dups


def chunk_provenance(page_start: int, page_end: int, recognised: set[int],
                     conf: dict, viol: dict | None = None
                     ) -> tuple[str, float | None, int, str | None]:
    """('extracted'|'recognised', min confidence) for one chunk's page span.

    A chunk spanning one recognised page and one extracted page is
    RECOGNISED. The reader cannot tell which sentence came from where, so the
    label makes the weaker claim - under-claiming costs a little confidence,
    over-claiming is the failure this system exists to prevent. The minimum
    confidence governs, because the weakest evidence in the chunk is what the
    reader is exposed to. See ADR-0006.

    Module level so a test can exercise THIS function rather than a copy of
    its logic - a test that reimplements the rule cannot fail when the rule
    changes.
    """
    spanned = [p for p in range(page_start, page_end + 1) if p in recognised]
    if not spanned:
        return ("extracted", None, 0, None)
    scores = [conf[p] for p in spanned if conf.get(p) is not None]
    viol = viol or {}
    n = sum(viol.get(p, (0, ""))[0] for p in spanned)
    sample = "".join(sorted({c for p in spanned for c in viol.get(p, (0, ""))[1]}))[:20]
    return ("recognised", min(scores) if scores else None, n, sample or None)


def chunk_document(doc_id: str, force: bool = False,
                   acknowledge_orphaned_findings: bool = False) -> dict:
    """Chunk one extracted document. Idempotent - re-running replaces rows.

    B38: replacing the chunks CASCADES into `standard_requirements` (its
    `chunk_id` is ON DELETE CASCADE), so a re-chunk that would take requirement
    rows review findings cite is RECORDED and REFUSED unless
    `acknowledge_orphaned_findings` - see `orphan_guard`."""
    timer = Timer()
    conn = connect()
    keyword.ensure_schema(conn)
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError(f"unknown document {doc_id}")

    # Recognised text overrides the empty extraction that triggered it. The
    # resolution is explicit rather than a column read, because page_ocr is a
    # separate table precisely so extraction cannot destroy it - see ADR-0006.
    # Anything reading pages.text directly will silently ignore recognised
    # text, which is why this is the one place pages are loaded.
    pages, raw_tables, page_rows = _load_pages(conn, doc_id)
    recognised_pages = {r["page_no"] for r in page_rows if r["recognised"]}
    page_conf = {r["page_no"]: r["min_conf"] for r in page_rows if r["recognised"]}
    page_viol = {r["page_no"]: (r["viol"] or 0, r["viol_sample"] or "")
                 for r in page_rows if r["recognised"]}
    if not pages:
        raise ValueError(f"{doc_id} has no extracted pages - run extraction first")

    total_pages = doc["page_count"] or len(pages)
    page_kinds = {pno: classify_page(text, pno, total_pages) for pno, text in pages}
    signature = _chunk_signature(doc["sha256"], pages, raw_tables)
    existing = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    if not force and existing and doc["chunk_signature"] == signature:
        # Nothing about the input changed, so rebuilding would produce the
        # same rows. /extract resumes rather than redoing work; this matches.
        #
        # The state must still advance. Returning early without moving the
        # document on left it at 'chunking' forever, and the ingestion state
        # loop revisited it until its guard tripped.
        if doc["status"] == states.CHUNKING:
            with conn:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (states.INDEXING_KEYWORD, doc_id),
                )
        return {
            "document_id": doc_id,
            "filename": doc["filename"],
            "pages": len(pages),
            "chunks": existing,
            "chunks_retrievable": doc["chunk_count"],
            "chunks_this_run": 0,
            "skipped": True,
            "reason": "unchanged since last chunking",
            "seconds": timer.seconds(),
            "chunks_per_sec": None,
        }

    running = detect_running_lines(pages)
    # Ruled tables replace their own lines with one structured stand-in
    # BEFORE segmentation, so no cell is read as a heading, stripped as a
    # running line, or published twice (as the table and as shredded prose).
    masked = mask_tables(pages, _decode_tables(raw_tables), running)
    blocks, removed = segment_document(masked, running, page_kinds)
    chunks = build_chunks(blocks, document_vocabulary(pages))

    ceiling = settings.chunk_max_tokens
    over = [c for c in chunks if c.tokens > ceiling]
    assert not over, (
        f"{len(over)} chunk(s) exceed the {ceiling}-token ceiling "
        f"(max {max(c.tokens for c in over) if over else 0}) - e5-small would truncate them"
    )

    # A chunk is retrievable only if its kind is searchable AND its text reads
    # like language. The quality gate is the safety net for failure modes no
    # structural detector anticipated.
    quality = {id(c): assess(c.text, c.kind) for c in chunks}
    kind_counts: Counter[str] = Counter(c.kind for c in chunks)
    quality_rejected = [
        c for c in chunks
        if c.kind in RETRIEVABLE_KINDS and not quality[id(c)]["ok"]
    ]
    duplicates = duplicate_of(chunks)
    retrievable = [
        c for ordinal, c in enumerate(chunks)
        if c.kind in RETRIEVABLE_KINDS and quality[id(c)]["ok"]
        and ordinal not in duplicates
    ]

    # A parent id per contiguous run of chunks sharing a section and kind.
    # build_chunks accumulates ACROSS source blocks - one chunk can span
    # several blocks and one block several chunks - so a single block id is
    # not well defined here. What is well defined, and what the reader
    # actually needs, is the run of chunks that belong to the same clause:
    # NORSOK's A.1 is a table chunk followed by its notes chunk, and quoting
    # only one of them answers with the notes and leaves the figure behind.
    parents: list[str] = []
    group = 0
    for i, c in enumerate(chunks):
        if i and (c.section != chunks[i - 1].section or c.kind != chunks[i - 1].kind):
            group += 1
        parents.append(f"{doc['sha256'][:12]}:g{group:05d}")

    rows = []
    for ordinal, c in enumerate(chunks):
        chash = content_hash(c.text)
        q = quality[id(c)]
        rows.append(
            (
                chunk_id(doc["sha256"], c.page_start, ordinal, chash),
                doc_id,
                doc["filename"],
                ordinal,
                c.page_start,
                c.page_end,
                c.section,
                parents[ordinal],
                c.kind,
                c.text,
                c.tokens,
                chash,
                int(c.kind in RETRIEVABLE_KINDS and q["ok"] and ordinal not in duplicates),
                (",".join(q["reasons"])
                 or (f"duplicate_of={duplicates[ordinal]}" if ordinal in duplicates
                     else None)),
                *chunk_provenance(c.page_start, c.page_end, recognised_pages,
                                  page_conf, page_viol),
            )
        )

    # ------------------------------------------------------------------
    # Exclusion ledger. Nothing is ever dropped silently: every page and
    # every chunk that search cannot see is recorded with the rule that
    # excluded it and the text that was dropped, queryable via
    # GET /api/documents/{id}/excluded.
    # ------------------------------------------------------------------
    now = _now_iso()
    exclusion_rows = []

    # Which pages actually contributed a chunk. Any page that did not must be
    # accounted for below - "nothing is dropped silently" is the promise
    # /excluded exists to keep, and a page that quietly yields nothing is
    # exactly the case that promise is about.
    pages_with_chunks: set[int] = set()
    for c in chunks:
        for pno in range(c.page_start, c.page_end + 1):
            pages_with_chunks.add(pno)

    ocr_pages = {
        r["page_no"]
        for r in conn.execute(
            "SELECT page_no FROM pages WHERE document_id = ? AND needs_ocr = 1",
            (doc_id,),
        )
    }
    # What recognition actually did to each flagged page, so the exclusion
    # ledger can tell "not run yet" from "ran and the page is blank" from
    # "ran and failed". Conflating those is the defect the old single rule had.
    ocr_results = {
        r["page_no"]: {"box_count": r["box_count"], "char_count": r["char_count"],
                       "error": r["error"]}
        for r in conn.execute(
            "SELECT page_no, box_count, char_count, error FROM page_ocr WHERE document_id = ?",
            (doc_id,),
        )
    }

    def dropped_real_content(text: str, rule: str) -> int:
        """Does this dropped page look like body text rather than furniture?

        Uses the SAME predicate as the classifier gate in classify_page, so
        the two cannot drift: clause headings plus real prose is body text. A
        contents or index page is exempt, because it legitimately consists of
        heading-like lines and would otherwise fire on every book.

        This should always be zero. If it is not, a page like NORSOK 11 - the
        whole of Clause 8, dropped as front matter - has happened again.
        """
        if rule.endswith(("_toc", "_index")):
            return 0
        # A references page legitimately carries its own numbered heading -
        # "9.15 References" - followed by bibliography entries long enough to
        # read as prose. The alert fired on exactly that in book4, which is a
        # false positive: the page is correctly excluded and nothing was lost.
        # Left alone it would fire on every chapter of every textbook, and an
        # alert that fires on the normal case stops being read.
        if rule.endswith("_references") and _only_reference_headings(text):
            return 0
        if count_clause_headings(text) >= 1 and longest_clause(text) >= MIN_CLAUSE_WORDS:
            return 1
        return 0

    for pno, ptext in pages:
        kind = page_kinds.get(pno, "prose")
        # text_length uses the SAME definition as pages.char_count, so the two
        # endpoints cannot disagree by a trailing newline.
        length = len(ptext.strip())

        if kind not in RETRIEVABLE_KINDS:
            rule = f"page_classified_{kind}"
            exclusion_rows.append(
                (doc_id, "page", pno, pno, None, rule,
                 f"page classified as {kind}", ptext[:2000], length, now,
                 dropped_real_content(ptext, rule))
            )
            continue

        if pno in pages_with_chunks:
            continue

        # The page survived classification but produced no chunk at all.
        if pno in ocr_pages:
            # Four rules, each describing the PAGE rather than the system. The
            # old single rule asserted "OCR is not implemented", which is a
            # property of the build and goes false the day it ships.
            rec = ocr_results.get(pno)
            if rec is None:
                rule = "ocr_not_run"
                reason = ("scanned page with no extractable text; recognition "
                          "has not run")
            elif rec["error"]:
                rule = "ocr_failed"
                reason = f"recognition failed on this page: {rec['error']}"
            elif rec["box_count"] == 0:
                # Measured: 5 of 12 flagged pages return zero boxes at both 150
                # and 300 dpi. Those pages are BLANK, not unreadable, and
                # calling them unreadable puts a false accusation in the ledger.
                rule = "ocr_found_no_text"
                reason = ("scanned page; recognition ran and found no text - "
                          "the page appears to be blank")
            else:
                rule = "ocr_yielded_no_chunk"
                reason = (
                    f"recognition read {rec['char_count']} characters from this "
                    "scanned page but they produced no chunk"
                )
        elif length == 0:
            reason = "page contained no text after normalisation"
            rule = "page_empty"
        else:
            reason = (
                f"page held {length} characters but produced no chunk - too "
                "short or too fragmented to form one"
            )
            rule = "page_yielded_no_chunk"
        exclusion_rows.append(
            (doc_id, "page", pno, pno, None, rule, reason, ptext[:2000], length,
             now, dropped_real_content(ptext, rule))
        )
    for ordinal, c in enumerate(chunks):
        q = quality[id(c)]
        if c.kind in RETRIEVABLE_KINDS and not q["ok"]:
            exclusion_rows.append(
                (doc_id, "chunk", c.page_start, c.page_end,
                 chunk_id(doc["sha256"], c.page_start, ordinal, content_hash(c.text)),
                 "content_quality_gate", ",".join(q["reasons"]),
                 c.text[:2000], len(c.text.strip()), now, 0)
            )
        elif ordinal in duplicates:
            first = chunks[duplicates[ordinal]]
            exclusion_rows.append(
                (doc_id, "chunk", c.page_start, c.page_end,
                 chunk_id(doc["sha256"], c.page_start, ordinal, content_hash(c.text)),
                 "duplicate_chunk",
                 f"identical to chunk {duplicates[ordinal]} (pages "
                 f"{first.page_start}-{first.page_end}) in the same section",
                 c.text[:2000], len(c.text.strip()), now, 0)
            )

    orphan_guard.check(
        "re_chunk",
        requirement_where="chunk_id IN (SELECT id FROM chunks WHERE document_id = ?)",
        params=(doc_id,), document_id=doc_id,
        acknowledge=acknowledge_orphaned_findings)
    with conn:
        conn.execute("DELETE FROM exclusions WHERE document_id = ?", (doc_id,))
        conn.executemany(
            """INSERT INTO exclusions
               (document_id, scope, page_start, page_end, chunk_id, rule,
                reason, text_sample, text_length, created_at, clause_headings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            exclusion_rows,
        )
        # The keyword index is keyed on chunk ids, so a rebuild invalidates
        # it. Dropped here and rebuilt by the indexing stage.
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        # Vectors are keyed on chunk id. Re-chunking changes those ids, so any
        # vector whose chunk no longer exists is an orphan - and embedded_count
        # counts vector ROWS, so leaving them made progress read above 100%
        # (1448 embedded against 1356 chunks). Same failure as every other
        # count derived from something adjacent to the thing it claims.
        conn.execute(
            """DELETE FROM chunk_vectors WHERE document_id = ?
               AND chunk_id NOT IN (SELECT id FROM chunks WHERE document_id = ?)""",
            (doc_id, doc_id),
        )
        conn.executemany(
            """INSERT OR REPLACE INTO chunks
               (id, document_id, filename, ordinal, page_start, page_end,
                section, parent_id, kind, text, token_count, content_hash,
                retrievable, quality_flags, text_source, ocr_min_conf,
                ocr_alphabet_violations, ocr_alphabet_sample)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        # chunk_count is the RETRIEVABLE count - what search can actually see.
        # chunk_count_total is every row, including the ones kept only for
        # inspection. The two differ and both are reported.
        conn.execute(
            "UPDATE documents SET chunk_count = ?, chunk_count_total = ?,"
            " chunk_signature = ?, status = ? WHERE id = ?",
            (len(retrievable), len(chunks), signature, states.INDEXING_KEYWORD, doc_id),
        )

    elapsed = timer.seconds()
    toks = sorted(c.tokens for c in retrievable)
    spanning = sum(1 for c in chunks if c.page_end > c.page_start)
    return {
        "document_id": doc_id,
        "filename": doc["filename"],
        "pages": len(pages),
        "chunks": len(chunks),
        "chunks_retrievable": len(retrievable),
        "chunks_non_retrievable": len(chunks) - len(retrievable),
        "chunks_by_kind": dict(kind_counts),
        "chunks_rejected_by_quality_gate": len(quality_rejected),
        "chunks_duplicate": len(duplicates),
        "pages_excluded": sum(1 for r in exclusion_rows if r[1] == "page"),
        "exclusions_recorded": len(exclusion_rows),
        "chunks_this_run": len(chunks),
        "skipped": False,
        "chunks_per_page": round(len(chunks) / len(pages), 2) if pages else None,
        "tables_kept_whole": sum(1 for c in chunks if c.kind == "table"),
        "chunks_spanning_pages": spanning,
        "running_lines_detected": len(running),
        "running_lines_removed": removed,
        "token_min": toks[0] if toks else None,
        "token_median": toks[len(toks) // 2] if toks else None,
        "token_max": toks[-1] if toks else None,
        "token_ceiling": ceiling,
        "seconds": elapsed,
        "chunks_per_sec": rate(len(chunks), elapsed),
    }
