"""Two general page-reading rules for sheets laid out in columns (#1478).

Behind `settings.page_column_rows_enabled` (OFF by default). Plain code, no model.

1. A HEADER LINE OF UNIT-BEARING NAMES OVER A COLUMN OF NUMBERS. A line such as
   "FLOW [l/s]   HEAD [m]   POWER [kW]" with lines of numbers under it, each number
   standing under one name, is a table whose header is a line of text. The name
   plus the number plus the unit from the brackets is one label/value. Several
   lines under the header are several rows; the row's own number (1, 2) is kept
   in the label, so two rows never collapse into one field. A number in
   brackets beside a value (an alternative basis) is not the value. A number that
   another reader already took (same place on the page) is not read twice.

2. STACKED LABELS ARE NEVER ONE LABEL. A table cell of three or more lines, each
   line a short capitals-only label with no figure (POWER FACTOR / EFFICIENCY /
   MOTOR DATA), was joined into one jumbled label. Which value belongs to which
   line cannot be told from the cell text, so the cell is read as unreadable
   (empty): no row is keyed from it. Unreadable beats a wrong label.

The geometry helpers (visual lines, phrases, unit test) are passed in, so this
module does not import `geometry_reader` (which imports it).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from . import numparse
from .config import settings

#: A unit in square brackets, alone ("[l/s]") or glued to a name ("(NPSHR)[m]").
_BRACKET_UNIT = re.compile(r"^(?P<pre>.*?)\[(?P<unit>[^\[\]]{1,12})\]$")
#: A plain number as one word.
_PLAIN_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
#: A row's own number, left of the first name.
_ROW_NUMBER = re.compile(r"^\d{1,3}$")
#: A line of capitals-only label text: no figure, no lowercase.
_CAPITALS_LABEL = re.compile(r"^[A-Z][A-Z .,/&#'()-]*$")

#: A year as a number, and a line that is page furniture, not a measurement.
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_FURNITURE = re.compile(
    r"\b(?:page|sheet|rev|revision|date|issue)\b|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.](?:\d{2}|\d{4})\b",
    re.IGNORECASE,
)

#: What this page's reading left out, counted for the run in progress: {kind: n}.
_LOSSES: ContextVar[dict | None] = ContextVar("page_columns_losses", default=None)
STACKED = "stacked label cells"
SKIPPED = "value rows under a header line"
#: A data line is at most this many line heights below the line above it.
MAX_LINE_GAP = 3.0
#: Stacked labels: at least this many lines, each at most this many words.
STACK_MIN_LINES = 3
STACK_MAX_WORDS = 3


def enabled() -> bool:
    return bool(settings.page_column_rows_enabled)


def is_stacked_labels(raw: str | None) -> bool:
    """True when `raw` (a cell's text WITH its line breaks) is three or more
    short capitals-only label lines, each its own label."""
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if len(lines) < STACK_MIN_LINES:
        return False
    return all(
        _CAPITALS_LABEL.match(ln) and len(ln.split()) <= STACK_MAX_WORDS for ln in lines
    )


def clean_cell(raw: Any, fallback: Callable[[Any], str]) -> str:
    """The cell's text: `fallback(raw)` as always, except stacked labels (switch
    on) which are unreadable and so empty."""
    if enabled() and isinstance(raw, str) and is_stacked_labels(raw):
        _lose(STACKED)
        return ""
    return fallback(raw)


def _lose(kind: str) -> None:
    counts = _LOSSES.get()
    if counts is None:
        counts = {}
        _LOSSES.set(counts)
    counts[kind] = counts.get(kind, 0) + 1


def flush_losses(page_no: int) -> dict[str, int]:
    """Hand the counts left out of this page to the page ledger (the reader
    failures of `datasheets._PAGE_FAILURES`, which make the page's reading
    incomplete and are printed with it) and clear them."""
    counts = _LOSSES.get() or {}
    _LOSSES.set(None)
    if counts:
        from . import datasheets  # at call time: datasheets imports the readers

        failures = datasheets._PAGE_FAILURES.get()
        if failures is not None:
            said = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
            failures.setdefault(int(page_no), set()).add(
                f"column rows: {said} not read"
            )
    return counts


def _head(phrase: list[tuple], is_unit: Callable[..., bool]) -> dict[str, Any] | None:
    """`{name, unit, x0, x1, bbox}` when the phrase is NAME + bracketed unit."""
    last = phrase[-1][4]
    m = _BRACKET_UNIT.match(last)
    if not m or not is_unit(m.group("unit"), allow_single=True):
        return None
    name_words = [w[4] for w in phrase[:-1]] + (
        [m.group("pre")] if m.group("pre") else []
    )
    name = re.sub(
        r"\s+", " ", " ".join(name_words).replace("(", " ").replace(")", " ")
    ).strip()
    if not re.search(r"[^\W\d_]", name):
        return None
    x0, x1 = min(w[0] for w in phrase), max(w[2] for w in phrase)
    return {
        "name": name,
        "unit": m.group("unit").strip(),
        "x0": x0,
        "x1": x1,
        "bbox": [
            round(x0, 2),
            round(min(w[1] for w in phrase), 2),
            round(x1, 2),
            round(max(w[3] for w in phrase), 2),
        ],
    }


def _under(
    heads: list[dict[str, Any]], line: list[tuple]
) -> tuple[dict[int, tuple], bool, bool]:
    """(head index -> its one number, touched, clean). `touched`: a plain number
    stands under some name. `clean`: EVERY name has exactly one number inside its
    own box (no slack) and no number straddles two names."""
    per: dict[int, list[tuple]] = {}
    straddle = touched = False
    for w in line:
        if not _PLAIN_NUMBER.match(w[4]):
            continue
        hit = [k for k, h in enumerate(heads) if w[0] < h["x1"] and w[2] > h["x0"]]
        touched = touched or bool(hit)
        straddle = straddle or len(hit) > 1
        for k in hit:
            per.setdefault(k, []).append(w)
    clean = (
        not straddle
        and len(per) == len(heads)
        and all(len(v) == 1 for v in per.values())
    )
    return ({k: v[0] for k, v in per.items()} if clean else {}), touched, clean


def _is_measurement(line: list[tuple], cells: dict[int, tuple]) -> bool:
    """Not a date, page or sheet line, no year as a value, every value a number
    that `numparse` accepts."""
    if _FURNITURE.search(" ".join(w[4] for w in line)):
        return False
    return all(
        not _YEAR.match(w[4]) and numparse.parse_value(w[4]) is not None
        for w in cells.values()
    )


def _taken(word: tuple, taken: list[tuple[list[float], str]]) -> bool:
    """Another reader already holds this number: a row whose box covers the word
    AND whose text holds the word's text (a cell that merely covers the area
    does not own every number inside it)."""
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return any(
        b
        and b[0] <= cx <= b[2]
        and b[1] <= cy <= b[3]
        and word[4] in (text or "").replace("(", " ").replace(")", " ").split()
        for b, text in taken
    )


def with_head_rows(page: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` plus the header-line rows of `page` (switch on); `rows` as is when off."""
    if not enabled():
        return rows
    from . import (
        geometry_reader as gr,  # at call time: geometry_reader imports this module
    )

    lines = gr._visual_lines([w for w in gr.upright_words(page) if w[4].strip()])
    found = head_rows(
        lines,
        gr._phrases,
        gr.is_unit_label,
        page_no=page.number + 1,
        taken=[(r["bbox"], r["value_text"]) for r in rows if r.get("bbox")],
    )
    flush_losses(page.number + 1)
    return rows + found


