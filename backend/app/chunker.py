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
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from tokenizers import Tokenizer

from .config import settings
from .db import connect
from .rates import Timer, rate

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

    toc_lines = sum(1 for line in lines if _TOC_LINE.match(line))
    if len(lines) >= 6 and toc_lines >= len(lines) * 0.4 and toc_lines >= 5:
        # An index has the same shape but sits at the back of the book.
        if page_no > total_pages * 0.85:
            return "index"
        return "toc"

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
                # carry the trailing sentences forward as overlap
                tail: list[tuple[str, int, int, int]] = []
                acc = 0
                for item in reversed(cur):
                    if acc >= overlap:
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


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(doc_sha: str, page_start: int, ordinal: int, chash: str) -> str:
    """Deterministic: document hash + page + ordinal + content hash.

    A retry therefore REPLACES the same row rather than inserting a duplicate.
    """
    return f"{doc_sha[:12]}:p{page_start:05d}:c{ordinal:05d}:{chash[:8]}"


def chunk_document(doc_id: str) -> dict:
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
    running = detect_running_lines(pages)
    blocks, removed = segment_document(pages, running, page_kinds)
    chunks = build_chunks(blocks)

    ceiling = settings.chunk_max_tokens
    over = [c for c in chunks if c.tokens > ceiling]
    assert not over, (
        f"{len(over)} chunk(s) exceed the {ceiling}-token ceiling "
        f"(max {max(c.tokens for c in over) if over else 0}) - e5-small would truncate them"
    )

    retrievable = [c for c in chunks if c.kind in RETRIEVABLE_KINDS]
    kind_counts: Counter[str] = Counter(c.kind for c in chunks)

    rows = []
    for ordinal, c in enumerate(chunks):
        chash = content_hash(c.text)
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
                int(c.kind in RETRIEVABLE_KINDS),
            )
        )

    with conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        conn.executemany(
            """INSERT OR REPLACE INTO chunks
               (id, document_id, filename, ordinal, page_start, page_end,
                section, kind, text, token_count, content_hash, retrievable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.execute(
            "UPDATE documents SET chunk_count = ?, status = 'embedding' WHERE id = ?",
            (len(retrievable), doc_id),
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
        "chunks_by_kind": dict(kind_counts),
        "chunks_this_run": len(chunks),
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
