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
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from tokenizers import Tokenizer

from .config import settings
from .db import connect
from .rates import Timer, rate
from . import states
from .quality import assess, looks_like_table

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
            removed += 1
            continue
        keep.append(line)
    return "\n".join(keep), removed


# ------------------------------------------------------------- structure

# 5.1 Introduction / 2.2.3 Location Tracking / CHAPTER 9
_HEADING = re.compile(
    r"^\s*(?:(?:CHAPTER|Chapter|SECTION|Section)\s+)?"
    r"(\d+(?:\.\d+){0,3})\s+([A-Z][^\n]{2,70})\s*$"
)
_ALLCAPS_HEADING = re.compile(r"^\s*([A-Z][A-Z \-&/]{6,60})\s*$")
_TABLE_CAPTION = re.compile(r"^\s*(?:TABLE|Table|FIGURE|Figure)\s+\d+")
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
_TRAILING_PAGE_NO = re.compile(r"\s\d{1,4}$")
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
    "composition", "rights and permissions", "manufacturing buyer",
    "vice president", "typeset in", "www.pearson", "permissions department",
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
    if early and len(text.split()) < 40 and len(lines) < 6:
        return "frontmatter"

    low = text.lower()
    marker_hits = sum(1 for m in _FRONTMATTER_MARKERS if m in low)
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
    # a table-of-contents line ends in a page number - not a real heading
    if _TRAILING_PAGE_NO.search(line):
        return None

    number, title = m.group(1), m.group(2).strip()

    # A section number is small and non-zero. "330 Hudson Street" is a street
    # address; "0 K(s, t) f(t) dt" is an integral, not section zero.
    parts = number.split(".")
    if any(int(p) > _MAX_SECTION_NUMBER for p in parts):
        return None
    if int(parts[0]) < 1:
        return None

    # Maths and code punctuation never appears in a section title.
    if _MATH_PUNCT.search(title):
        return None
    # A real title is mostly letters and spaces.
    letters = sum(1 for ch in title if ch.isalpha() or ch.isspace())
    if letters < len(title) * 0.85:
        return None

    # A title carrying digits is an address, a measurement or a code line
    # ("330 Hudson Street, NY, NY 10013"), not a section title.
    if _ANY_DIGIT.search(title):
        return None

    # A bare integer with a short title is a figure annotation ("3 L/min").
    # A dotted number ("5.1 Introduction") is unambiguous on its own.
    if "." not in number and len(title.split()) < 3:
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


def segment_document(
    pages: list[tuple[int, str]],
    running: set[str],
    page_kinds: dict[int, str] | None = None,
) -> tuple[list[Block], int]:
    """Flatten pages into blocks, carrying heading state across page boundaries."""
    blocks: list[Block] = []
    section: str | None = None
    removed_total = 0

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
            if head:
                flush_prose()
                if not contents_page:
                    # heading state persists across pages until the next heading
                    section = head
                i += 1
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
        cur: list[str] = []
        for w in c.text.split():
            cur.append(w)
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

    for pno, ptext in pages:
        kind = page_kinds.get(pno, "prose")
        # text_length uses the SAME definition as pages.char_count, so the two
        # endpoints cannot disagree by a trailing newline.
        length = len(ptext.strip())

        if kind not in RETRIEVABLE_KINDS:
            exclusion_rows.append(
                (doc_id, "page", pno, pno, None, f"page_classified_{kind}",
                 f"page classified as {kind}", ptext[:2000], length, now)
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
            (doc_id, "page", pno, pno, None, rule, reason, ptext[:2000], length, now)
        )
    for ordinal, c in enumerate(chunks):
        q = quality[id(c)]
        if c.kind in RETRIEVABLE_KINDS and not q["ok"]:
            exclusion_rows.append(
                (doc_id, "chunk", c.page_start, c.page_end,
                 chunk_id(doc["sha256"], c.page_start, ordinal, content_hash(c.text)),
                 "content_quality_gate", ",".join(q["reasons"]),
                 c.text[:2000], len(c.text.strip()), now)
            )

    with conn:
        conn.execute("DELETE FROM exclusions WHERE document_id = ?", (doc_id,))
        conn.executemany(
            """INSERT INTO exclusions
               (document_id, scope, page_start, page_end, chunk_id, rule,
                reason, text_sample, text_length, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            exclusion_rows,
        )
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
                section, kind, text, token_count, content_hash, retrievable,
                quality_flags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