def head_rows(
    lines: list[list[tuple]],
    phrases: Callable[[list[tuple]], list[list[tuple]]],
    is_unit: Callable[..., bool],
    *,
    page_no: int,
    taken: list[tuple[list[float], str]],
) -> list[dict[str, Any]]:
    """Label/value rows read from header lines of unit-bearing names (rule 1)."""
    out: list[dict[str, Any]] = []
    for li, line in enumerate(lines):
        heads = [h for h in (_head(p, is_unit) for p in phrases(line)) if h]
        if len(heads) < 2:
            continue
        data: list[tuple[tuple | None, dict[int, tuple]]] = []
        prev = line
        for nxt in lines[li + 1 :]:
            height = max(w[3] - w[1] for w in prev) or 10.0
            if min(w[1] for w in nxt) - max(w[3] for w in prev) > MAX_LINE_GAP * height:
                break
            cells, touched, clean = _under(heads, nxt)
            if not touched:
                break
            prev = nxt
            if not clean or not _is_measurement(nxt, cells):
                _lose(SKIPPED)
                continue
            key = next(
                (
                    w
                    for w in nxt
                    if _ROW_NUMBER.match(w[4])
                    and w[2] < heads[0]["x0"]
                    and not any(w is c for c in cells.values())
                ),
                None,
            )
            data.append((key, cells))
        for n, (key, cells) in enumerate(data, start=1):
            for k, w in sorted(cells.items()):
                if _taken(w, taken):
                    continue
                h = heads[k]
                label = (
                    h["name"]
                    if len(data) == 1
                    else f"{h['name']} {key[4] if key else n}"
                )
                out.append(
                    {
                        "source": "form",
                        "page": page_no,
                        "label": label,
                        "label_text": h["name"],
                        "value_text": f"{w[4]} {h['unit']}",
                        "value": w[4].replace(",", "."),
                        "unit": h["unit"],
                        "is_blank": False,
                        "blank_marker": None,
                        "condition": None,
                        "note": None,
                        "bbox": [
                            round(w[0], 2),
                            round(w[1], 2),
                            round(w[2], 2),
                            round(w[3], 2),
                        ],
                        "label_bbox": h["bbox"],
                        "position": "below",
                        "table_id": None,
                        "row": None,
                        "column": None,
                        "column_label": None,
                    }
                )
    return out
