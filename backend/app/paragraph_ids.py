"""Order 161 C: the paragraph a CRS row cites, read from the standard's own numbering.

A requirement carries the clause of the heading its chunk was cut under. For a
standard whose headings are not "4.3.2 Title" - paragraph ids such as "UG-20"
with sub-paragraphs "(b)" - that clause is a number read from a table, and
`standards.paragraph_ids_known` says so; the CRS then printed "paragraph not
identified" on every row of that standard. The paragraph is in the standard's
own text, so this module reads it there.

GENERAL BY CONSTRUCTION (owner order 143): nothing here names a standard, a
part, a prefix or a layout. A heading is a line that BEGINS with an identifier
of one of a few numbering SHAPES followed by its title; a standard's numbering
is the shape that most of its own headings share (`dominant_shape`), so a table
row that only looks like a heading in another shape is never taken for one. When
no shape clearly dominates, or the requirement's own sentence is not found in
its chunk, the answer is None and the CRS keeps saying "paragraph not
identified": unsure is never guessed (CLAUDE.md rule 4).

A heading is either a line of its own (a title in Title Case or capitals) or a
RUN-IN heading: the identifier, a title in CAPITALS, and the text of the
paragraph (often its first sub-paragraph "(a)") on the same line.

DISPLAY ONLY. Read only: it sets `paragraph_id` on a finding in memory, beside
`standard_clause`, which is left exactly as it was - the permanent comment
numbers are keyed on the requirement, never on this. No network; nothing is
logged.
"""

from __future__ import annotations

import re

from .config import settings
from .db import connect

#: The numbering shapes: an identifier at the start of a line, then the rest of
#: the line. A shape is a SHAPE (letters, digits, separators), never a list of
#: codes.
SHAPES: dict[str, re.Pattern] = {
    # 4.3.2 Title - dotted numbers
    "dotted": re.compile(r"^(?P<id>\d{1,3}(?:\.\d{1,3}){0,5})\.?\s+(?P<rest>\S.*)$"),
    # A.2.1 Title - an annex letter, then dotted numbers
    "annex": re.compile(r"^(?P<id>[A-Z]\.\d{1,3}(?:\.\d{1,3}){0,4})\s+(?P<rest>\S.*)$"),
    # AB-20 Title, XY-12.1 Title - letters, a hyphen, a number
    "prefixed": re.compile(
        r"^(?P<id>[A-Z]{1,5}-\d{1,4}(?:\.\d{1,3})*)\s+(?P<rest>\S.*)$"
    ),
    # 12-4.1 Title - a number, a hyphen, a number
    "numbered_hyphen": re.compile(
        r"^(?P<id>\d{1,3}-\d{1,3}(?:\.\d{1,3})*)\s+(?P<rest>\S.*)$"
    ),
}
#: A sub-paragraph marker at the start of a line: (a) or (1).
_SUB = re.compile(r"^\((?P<mark>[a-z]|\d{1,2})\)(?=\s)")
#: A number standing alone in a title ("Hot 5 bar"): a table row, not a heading.
_NUMBER_WORD = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])")
#: A word of a title in capitals: letters, with hyphens, slashes and ampersands
#: inside it, and an optional closing full stop or colon.
_CAPS_WORD = re.compile(r"^[A-Z][A-Z\-/&,]*[.:]?$")

#: A standard's numbering is the shape holding MORE THAN HALF of its distinct
#: headings, and only when there are enough of them to mean it.
MIN_HEADINGS = 8
MIN_SHARE = 0.5
#: An identifier that opens a line in more than this many chunks is a running
#: header or a repeated table row, not a heading.
MAX_CHUNKS_PER_HEADING = 2
#: A requirement sentence shorter than this (folded) is too generic to locate.
MIN_PROBE = 25
#: How many chunks before the requirement's own are searched for its heading.
LOOK_BACK = 6
#: The longest title a heading line carries.
MAX_TITLE = 90


def _lines(text: str) -> list[tuple[int, str]]:
    """[(offset, stripped line)] for the non-empty lines of `text`."""
    out, at = [], 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped:
            out.append((at + (len(raw) - len(raw.lstrip())), stripped))
        at += len(raw) + 1
    return out


def _is_title(title: str) -> bool:
    """A heading line's title is short, does not read as a sentence (no closing
    full stop, comma or semicolon) and holds no number of its own."""
    title = title.strip()
    return (
        2 <= len(title) <= MAX_TITLE
        and not title.endswith((".", ",", ";"))
        and not _NUMBER_WORD.search(title)
    )


