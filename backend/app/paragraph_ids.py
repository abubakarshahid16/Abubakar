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
    "dotted": re.compile(r"^(?P<id>\d{1,3}(?:\.\d{1,3}){0,5})\.?(?=\s+[A-Z])"),
    # A.2.1 Title - an annex letter, then dotted numbers
    "annex": re.compile(r"^(?P<id>[A-Z]\.\d{1,3}(?:\.\d{1,3}){0,4})(?=\s+[A-Za-z])"),
    # AB-20 Title, XY-12.1 Title - letters, a hyphen, a number
    "prefixed": re.compile(r"^(?P<id>[A-Z]{1,5}-\d{1,4}(?:\.\d{1,3})*)(?=\s+[A-Za-z])"),
    # 12-4.1 Title - a number, a hyphen, a number
    "numbered_hyphen": re.compile(
        r"^(?P<id>\d{1,3}-\d{1,3}(?:\.\d{1,3})*)(?=\s+[A-Za-z])"
    ),
}
#: A sub-paragraph marker at the start of a line: (a) or (1).
_SUB = re.compile(r"^\((?P<mark>[a-z]|\d{1,2})\)(?=\s)")

#: A standard's numbering is the shape holding most of its distinct headings,
#: and only when there are enough of them to mean it.
MIN_HEADINGS = 8
MIN_SHARE = 0.5
#: How many chunks before the requirement's own are searched for its heading.
LOOK_BACK = 6


def _lines(text: str) -> list[tuple[int, str]]:
    """[(offset, stripped line)] for the non-empty lines of `text`."""
    out, at = [], 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped:
            out.append((at + (len(raw) - len(raw.lstrip())), stripped))
        at += len(raw) + 1
    return out


def headings(text: str, shape: str) -> list[tuple[int, str]]:
    """[(offset, id)] of the line-leading identifiers of `shape` in `text`."""
    pattern = SHAPES[shape]
    return [
        (at, m.group("id")) for at, line in _lines(text) if (m := pattern.match(line))
    ]


def dominant_shape(texts: list[str]) -> str | None:
    """The numbering shape most of the standard's own headings share, or None
    when there are too few headings, or no shape holds half of them."""
    ids = {shape: {i for t in texts for _, i in headings(t, shape)} for shape in SHAPES}
    total = sum(len(v) for v in ids.values())
    shape, found = max(ids.items(), key=lambda kv: len(kv[1]))
    if len(found) >= MIN_HEADINGS and len(found) / total >= MIN_SHARE:
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


def paragraph_for(
    chunks: list[str], index: int, source_text: str, shape: str
) -> str | None:
    """The paragraph id the requirement's `source_text` sits under: the last
    heading of `shape` before it in chunk `index` (or the nearest chunks
    before), with the sub-paragraph in force. None when the sentence is not in
    its chunk or no heading is found within `LOOK_BACK` chunks."""
    probe = _normal(source_text)[:80]
    text = chunks[index]
    # offsets are into `text`; compare on the same whitespace folding
    flat = _normal(text)
    if not probe or probe not in flat:
        return None
    position = _position_of(text, probe)
    found = [(at, i) for at, i in headings(text, shape) if at < position]
    if found:
        at, ident = found[-1]
        return ident + _sub_marks(text, at, position)
    for back in range(1, LOOK_BACK + 1):
        if index - back < 0:
            break
        earlier = headings(chunks[index - back], shape)
        if earlier:
            return earlier[-1][1]
    return None


def _position_of(text: str, probe: str) -> int:
    """The offset in `text` where the whitespace-folded `probe` starts."""
    words = probe.split(" ")
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, text)
    return m.start() if m else len(text)


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
    by_standard: dict[str, tuple[list[str], dict[str, int], str | None]] = {}
    for f in wanted:
        standard = f["standard_document_id"]
        if standard not in by_standard:
            rows = conn.execute(
                "SELECT id, text FROM chunks WHERE document_id = ? ORDER BY page_start, ordinal",
                [standard],
            ).fetchall()
            texts = [r["text"] or "" for r in rows]
            by_standard[standard] = (
                texts,
                {r["id"]: i for i, r in enumerate(rows)},
                dominant_shape(texts),
            )
        texts, position, shape = by_standard[standard]
        chunk_id, source_text = requirements.get(f["requirement_id"], (None, None))
        if shape is None or chunk_id not in position or not source_text:
            continue
        paragraph = paragraph_for(texts, position[chunk_id], source_text, shape)
        if paragraph:
            f["paragraph_id"] = paragraph
