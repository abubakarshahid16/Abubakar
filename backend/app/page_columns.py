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
from typing import Any

from .config import settings

#: A unit in square brackets, alone ("[l/s]") or glued to a name ("(NPSHR)[m]").
_BRACKET_UNIT = re.compile(r"^(?P<pre>.*?)\[(?P<unit>[^\[\]]{1,12})\]$")
#: A plain number as one word.
_PLAIN_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
#: A row's own number, left of the first name.
_ROW_NUMBER = re.compile(r"^\d{1,3}$")
#: A line of capitals-only label text: no figure, no lowercase.
_CAPITALS_LABEL = re.compile(r"^[A-Z][A-Z .,/&#'()-]*$")

#: Slack (pt) either side of a name's box within which a number stands under it.
COLUMN_SLACK = 8.0
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
    return all(_CAPITALS_LABEL.match(ln) and len(ln.split()) <= STACK_MAX_WORDS
               for ln in lines)


def clean_cell(raw: Any, fallback: Callable[[Any], str]) -> str:
    """The cell's text: `fallback(raw)` as always, except stacked labels (switch
    on) which are unreadable and so empty."""
    if enabled() and isinstance(raw, str) and is_stacked_labels(raw):
        return ""
    return fallback(raw)


def _head(phrase: list[tuple], is_unit: Callable[..., bool]) -> dict[str, Any] | None:
    """`{name, unit, x0, x1, bbox}` when the phrase is NAME + bracketed unit."""
    last = phrase[-1][4]
    m = _BRACKET_UNIT.match(last)
    if not m or not is_unit(m.group("unit"), allow_single=True):
        return None
    name_words = [w[4] for w in phrase[:-1]] + ([m.group("pre")] if m.group("pre") else [])
    name = re.sub(r"\s+", " ", " ".join(name_words).replace("(", " ").replace(")", " ")).strip()
    if not re.search(r"[^\W\d_]", name):
        return None
    x0, x1 = min(w[0] for w in phrase), max(w[2] for w in phrase)
    return {"name": name, "unit": m.group("unit").strip(), "x0": x0, "x1": x1,
            "bbox": [round(x0, 2), round(min(w[1] for w in phrase), 2),
                     round(x1, 2), round(max(w[3] for w in phrase), 2)]}


def _under(heads: list[dict[str, Any]], line: list[tuple]) -> dict[int, tuple]:
    """Head index -> the plain-number word under it (leftmost wins)."""
    found: dict[int, tuple] = {}
    for w in line:
        if not _PLAIN_NUMBER.match(w[4]):
            continue
        centre = (w[0] + w[2]) / 2
        for k, h in enumerate(heads):
            if h["x0"] - COLUMN_SLACK <= centre <= h["x1"] + COLUMN_SLACK and k not in found:
                found[k] = w
                break
    return found


def _taken(word: tuple, taken: list[tuple[list[float], str]]) -> bool:
    """Another reader already holds this number: a row whose box covers the word
    AND whose text holds the word's text (a cell that merely covers the area
    does not own every number inside it)."""
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return any(b and b[0] <= cx <= b[2] and b[1] <= cy <= b[3]
               and word[4] in (text or "").replace("(", " ").replace(")", " ").split()
               for b, text in taken)


def with_head_rows(page: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` plus the header-line rows of `page` (switch on); `rows` as is when off."""
    if not enabled():
        return rows
    from . import geometry_reader as gr  # at call time: geometry_reader imports this module
    lines = gr._visual_lines([w for w in gr.upright_words(page) if w[4].strip()])
    return rows + head_rows(lines, gr._phrases, gr.is_unit_label, page_no=page.number + 1,
                            taken=[(r["bbox"], r["value_text"]) for r in rows if r.get("bbox")])


def head_rows(lines: list[list[tuple]], phrases: Callable[[list[tuple]], list[list[tuple]]],
              is_unit: Callable[..., bool], *, page_no: int,
              taken: list[tuple[list[float], str]]) -> list[dict[str, Any]]:
    """Label/value rows read from header lines of unit-bearing names (rule 1)."""
    out: list[dict[str, Any]] = []
    for li, line in enumerate(lines):
        heads = [h for h in (_head(p, is_unit) for p in phrases(line)) if h]
        if len(heads) < 2:
            continue
        need = max(2, (len(heads) + 1) // 2)
        data: list[tuple[tuple | None, dict[int, tuple]]] = []
        prev = line
        for nxt in lines[li + 1:]:
            height = max(w[3] - w[1] for w in prev) or 10.0
            if min(w[1] for w in nxt) - max(w[3] for w in prev) > MAX_LINE_GAP * height:
                break
            cells = _under(heads, nxt)
            if len(cells) < need:
                break
            key = next((w for w in nxt if _ROW_NUMBER.match(w[4])
                        and w[2] < heads[0]["x0"] and not any(w is c for c in cells.values())),
                       None)
            data.append((key, cells))
            prev = nxt
        for n, (key, cells) in enumerate(data, start=1):
            for k, w in sorted(cells.items()):
                if _taken(w, taken):
                    continue
                h = heads[k]
                label = h["name"] if len(data) == 1 else f"{h['name']} {key[4] if key else n}"
                out.append({
                    "source": "form", "page": page_no, "label": label, "label_text": h["name"],
                    "value_text": f"{w[4]} {h['unit']}", "value": w[4].replace(",", "."),
                    "unit": h["unit"], "is_blank": False, "blank_marker": None,
                    "condition": None, "note": None,
                    "bbox": [round(w[0], 2), round(w[1], 2), round(w[2], 2), round(w[3], 2)],
                    "label_bbox": h["bbox"], "position": "below",
                    "table_id": None, "row": None, "column": None, "column_label": None,
                })
    return out
