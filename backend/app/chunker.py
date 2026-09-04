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
import re
from datetime import datetime, timezone
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from tokenizers import Tokenizer

from .config import settings
from .db import connect
from .rates import Timer, rate
from . import states
from . import keyword
from .quality import MIN_CLAUSE_WORDS, assess, longest_clause, looks_like_table

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


def detect_running_lines(pages: list[tuple[int, str]]) -> set[str]:
    """Normalised lines that repeat at the top or bottom of most pages.

    Only the first and last few lines of each page are considered, so a
    sentence that legitimately recurs in body text is never removed.
    """
    if len(pages) < 5:
        return set()
    n = settings.running_line_scan_lines
    counts: Counter[str] = Counter()
    for _, text in pages:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        edge = lines[:n] + lines[-n:]
        for norm in {normalise_line(line) for line in edge if line.strip()}:
            if norm and len(norm) <= 120:
                counts[norm] += 1
    # A running head repeats within a CHAPTER, not across the whole book, so a
    # "most pages" threshold misses it entirely. Use an absolute floor instead:
    # appearing at the edge of many pages is already strong evidence.
    floor = max(5, int(len(pages) * settings.running_line_threshold))
    return {line for line, c in counts.items() if c >= floor}


def strip_running_lines(text: str, running: set[str]) -> tuple[str, int]:
    """Remove running lines from the page edges only. Returns (text, removed)."""
    if not running:
        return text, 0
    lines = text.splitlines()
    # On a short page every line would fall inside the edge window, which would
    # strip body text. Shrink the window so the middle of a page is always safe.
    n = settings.running_line_scan_lines
    if len(lines) < 2 * n + 2:
        n = 1
    keep: list[str] = []
    removed = 0
    last = len(lines) - 1
    for i, line in enumerate(lines):
        at_edge = i < n or i > last - n
        if at_edge and line.strip() and normalise_line(line) in running:
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
_ALLCAPS_HEADING = re.compile(r"^\s*([A-Z][A-Z \-&/]{6,60})\s*$")
_TABLE_CAPTION = re.compile(r"^\s*(?:TABLE|Table|FIGURE|Figure)\s+\d+")
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
# Chunks below this are merged into their neighbour rather than published.
_MIN_CHUNK_TOKENS = 25
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


