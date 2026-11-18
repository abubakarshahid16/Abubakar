"""A form printed in TWO HALVES side by side (owner's measure, 18 Nov 2026: the strict judges marked comments WRONG that set one
half's value against the other half's heading). In the page text read in visual order, one text line holds a field of the left
half and a field of the right half, so the model reads "LABEL value   LABEL value" as one field and takes the right half's value
for the left half's item. Code finds the ONE position where the page splits: a wide gap that most lines with text on both sides
share and few lines cross. The page is then shown to the model as its left half, then its right half, under the same page number.
The quote check still reads the page as stored: a quote from one half stands on the stored line as it did; a quote that runs
across the two halves is not found, as before. A page with no such split (prose, a scanned page, a table whose lines run across)
is shown as it is. No document word is written here."""

from __future__ import annotations

import re

#: The two halves are apart by at least this many spaces where a line is cut.
GAP = 2
#: A line is cut at its own gap nearest the page's split position, at most this many positions away (a form's right half does
#: not start at one exact position on every line).
DRIFT = 12
#: A page is split only when at least this many lines, and this share of its lines with text, are cut with text on both sides.
MIN_LINES = 8
MIN_SHARE = 0.4
#: ... and at most this share of its lines with text run across the split with no gap near it.
MAX_CROSS = 0.25
#: The split position is searched between these shares of the page's widest line, and never nearer the left edge than
#: `MIN_LEFT` characters (a half of a form is wider than a line number and its gap).
FROM, TO = 0.3, 0.75
MIN_LEFT = 40


def cut(line: str, c: int) -> int | None:
    """Where ONE line is cut for split position c: the gap of at least `GAP` spaces nearest c (within `DRIFT`), with text on
    both sides and the right part starting with a letter (a label: a fill-in, a star or a figure is the value of the field on
    its left); None when the line has text on one side only or runs across."""
    if len(line) <= c - DRIFT or not line.strip():
        return None
    for d in range(DRIFT + 1):
        for g in (c - d, c + d):
            if (
                GAP <= g < len(line)
                and line[g - GAP : g].isspace()
                and line[:g].strip()
                and line[g:]
                .strip()[:1]
                .isalpha()  # the right half starts with a label, never a fill-in or a figure
            ):
                return g
    return None


def _score(lines: list[str], c: int) -> tuple[int, int]:
    """(lines cut at c with text on both sides, lines with text on both sides of c and no gap near it)."""
    both = cross = 0
    for line in lines:
        if cut(line, c) is not None:
            both += 1
        elif len(line) > c and line[:c].strip() and line[c:].strip():
            cross += 1
    return both, cross


def split_at(text: str) -> int | None:
    """The position where a two-half page splits, or None when the page is not a two-half form."""
    lines = [ln for ln in str(text or "").split("\n") if ln.strip()]
    if len(lines) < MIN_LINES:
        return None
    width = max(len(ln) for ln in lines)
    best = None
    for c in range(max(int(width * FROM), MIN_LEFT), int(width * TO) + 1):
        both, cross = _score(lines, c)
        enough = both >= max(MIN_LINES, MIN_SHARE * len(lines))
        if (
            enough
            and cross <= MAX_CROSS * len(lines)
            and (best is None or both - cross > best[1])
        ):
            best = (c, both - cross)
    return best[0] if best else None


def halves(text: str) -> tuple[str, str] | None:
    """(left half, right half) of a two-half page, each line cut at its own gap near the split position (a line that runs
    across stays whole in the left half; a line with text only right of the split goes to the right half), or None."""
    c = split_at(text)
    if c is None:
        return None
    left, right = [], []
    for line in str(text or "").split("\n"):
        g = cut(line, c)
        if g is not None:
            left.append(line[:g].rstrip())
            right.append(line[g:].strip())
        elif line.strip() and not line[: max(c - DRIFT, 0)].strip():
            right.append(line.strip())  # text in the right half only
        else:
            left.append(line.rstrip())
    return "\n".join(left), "\n".join(x for x in right if x)


#: A field with two names and two values split by "/": "Name A/Name B   x / y". The names are words (no figure); the values
#: are the first two "/"-separated parts after a gap of two spaces or more.
_PAIR = re.compile(
    r"(?P<head>[A-Za-z][A-Za-z .()]*?)?\b(?P<a>[A-Za-z][A-Za-z.]*)\s*/\s*(?P<b>[A-Za-z][A-Za-z.]*)\s*:?\s{2,}"
    r"(?P<x>[^/\s](?:[^/\s]| (?! ))*?|-) ?/ {0,4}(?P<y>[^/\s]+)"  # a value holds no gap of two spaces
)


def pairs(line: str) -> str:
    """The reading of a paired field on one line, "(read in pairs: A = x; B = y)", or "" when the line holds none."""
    m = _PAIR.search(line or "")
    if not m:
        return ""
    x, y = (v.strip(" _") for v in (m["x"], m["y"]))
    x, y = (v if v not in ("", "-") else "blank" for v in (x, y))
    return f"(read in pairs: {m['a']} = {x}; {m['b']} = {y})"


def with_pairs(text: str) -> str:
    """The text with the reading of each paired field on a line of its own below it; the line itself is unchanged."""
    out = []
    for line in str(text or "").split("\n"):
        out.append(line)
        reading = pairs(line)
        if reading:
            out.append("    " + reading)
    return "\n".join(out)
