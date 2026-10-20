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

DISPLAY ONLY. Read only: it sets `paragraph_id` on a finding in memory, beside
`standard_clause`, which is left exactly as it was - the permanent comment
numbers are keyed on the requirement, never on this. No network; nothing is
logged.
"""

from __future__ import annotations

import re

from .db import connect

#: The numbering shapes: an identifier at the start of a line, then its title.
#: A shape is a SHAPE (letters, digits, separators), never a list of codes.
SHAPES: dict[str, re.Pattern] = {
    # 4.3.2 Title - dotted numbers
    "dotted": re.compile(
        r"^(?P<id>\d{1,3}(?:\.\d{1,3}){0,5})\.?\s+(?P<title>[A-Z].*)$"
    ),
    # A.2.1 Title - an annex letter, then dotted numbers
    "annex": re.compile(
        r"^(?P<id>[A-Z]\.\d{1,3}(?:\.\d{1,3}){0,4})\s+(?P<title>[A-Z].*)$"
    ),
    # AB-20 Title, XY-12.1 Title - letters, a hyphen, a number
    "prefixed": re.compile(
        r"^(?P<id>[A-Z]{1,5}-\d{1,4}(?:\.\d{1,3})*)\s+(?P<title>[A-Z].*)$"
    ),
    # 12-4.1 Title - a number, a hyphen, a number
    "numbered_hyphen": re.compile(
        r"^(?P<id>\d{1,3}-\d{1,3}(?:\.\d{1,3})*)\s+(?P<title>[A-Z].*)$"
    ),
}
#: A sub-paragraph marker at the start of a line: (a) or (1).
_SUB = re.compile(r"^\((?P<mark>[a-z]|\d{1,2})\)(?=\s)")
#: A number standing alone in a title ("Hot 5 bar"): a table row, not a heading.
_NUMBER_WORD = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])")

#: A standard's numbering is the shape holding MORE THAN HALF of its distinct
#: headings (and more than any other shape), and only when there are enough
#: of them to mean it.
MIN_HEADINGS = 8
MIN_SHARE = 0.5
#: An identifier that opens a line in this many chunks or more is a running
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
    """A heading's title is short, does not read as a sentence (no closing
    full stop, comma or semicolon) and holds no number of its own."""
    title = title.strip()
    return (
        2 <= len(title) <= MAX_TITLE
        and not title.endswith((".", ",", ";"))
        and not _NUMBER_WORD.search(title)
    )


def headings(
    text: str, shape: str, skip: frozenset[str] = frozenset()
) -> list[tuple[int, str]]:
    """[(offset, id)] of the heading lines of `shape` in `text`: a line that
    begins with the identifier, then a title that is a title (`_is_title`).
    Identifiers in `skip` (running headers) are not headings."""
    pattern = SHAPES[shape]
    out = []
    for at, line in _lines(text):
        m = pattern.match(line)
        if m and m.group("id") not in skip and _is_title(m.group("title")):
            out.append((at, m.group("id")))
    return out


def running_headers(texts: list[str]) -> frozenset[str]:
    """Identifiers that open a line in more than `MAX_CHUNKS_PER_HEADING`
    chunks, in any shape: page headers and repeated rows, never headings."""
    seen: dict[str, int] = {}
    for text in texts:
        for shape in SHAPES:
            for ident in {i for _, i in headings(text, shape)}:
                seen[ident] = seen.get(ident, 0) + 1
    return frozenset(i for i, n in seen.items() if n > MAX_CHUNKS_PER_HEADING)


def dominant_shape(texts: list[str], skip: frozenset[str] = frozenset()) -> str | None:
    """The numbering shape most of the standard's own headings share, or None
    when there are too few headings, or no shape holds MORE than half of them
    (two shapes with the same number of headings are not a numbering)."""
    ids = {
        shape: {i for t in texts for _, i in headings(t, shape, skip)}
        for shape in SHAPES
    }
    total = sum(len(v) for v in ids.values())
    shape, found = max(ids.items(), key=lambda kv: len(kv[1]))
    if len(found) >= MIN_HEADINGS and len(found) / total > MIN_SHARE:
        return shape
    return None


def _sub_marks(text: str, start: int, stop: int) -> str:
    """The sub-paragraph "(b)(2)" in force at `stop`, for markers after `start`."""
    letter = digit = ""
    for at, line in _lines(text):
        if not start <= at < stop:
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
) -> str | None:
    """The paragraph id the requirement's `source_text` sits under: the last
    heading of `shape` before it, looking back through up to `LOOK_BACK`
    earlier chunks, with the sub-paragraph in force. None when the sentence is
    too short to place, is not in its chunk exactly once, or no heading
    precedes it."""
    probe = _normal(source_text)[:80]
    if len(probe) < MIN_PROBE:
        return None
    here = _position_of(chunks[index], probe)
    if here is None:
        return None
    first = max(0, index - LOOK_BACK)
    before = "\n".join(chunks[first:index])
    window = (before + "\n" if before else "") + chunks[index]
    position = (len(before) + 1 if before else 0) + here
    found = [(at, i) for at, i in headings(window, shape, skip) if at < position]
    if not found:
        return None
    at, ident = found[-1]
    return ident + _sub_marks(window, at, position)


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
    by_standard: dict[
        str, tuple[list[str], dict[str, int], str | None, frozenset[str]]
    ] = {}
    for f in wanted:
        standard = f["standard_document_id"]
        if standard not in by_standard:
            rows = conn.execute(
                "SELECT id, text FROM chunks WHERE document_id = ? ORDER BY ordinal",
                [standard],
            ).fetchall()
            texts = [r["text"] or "" for r in rows]
            skip = running_headers(texts)
            by_standard[standard] = (
                texts,
                {r["id"]: i for i, r in enumerate(rows)},
                dominant_shape(texts, skip),
                skip,
            )
        texts, position, shape, skip = by_standard[standard]
        chunk_id, source_text = requirements.get(f["requirement_id"], (None, None))
        if shape is None or chunk_id not in position or not source_text:
            continue
        paragraph = paragraph_for(texts, position[chunk_id], source_text, shape, skip)
        if paragraph:
            f["paragraph_id"] = paragraph