def _run_in(rest: str, limit: int | None = MAX_TITLE) -> str | None:
    """For the text after an identifier that starts with a title in CAPITALS and
    goes on in the same line: the sub-paragraph marker that follows the title
    ("a", "1", or "" for none), else None when it is not a run-in heading. The
    text after the title must be empty, a marker, or begin with a letter: a
    number there is a table row or a contents entry."""
    words = rest.split()
    caps: list[str] = []
    for word in words:
        if not _CAPS_WORD.match(word):
            break
        caps.append(word)
        if word.endswith((".", ":")):
            break
    title = " ".join(caps)
    if sum(c.isalpha() for c in title) < 3 or (limit and len(title) > limit):
        return None
    after = words[len(caps) :]
    if not after:
        return ""
    m = _SUB.match(after[0] + " ")
    if m:
        return m.group("mark")
    return "" if after[0][0].isalpha() else None


def _heading(rest: str) -> str | None:
    """The inline sub-paragraph marker ("" when none) of a heading line whose
    text after the identifier is `rest`, or None when the line is not a
    heading: a contents entry ("title . . . . 25"), a sentence, a table row."""
    if rest[0].isupper() and _is_title(rest):
        return ""
    return _run_in(rest)


def headings(
    text: str, shape: str, skip: frozenset[str] = frozenset()
) -> list[tuple[int, str, str]]:
    """[(offset, id, inline marker)] of the heading lines of `shape` in `text`:
    a line that begins with the identifier and goes on as a title (`_heading`).
    Identifiers in `skip` (running headers) are not headings."""
    pattern = SHAPES[shape]
    out = []
    for at, line in _lines(text):
        m = pattern.match(line)
        if m and m.group("id") not in skip:
            inline = _heading(m.group("rest"))
            if inline is not None:
                out.append((at, m.group("id"), inline))
    return out


def running_headers(texts: list[str]) -> frozenset[str]:
    """Identifiers that open a line in more than `MAX_CHUNKS_PER_HEADING`
    chunks, in any shape: page headers and repeated rows, never headings."""
    seen: dict[str, int] = {}
    for text in texts:
        for shape in SHAPES:
            for ident in {i for _, i, _ in headings(text, shape)}:
                seen[ident] = seen.get(ident, 0) + 1
    return frozenset(i for i, n in seen.items() if n > MAX_CHUNKS_PER_HEADING)


def dominant_shape(texts: list[str], skip: frozenset[str] = frozenset()) -> str | None:
    """The numbering shape most of the standard's own headings share, or None
    when there are too few headings, or no shape holds MORE than half of them
    (two shapes with the same number of headings are not a numbering)."""
    ids = {
        shape: {i for t in texts for _, i, _ in headings(t, shape, skip)}
        for shape in SHAPES
    }
    total = sum(len(v) for v in ids.values())
    shape, found = max(ids.items(), key=lambda kv: len(kv[1]))
    if len(found) >= MIN_HEADINGS and len(found) / total > MIN_SHARE:
        return shape
    return None


def _sub_marks(text: str, start: int, stop: int, inline: str = "") -> str:
    """The sub-paragraph "(b)(2)" in force at `stop`: the marker on the heading
    line itself (`inline`), then the line-leading markers after `start`."""
    letter, digit = ("", inline) if inline.isdigit() else (inline, "")
    for at, line in _lines(text):
        if not start < at < stop:
            continue
        m = _SUB.match(line)
        if not m:
            continue
        mark = m.group("mark")
        if mark.isdigit():
            digit = mark
        else:
            letter, digit = mark, ""
    return (f"({letter})" if letter else "") + (f"({digit})" if digit else "")


def _unplaced_heading(
    text: str, start: int, stop: int, skip: frozenset[str] = frozenset()
) -> bool:
    """True when a line after `start`, up to and including the one at `stop`,
    opens like a heading of ANY shape (an identifier, then a title in capitals
    that goes on in the same line, of any length) that the numbering did not
    recognise (a title over `MAX_TITLE` is not): the paragraph in force is then
    not the one found before it. A contents entry or table row (a number or
    dot leaders after the title) is not a heading. Unsure is "not identified",
    never the paragraph before."""
    for at, line in _lines(text):
        if not start < at <= stop:
            continue
        for pattern in SHAPES.values():
            m = pattern.match(line)
            if not m or m.group("id") in skip:
                continue
            if _run_in(m.group("rest"), limit=None) is not None:
                return True
    return False


def _normal(text: str) -> str:
    return " ".join(str(text or "").split())


def _position_of(text: str, probe: str) -> int | None:
    """The offset in `text` where the whitespace-folded `probe` starts, or
    None when it is not there exactly once (a sentence that occurs twice cannot
    say which paragraph it sits under)."""
    pattern = r"\s+".join(re.escape(w) for w in probe.split(" "))
    found = [m.start() for m in re.finditer(pattern, text)]
    return found[0] if len(found) == 1 else None