def _table_run_length(lines: list[str], i: int) -> int:
    """How many lines from i form a table-like run. 0 if it is not one.

    Deliberately conservative. An earlier version treated any short line as
    tabular, which turned every equation in a maths textbook into its own
    tiny "table" chunk. A run must now be either introduced by an explicit
    TABLE/FIGURE caption, or be strongly numeric throughout.
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


def _heading_number(heading: str) -> str:
    """The numbering off the front of a validated heading string."""
    return heading.split(" ", 1)[0]


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
        limit = min(seen)
        while limit + 1 in seen:
            limit += 1
        allowed |= {name(n) for n in seen if n <= limit}

    allowed |= _bare_integer_clauses(ordered)
    return allowed


def _candidate_headings(
    pages: list[tuple[int, str]],
    running: set[str],
    page_kinds: dict[int, str] | None,
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
        cleaned, _ = strip_running_lines(raw, running)
        lines = cleaned.splitlines()
        if sum(1 for line in lines if looks_like_heading(line)) > _CONTENTS_PAGE_HEADINGS:
            continue  # a contents page never sets heading state
        i = 0
        while i < len(lines):
            head = looks_like_heading(lines[i])
            consumed = 1
            if head is None:
                head, consumed = _split_line_heading(lines, i)
            if head:
                found.append(head)
            i += consumed
    return found


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
    allowed_numbers = plausible_heading_numbers(
        _heading_number(h) for h in _candidate_headings(pages, running, page_kinds)
    )

    kinds = page_kinds or {}
    for page_no, raw in pages:
        page_kind = kinds.get(page_no, "prose")
        cleaned, removed = strip_running_lines(raw, running)
        removed_total += removed
        lines = cleaned.splitlines()

        if page_kind != "prose":
            # Front matter, contents and index are kept whole for inspection
            # but never treated as prose, and never set heading state.
            body = cleaned.strip()
            if body:
                blocks.append(Block(page_kind, body, page_no, page_no, None))
            continue

        # A contents page is a wall of heading-like lines. Letting it set the
        # section state makes every later chunk inherit a heading from the
        # front matter, so headings from such a page are ignored entirely.
        heading_hits = sum(1 for line in lines if looks_like_heading(line))
        contents_page = heading_hits > _CONTENTS_PAGE_HEADINGS

        buf: list[str] = []
        i = 0

        def flush_prose() -> None:
            nonlocal buf
            body = "\n".join(buf).strip()
            if body:
                blocks.append(Block("prose", body, page_no, page_no, section))
            buf = []

        while i < len(lines):
            line = lines[i]

            head = looks_like_heading(line)
            consumed = 1
            if head is None:
                # The split-line form: a clause number alone, its title on the
                # next line. This is how NORSOK and most engineering
                # specifications lay headings out, and it is why every chunk
                # in such a document had section: null.
                head, consumed = _split_line_heading(lines, i)

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

            if head:
                flush_prose()
                if not contents_page:
                    # heading state persists across pages until the next heading
                    section = head
                i += consumed
                continue

            run = _table_run_length(lines, i)
            if run:
                flush_prose()
                body = "\n".join(lines[i:i + run]).strip()
                if body:
                    blocks.append(Block("table", body, page_no, page_no, section))
                i += run
                continue

            buf.append(line)
            i += 1

        flush_prose()

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


def sentences(text: str) -> list[str]:
    """Split prose into sentences, collapsing PDF line-wrap newlines.

    A PDF wraps mid-sentence, so the raw text is full of newlines that are
    layout, not meaning. Collapsing them makes a retrieved passage readable
    when it is quoted back to the user verbatim. Table blocks are handled
    separately and keep their line structure.
    """
    parts = [_WS.sub(" ", p).strip() for p in _SENTENCE_END.split(text)]
    parts = [p for p in parts if p]
    if parts:
        return parts
    collapsed = _WS.sub(" ", text).strip()
    return [collapsed] if collapsed else []


def build_chunks(blocks: list[Block]) -> list[Block]:
    """Accumulate blocks into ~target-token chunks on sentence boundaries."""
    target = settings.chunk_target_tokens
    ceiling = settings.chunk_max_tokens
    overlap = settings.chunk_overlap_tokens

    chunks: list[Block] = []
    cur: list[tuple[str, int, int, int]] = []  # (text, tokens, page_start, page_end)
    cur_tokens = 0
    cur_section: str | None = None

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

    for b in blocks:
        b.tokens = count_tokens(b.text)

        # a table stays whole when it fits; otherwise it is windowed, not dropped
        if b.kind == "table" and b.tokens < _MIN_TABLE_TOKENS:
            # too small to be a useful standalone chunk - treat it as prose
            b.kind = "prose"

        if b.kind not in ("prose", "table"):
            # toc / frontmatter / index / references: keep as its own chunk so
            # it can be inspected, but never blend it into retrievable prose.
            flush()
            if b.tokens <= ceiling:
                chunks.append(Block(b.kind, b.text, b.page_start, b.page_end, None, b.tokens))
            else:
                chunks.extend(split_oversized(b.text, b.page_start, b.page_end, None, b.kind))
            continue

        if b.kind == "table":
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
            flush()
            cur_section = b.section

        if b.tokens > ceiling:
            flush()
            chunks.extend(
                split_oversized(b.text, b.page_start, b.page_end, b.section, "prose")
            )
            continue

        for sent in sentences(b.text):
            st = count_tokens(sent)
            if st > ceiling:
                flush()
                chunks.extend(
                    split_oversized(sent, b.page_start, b.page_end, b.section, "prose")
                )
                continue
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
            cur.append((sent, st, b.page_start, b.page_end))
            cur_tokens += st

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
CHUNKER_VERSION = "4"


def _chunk_signature(doc_sha: str, pages: list[tuple[int, str]]) -> str:
    """Identifies the input to chunking: the document, its extracted text, and
    the chunker version. Unchanged signature means the output would be
    identical, so the work can be skipped."""
    h = hashlib.sha256()
    h.update(doc_sha.encode())
    h.update(CHUNKER_VERSION.encode())
    h.update(str(len(pages)).encode())
    for pno, text in pages:
        h.update(str(pno).encode())
        h.update(hashlib.sha256(text.encode("utf-8")).digest())
    return h.hexdigest()


def chunk_document(doc_id: str, force: bool = False) -> dict:
    """Chunk one extracted document. Idempotent - re-running replaces rows."""
    timer = Timer()
    conn = connect()
    keyword.ensure_schema(conn)
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise ValueError(f"unknown document {doc_id}")

    pages = [
        (r["page_no"], r["text"])
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (doc_id,),
        )
    ]
    if not pages:
        raise ValueError(f"{doc_id} has no extracted pages - run extraction first")

    total_pages = doc["page_count"] or len(pages)
    page_kinds = {pno: classify_page(text, pno, total_pages) for pno, text in pages}
    signature = _chunk_signature(doc["sha256"], pages)
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
    blocks, removed = segment_document(pages, running, page_kinds)
    chunks = build_chunks(blocks)

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
    retrievable = [
        c for c in chunks
        if c.kind in RETRIEVABLE_KINDS and quality[id(c)]["ok"]
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
                int(c.kind in RETRIEVABLE_KINDS and q["ok"]),
                ",".join(q["reasons"]) or None,
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
            reason = "scanned page with no extractable text; OCR is not implemented"
            rule = "needs_ocr_not_implemented"
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
                retrievable, quality_flags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