def paragraph_for(
    chunks: list[str],
    index: int,
    source_text: str,
    shape: str,
    skip: frozenset[str] = frozenset(),
    heads: list[list[tuple[int, str, str]]] | None = None,
) -> str | None:
    """The paragraph id the requirement's `source_text` sits under: the last
    heading of `shape` at or before it (a sentence that opens with its own
    heading line is under that heading), looking back through up to
    `LOOK_BACK` earlier chunks, with the sub-paragraph in force. None when the
    sentence is too short to place, is not in its chunk exactly once, or no
    heading precedes it, or when a line between that heading and the sentence
    opens like a heading the numbering did not recognise. `heads` is each
    chunk's `headings`, when already known (the per-standard memo)."""
    probe = _normal(source_text)[:80]
    if len(probe) < MIN_PROBE:
        return None
    here = _position_of(chunks[index], probe)
    if here is None:
        return None

    def of(i: int) -> list[tuple[int, str, str]]:
        return heads[i] if heads is not None else headings(chunks[i], shape, skip)

    found = [h for h in of(index) if h[0] <= here]
    first = index
    while not found and first > max(0, index - LOOK_BACK):
        first -= 1
        found = of(first)
    if not found:
        return None
    at, ident, inline = found[-1]
    before = "\n".join(chunks[first:index])
    window = (before + "\n" if before else "") + chunks[index]
    position = (len(before) + 1 if before else 0) + here
    if _unplaced_heading(window, at, position, skip):
        return None
    return ident + _sub_marks(window, at, position, inline)


def cited(finding: dict) -> str:
    """What a CRS standard reference prints after the standard's name: " cl. 4.3"
    for a clause that is a paragraph id; for a table number (`clause_identified`
    False) or no clause, " cl. <paragraph>" when the standard's own text names
    one (`paragraph_id`), else " (paragraph not identified)" for a table number
    (never the table number itself) and nothing for no clause."""
    clause = finding.get("standard_clause")
    if clause and finding.get("clause_identified") is not False:
        return f" cl. {clause}"
    paragraph = finding.get("paragraph_id")
    if paragraph:
        return f" cl. {paragraph}"
    return " (paragraph not identified)" if clause else ""


_CACHE: dict = {}
_CACHE_SIZE = 4


def _load(standard: str):
    """(texts, {chunk id: index}, numbering shape, running headers, each
    chunk's headings) of one standard's own chunks."""
    rows = (
        connect()
        .execute(
            "SELECT id, text FROM chunks WHERE document_id = ? ORDER BY ordinal",
            [standard],
        )
        .fetchall()
    )
    texts = [r["text"] or "" for r in rows]
    skip = running_headers(texts)
    shape = dominant_shape(texts, skip)
    heads = [headings(t, shape, skip) for t in texts] if shape else []
    return (texts, {r["id"]: i for i, r in enumerate(rows)}, shape, skip, heads)


def _read(standard: str):
    """`_load`, remembered per standard, its number of chunks, their total
    size and newest row (and the database they are in), so a re-chunked
    standard is read again and a CRS preview or export does not scan
    thousands of chunks twice."""
    size = (
        connect()
        .execute(
            "SELECT count(*) AS n, coalesce(sum(length(text)), 0) AS c,"
            " coalesce(max(rowid), 0) AS r FROM chunks WHERE document_id = ?",
            [standard],
        )
        .fetchone()
    )
    key = (standard, size["n"], size["c"], size["r"], str(settings.db_path))
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = _load(standard)
    return _CACHE[key]


def attach(findings: list[dict]) -> None:
    """Set `paragraph_id` on every finding of a standard whose clause is not a
    paragraph id (`clause_identified` False) or is missing, when the standard's
    own text says which paragraph it is under. In place; reads the standard's
    own chunks, which the run already reads; writes nothing."""
    wanted = [
        f
        for f in findings
        if f.get("requirement_id")
        and f.get("standard_document_id")
        and (f.get("clause_identified") is False or not f.get("standard_clause"))
    ]
    if not wanted:
        return
    conn = connect()
    ids = sorted({f["requirement_id"] for f in wanted})
    requirements: dict[str, tuple] = {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        marks = ",".join("?" for _ in part)
        for r in conn.execute(
            f"SELECT id, chunk_id, source_text FROM standard_requirements WHERE id IN ({marks})",
            part,
        ):
            requirements[r["id"]] = (r["chunk_id"], r["source_text"])
    reads: dict[str, tuple] = {}
    for f in wanted:
        standard = f["standard_document_id"]
        if standard not in reads:
            reads[standard] = _read(standard)
        texts, position, shape, skip, heads = reads[standard]
        chunk_id, source_text = requirements.get(f["requirement_id"], (None, None))
        if shape is None or chunk_id not in position or not source_text:
            continue
        paragraph = paragraph_for(
            texts, position[chunk_id], source_text, shape, skip, heads
        )
        if paragraph:
            f["paragraph_id"] = paragraph
