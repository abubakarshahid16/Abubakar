"""Geometry reader: tables and forms read from PDF positions (#193 section 5.1).

BEHIND FLAGS (#193 plan B4, order 5.5): the full reader OFF by default, its
TABLE path alone ON by default (owner decision 2026-09-25). The only caller is
`datasheets.extract_facts`, and only when `settings.geometry_reader_enabled`
(env GEOMETRY_READER_ENABLED) is on: it then writes `read_page_rows` as
`extraction_method='geometry'` facts beside the rule readers' facts, which
always win. `settings.geometry_table_reader_enabled` (env
GEOMETRY_TABLE_READER_ENABLED) writes the TABLE rows alone - schedules such
as a nozzle table - without the form path. With both off nothing calls this
module.

Pure functions over one `pymupdf.Page`. No model, no network, no database.

Two readers:

* `read_tables(page)` - PyMuPDF `find_tables` with BOTH the "lines" and the
  "text" strategy; the better grid wins by `page_score` (documented below).
  Then, per table, by cell geometry: a gutter column of row numbers is set
  aside, title rows and empty rows are dropped, the multi-row header is found
  and rebuilt so a parent cell spanning several columns labels each child as
  "Parent Child".
* `read_form(page)` - label/value pairs from word bounding boxes: a label is a
  phrase ending with ":" (or followed on its line by an underscore field); its
  value is the next phrase to the right on the same baseline, else the phrase
  directly below in the same column. Underscore runs are EMPTY values
  (`is_blank=True`), not missed reads.

Every value keeps where it came from: page number, bbox, table id, row and
column for tables; label bbox and value bbox for forms; and `source`.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

#: A number as datasheets write it: optional sign, decimals with "." or ",",
#: or a fraction ("1 1/2", "3/4").
_NUM = r"[-+]?\s?(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"

#: (pattern, canonical unit). Order matters: "bar g" before "bar". The bare
#: "C" is a unit ONLY after a number (see `split_value_unit`), never alone.
_UNITS: tuple[tuple[str, str], ...] = (
    (r"bar\s*\(\s*ga?\s*\)|bar\s*g|barg", "barg"),
    (r"bar", "bar"),
    (r"kPa", "kPa"),
    (r"MPa", "MPa"),
    (r"psig", "psig"),
    # "oC"/"OC": the degree sign typed as a letter o, common on filled forms.
    (r"deg\s*C|[°º]\s*C|[oO]C", "degC"),
    (r"C", "degC"),
    (r"mm", "mm"),
    (r"in", "in"),
    (r"NPS", "NPS"),
)
_UNIT_ALT = "|".join(f"(?:{p})" for p, _c in _UNITS)
_NUM_UNIT = re.compile(rf"^\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT_ALT})\s*$")
_NPS_PREFIX = re.compile(rf"^\s*NPS\s*(?P<num>{_NUM})\s*$")
#: Units that may stand alone in their own column/phrase. Bare "C" and "in"
#: are excluded: alone they are a letter and an English word.
_STANDALONE_UNITS = tuple((p, c) for p, c in _UNITS if p not in ("C", "in"))


def _canonical_unit(raw: str, *, standalone: bool = False) -> str | None:
    table = _STANDALONE_UNITS if standalone else _UNITS
    for pattern, canonical in table:
        if re.fullmatch(pattern, raw.strip()):
            return canonical
    return None


def split_value_unit(text: str | None) -> dict[str, Any]:
    """Split "10 barg" into value "10" and unit "barg", keeping the original.

    The split happens only when the WHOLE text is number + known unit (or
    "NPS <number>"). Anything else keeps `unit=None` and the text as value:
    "10" has no unit, and "C" with no number before it is not a unit.
    """
    original = text if text is not None else ""
    stripped = original.strip()
    m = _NUM_UNIT.match(stripped)
    if m:
        unit_raw = m.group("unit")
        return {"text": original, "value": re.sub(r"\s+", "", m.group("num"))
                if "/" not in m.group("num") else m.group("num").strip(),
                "unit": _canonical_unit(unit_raw), "unit_text": unit_raw}
    m = _NPS_PREFIX.match(stripped)
    if m:
        return {"text": original, "value": m.group("num").strip(),
                "unit": "NPS", "unit_text": "NPS"}
    if _NUMERIC.match(stripped):
        stripped = re.sub(r"\s+", "", stripped)  # "- 0.5" -> "-0.5"
    return {"text": original, "value": stripped or None, "unit": None,
            "unit_text": None}


def standalone_unit(text: str) -> str | None:
    """The canonical unit when `text` is ONLY a unit ("bar (ga)", "°C")."""
    return _canonical_unit(text, standalone=True)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

_INT = re.compile(r"^\d{1,4}$")
_NUMERIC = re.compile(rf"^{_NUM}$")
#: A tag/mark in a table's first labelled column: N1, K1A, M1, P-101A, 12A.
_TAG = re.compile(r"^(?:[A-Z]{1,3}-?\d{1,4}[A-Z]?|\d{1,3}[A-Z])$")
_BLANK_RUN = re.compile(r"_+|-{2,}")
#: One or more clause references: "(6.3.10)", "(6.10.2.2) (6.11.3)".
_CLAUSE_REF = re.compile(r"^(?:\(\s*[\d.]+[a-z.]*\s*\)\s*)+$")


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip() if text is not None else ""


def _has_letter(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _bbox(rect: Any) -> list[float] | None:
    if rect is None:
        return None
    return [round(float(v), 2) for v in tuple(rect)[:4]]


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

#: A cell counts as "spanning" a column when the column's centre lies inside it.
#: A row is a TITLE row when one of its cells spans at least this share of the
#: table width (gutter excluded).
TITLE_SPAN_SHARE = 0.6
#: A leading column is a row-number GUTTER when at least this share of its
#: non-empty cells are small integers.
GUTTER_INT_SHARE = 0.8
#: A header block deeper than this is not a header: the rows above the first
#: data-like row are then form content, and the table gets NO labels rather
#: than a wrong one built from twenty stacked rows.
MAX_HEADER_ROWS = 4


def _grid(table: Any) -> tuple[list[list[str]], list[list[Any]]]:
    """Cell texts and cell rects, row-major; merged cells are None in rects."""
    texts = [[_clean(c) for c in row] for row in table.extract()]
    rects = [list(r.cells) for r in table.rows]
    return texts, rects


def _column_spans(rects: list[list[Any]], ncols: int) -> list[tuple[float, float]]:
    """Each grid column's x-range. The narrowest right edge wins, because a
    merged cell only ever extends a column to the right."""
    spans = []
    for j in range(ncols):
        x0s = [r[j][0] for r in rects if j < len(r) and r[j] is not None]
        x1s = [r[j][2] for r in rects if j < len(r) and r[j] is not None]
        spans.append((min(x0s), min(x1s)) if x0s else (0.0, 0.0))
    return spans


def _gutter_columns(texts: list[list[str]]) -> set[int]:
    """Column 0 is a gutter when it is row numbers (GUTTER_INT_SHARE of its
    non-empty cells are small integers, at least 3 of them)."""
    col = [row[0] for row in texts if row and row[0]]
    ints = sum(1 for v in col if _INT.match(v))
    if len(col) >= 3 and ints / len(col) >= GUTTER_INT_SHARE:
        return {0}
    return set()


def _is_empty(row: list[str], gutter: set[int]) -> bool:
    return not any(v for j, v in enumerate(row) if j not in gutter)


def _is_data_like(row: list[str], gutter: set[int]) -> bool:
    """DATA-LIKE: the first non-empty non-gutter cell is a tag/mark (N1, K1A,
    P-101), or at least two non-gutter cells are plain numbers."""
    cells = [v for j, v in enumerate(row) if j not in gutter]
    first = next((v for v in cells if v), "")
    if _TAG.match(first):
        return True
    return sum(1 for v in cells if v and _NUMERIC.match(v)) >= 2


def _is_title_row(row_rects: list[Any], row_texts: list[str], gutter: set[int],
                  x_left: float, x_right: float) -> bool:
    """TITLE: one non-empty cell spans >= TITLE_SPAN_SHARE of the table width."""
    width = max(x_right - x_left, 1e-6)
    for j, rect in enumerate(row_rects):
        if j in gutter or rect is None or not row_texts[j]:
            continue
        if (rect[2] - rect[0]) / width >= TITLE_SPAN_SHARE:
            return True
    return False


def _header_labels(header_rows: list[int], rects: list[list[Any]],
                   texts: list[list[str]], spans: list[tuple[float, float]],
                   gutter: set[int]) -> dict[int, str]:
    """Rebuild the header BY GEOMETRY.

    For each column, walk the header rows top to bottom; in each, the cell
    whose x-range contains the column's centre contributes its text. A parent
    cell spanning three columns therefore contributes to all three, and each
    child reads "Parent Child". Text without a letter (row numbers, revision
    marks) never becomes a label.
    """
    labels: dict[int, str] = {}
    for j, (c0, c1) in enumerate(spans):
        if j in gutter:
            continue
        centre = (c0 + c1) / 2
        parts: list[str] = []
        for h in header_rows:
            for k, rect in enumerate(rects[h]):
                if rect is None or not texts[h][k]:
                    continue
                if rect[0] <= centre <= rect[2]:
                    text = texts[h][k]
                    if _has_letter(text) and (not parts or parts[-1] != text):
                        parts.append(text)
                    break
        if parts:
            labels[j] = " ".join(parts)
    return labels


def _split_words(table: Any, rects: list[list[Any]],
                 words: list[tuple]) -> tuple[int, int, set[tuple[int, int]]]:
    """(words inside the table, words cut across cells, the cells they touch).

    A word is CUT when its box overlaps two or more cells by more than 1 pt
    horizontally, each cell also covering at least 30 % of the word's height.
    """
    tx0, ty0, tx1, ty1 = table.bbox
    inside = split = 0
    touched: set[tuple[int, int]] = set()
    for w in words:
        x0, y0, x1, y1 = w[:4]
        if not (tx0 <= (x0 + x1) / 2 <= tx1 and ty0 <= (y0 + y1) / 2 <= ty1):
            continue
        inside += 1
        h = max(y1 - y0, 1e-6)
        hits = [(i, j) for i, row in enumerate(rects) for j, c in enumerate(row)
                if c is not None
                and min(x1, c[2]) - max(x0, c[0]) > 1.0
                and (min(y1, c[3]) - max(y0, c[1])) / h >= 0.3]
        if len(hits) >= 2:
            split += 1
            touched.update(hits)
    return inside, split, touched


def table_score(table: Any, words: list[tuple], grid: tuple | None = None) -> dict[str, Any]:
    """The documented grid score for one table.

    score = clean_cells x column_consistency ** 2

    * clean_cells: cells with text, minus every filled cell that holds part
      of a CUT word (a word whose box overlaps two cells - a column boundary
      guessed through the middle of a word corrupts both cells).
    * column_consistency: share of non-empty rows whose filled-cell count
      equals the most common filled-cell count (a real grid repeats its shape).
      Squared, so a regular grid beats a larger irregular one: the "text"
      strategy on a two-panel form page finds many cells but no shape.
    """
    texts, rects = grid or _grid(table)
    counts = [sum(1 for v in row if v) for row in texts]
    nonempty = [c for c in counts if c]
    filled = sum(nonempty)
    consistency = (sum(1 for c in nonempty if c == statistics.mode(nonempty))
                   / len(nonempty)) if nonempty else 0.0
    inside, split, touched = _split_words(table, rects, words)
    dirty = sum(1 for i, j in touched if i < len(texts) and j < len(texts[i]) and texts[i][j])
    clean = filled - dirty
    return {"filled_cells": filled, "clean_cells": clean,
            "column_consistency": round(consistency, 4),
            "words": inside, "split_words": split,
            "split_rate": round(split / inside, 4) if inside else 0.0,
            "score": round(clean * consistency ** 2, 3)}


def _table_cell_value(text: str) -> dict[str, Any]:
    """A table cell's value, cleaned EXACTLY as a form value is (B4 fix 3).

    "___@ X__" in a cell used to reach the value with its underscore runs;
    a run, "*", "By <party>" or "TBA" in a cell is a blank with its marker,
    the same evidence rule `_parse_form_value` applies to forms. An EMPTY
    cell keeps `is_blank=True` with NO marker - it is not evidence of a
    blank field, and `read_page_rows` does not emit it. A cell that is only
    a printed unit keeps the plain unit split it always had.
    """
    if not text:
        return {"value": None, "unit": None, "is_blank": True, "blank_marker": None}
    parsed = _parse_form_value(text)
    if parsed["unit_only"]:
        plain = split_value_unit(text)
        return {"value": plain["value"], "unit": plain["unit"], "is_blank": False,
                "blank_marker": None}
    return {"value": parsed["value"], "unit": parsed["unit"],
            "is_blank": parsed["is_blank"], "blank_marker": parsed["blank_marker"],
            "condition": parsed.get("condition"), "note": parsed.get("note")}


def _structure(table: Any, *, page_no: int, table_id: str, strategy: str,
               grid: tuple | None = None) -> dict[str, Any]:
    texts, rects = grid or _grid(table)
    nrows, ncols = len(texts), (len(texts[0]) if texts else 0)
    spans = _column_spans(rects, ncols)
    gutter = _gutter_columns(texts)
    usable = [spans[j] for j in range(ncols) if j not in gutter and spans[j][1] > spans[j][0]]
    x_left = min((s[0] for s in usable), default=table.bbox[0])
    x_right = max((s[1] for s in usable), default=table.bbox[2])

    first_data = next((i for i in range(nrows)
                       if not _is_empty(texts[i], gutter) and _is_data_like(texts[i], gutter)),
                      None)
    title_rows: list[int] = []
    if first_data is not None:
        # HEADER = the non-title rows directly above the first data-like row
        # (empty rows on the way are skipped, never kept). Walking up stops at
        # the first title row; it and everything above it is preamble and is
        # dropped.
        rule = "rows above first data-like row"
        header: list[int] = []
        i = first_data - 1
        while i >= 0 and not _is_title_row(rects[i], texts[i], gutter, x_left, x_right):
            if not _is_empty(texts[i], gutter):
                header.insert(0, i)
            i -= 1
        title_rows = [r for r in range(0, i + 1) if not _is_empty(texts[r], gutter)]
        body_start = first_data
        if len(header) > MAX_HEADER_ROWS:
            rule = (f"none: {len(header)} rows above the first data-like row "
                    f"exceed MAX_HEADER_ROWS={MAX_HEADER_ROWS}")
            header, title_rows, body_start = [], [], nrows
    else:
        # No data-like row: the first non-empty non-title row is the header.
        rule = "fallback: first non-title row"
        header = []
        body_start = nrows
        for i in range(nrows):
            if _is_empty(texts[i], gutter):
                continue
            if not header and _is_title_row(rects[i], texts[i], gutter, x_left, x_right):
                title_rows.append(i)
                continue
            header = [i]
            body_start = i + 1
            break

    labels = _header_labels(header, rects, texts, spans, gutter)

    data_rows: list[dict[str, Any]] = []
    empty_rows = 0
    trailing_rows: list[int] = []
    gap = False
    for r in range(body_start, nrows):
        if _is_empty(texts[r], gutter):
            empty_rows += 1
            gap = bool(data_rows)
            continue
        if gap and not _is_data_like(texts[r], gutter):
            # A block after an empty gap that is not data (a title block or
            # footer) ends the table body.
            trailing_rows = [x for x in range(r, nrows) if not _is_empty(texts[x], gutter)]
            break
        gap = False
        cells = []
        for j, label in labels.items():
            text = texts[r][j]
            cells.append({
                "source": "table", "page": page_no, "table_id": table_id,
                "row": r, "column": j, "label": label, "text": text,
                **_table_cell_value(text), "bbox": _bbox(rects[r][j]),
            })
        data_rows.append({"row": r, "cells": cells})

    return {
        "source": "table", "page": page_no, "table_id": table_id,
        "strategy": strategy, "bbox": _bbox(table.bbox),
        "grid": [nrows, ncols], "gutter_columns": sorted(gutter),
        "header_rule": rule, "header_rows": header, "header_row_count": len(header),
        "labels": [labels[j] for j in sorted(labels)],
        "label_columns": sorted(labels),
        "title_rows": [" | ".join(v for v in texts[r] if v) for r in title_rows],
        "dropped_empty_rows": empty_rows,
        "trailing_rows": len(trailing_rows),
        "rows": data_rows,
    }


STRATEGIES = ("lines", "text")


def read_tables(page: Any) -> dict[str, Any]:
    """Read every table on `page` with the better of the two strategies.

    page_score = sum of `table_score` over the tables a strategy finds. The
    higher page score wins; a tie goes to "lines", whose cells come from
    drawn rules rather than guessed from text alignment.
    """
    page_no = page.number + 1
    words = page.get_text("words")
    found: dict[str, list[Any]] = {}
    scores: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        try:
            tables = list(page.find_tables(strategy=strategy).tables)
        except Exception as exc:  # a strategy that crashes simply loses
            tables = []
            scores[strategy] = {"score": 0.0, "tables": 0, "error": type(exc).__name__}
            found[strategy] = tables
            continue
        grids = [_grid(t) for t in tables]  # extract() is the slow part: once
        per = [table_score(t, words, g) for t, g in zip(tables, grids)]
        found[strategy] = list(zip(tables, grids))
        scores[strategy] = {"score": round(sum(p["score"] for p in per), 3),
                            "tables": len(tables), "per_table": per}
    winner = max(STRATEGIES, key=lambda s: (scores[s]["score"], s == "lines"))
    tables = [_structure(t, page_no=page_no, table_id=f"p{page_no}-t{i + 1}",
                         strategy=winner, grid=g)
              for i, (t, g) in enumerate(found[winner])]
    return {"source": "table", "page": page_no, "strategy": winner,
            "score": scores[winner]["score"], "scores": scores, "tables": tables}


# --------------------------------------------------------------------------
# Forms
# --------------------------------------------------------------------------

#: A value to the right must start within this share of the page width of
#: the label's right edge.
FORM_MAX_GAP_SHARE = 0.45
#: A unit in its own phrase attaches to a numeric value within this gap (pt).
FORM_UNIT_GAP = 80.0
#: An empty underscore run proves THIS label's field is blank only when it
#: starts within this gap (pt) of the label; farther away it belongs to
#: another column (two-column API forms put a column break about 230 pt away).
FORM_BLANK_NEAR = 120.0


def _visual_lines(words: list[tuple]) -> list[list[tuple]]:
    heights = [w[3] - w[1] for w in words] or [10.0]
    tol = max(2.0, 0.3 * statistics.median(heights))
    lines: list[tuple[float, list[tuple]]] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - yc) <= tol:
            lines[-1][1].append(w)
        else:
            lines.append((yc, [w]))
    return [sorted(ws, key=lambda w: w[0]) for _yc, ws in lines]


def _phrases(line: list[tuple]) -> list[list[tuple]]:
    """Words of one visual line grouped where the gap is word-spacing sized."""
    out: list[list[tuple]] = []
    for w in line:
        h = w[3] - w[1]
        if out and w[0] - out[-1][-1][2] <= max(6.0, 0.8 * h):
            out[-1].append(w)
        else:
            out.append([w])
    return out


def _segment(ws: list[tuple], kind: str, cue: str | None = None) -> dict[str, Any]:
    x0 = min(w[0] for w in ws); y0 = min(w[1] for w in ws)
    x1 = max(w[2] for w in ws); y1 = max(w[3] for w in ws)
    text = " ".join(w[4] for w in ws)
    if kind == "text" and _CLAUSE_REF.match(text):
        kind = "qualifier"
    return {"kind": kind, "cue": cue, "text": text, "bbox": (x0, y0, x1, y1),
            "yc": (y0 + y1) / 2, "h": y1 - y0}


def _split_phrase(ws: list[tuple]) -> list[dict[str, Any]]:
    """Cut a phrase into label and text segments.

    * A word ending with ":" closes a LABEL; parenthesised words right after
      it (clause references, qualifiers) belong to the label.
    * A word starting with "_" opens an underscore FIELD; plain text before it
      in the same phrase is a LABEL (the form-field cue), unless that text is
      itself the value of a ":" label or already holds a field.
    """
    out: list[dict[str, Any]] = []
    buf: list[tuple] = []
    after_colon = False
    i = 0
    while i < len(ws):
        word = ws[i][4]
        if word.endswith(":") and not word.startswith("_"):
            buf.append(ws[i])
            i += 1
            if i < len(ws) and ws[i][4].startswith("("):
                while i < len(ws):
                    buf.append(ws[i])
                    i += 1
                    if buf[-1][4].endswith(")"):
                        break
            out.append(_segment(buf, "label", "colon"))
            buf, after_colon = [], True
            continue
        if (word.startswith("_") and buf and not after_colon
                and not any(b[4].startswith("_") for b in buf)
                and _has_letter(" ".join(b[4] for b in buf))):
            out.append(_segment(buf, "label", "field"))
            buf = []
        buf.append(ws[i])
        i += 1
    if buf:
        out.append(_segment(buf, "text"))
    return out


#: Words a printed UNIT LABEL is made of ("bar a (psia)", "m3/h", "KJ / Kg - K",
#: "(USGPM)", "OC ( OF)"). Units are universal, not document-specific; a
#: text made only of these (and brackets, slashes, dashes) is a unit label.
_UNIT_WORDS = frozenset("""
bar bara barg a g psi psia psig kpa kpag mpa mpag pa atm mbar mmhg mmh2o inh2o
c f k oc of degc degf deg
m mm cm km ft in inch inches nps
m3 m3h h hr s min sec l lit litre liter gpm usgpm igpm bpd bbl
kg g lb lbs t ton tonne kgm3 kj kw w mw hp bhp kwh kva kv v a hz rpm
cp cst mpas ppm ppmw ppmv wt vol mol pct db dba sg api
m2 m3 mm2 cm3 ft2 ft3 nm3 sm3
""".split())
#: A printed marker meaning "not filled here": the API legend's "*" (to be
#: advised), "By <party>", "(Note 3)" / "[Note - 3]", TBA / TBC / TBD.
_BLANK_MARKER = re.compile(
    r"^(?:\*|by\s+[a-z][\w\s/&.-]*|[\[(]?\s*note\s*[-–—]?\s*\d+\s*[\])]?|tb[acd]|later)$",
    re.IGNORECASE)
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})
_RANGE = re.compile(rf"^(?P<a>{_NUM})\s*-\s*(?P<b>{_NUM})\s*(?P<u>.*)$")
_PAREN_UNIT = re.compile(r"^(?P<v>.*?\S)\s*\((?P<u>[^()]+)\)$")
_NUM_REST = re.compile(rf"^(?P<n>[<>~]?\s*{_NUM})\s+(?P<u>\S.*)$")
#: A drawn field with its answer inside and text AFTER the closing run:
#: "_ YES_ <HRC 25" -> inside "YES", after "<HRC 25". The text must open with
#: a run; "10 barg" or "__ISO 15156 -1" (no closing run) never match.
_ENCLOSED_FIELD = re.compile(
    r"^\s*_+\s*(?P<inside>[^_]*[^\W_][^_]*?)\s*_+\s*(?P<after>[^_]*?)\s*_*\s*$")


#: Alone, these are a letter or an English word ("GRADE: C", "A", "in").
_AMBIGUOUS_UNIT_WORDS = frozenset("a c f g k m s t l v w h in".split())


def is_unit_label(text: str | None, *, allow_single: bool = False) -> bool:
    """True when `text` is only a printed unit label - no value in it. Text
    made only of ambiguous single letters ("C", "A") is NOT a unit label
    unless `allow_single` (e.g. right after a '*' marker: "* m")."""
    words = [w for w in re.split(r"[\s()/\-·.,°º\[\]]+", (text or "").lower()) if w]
    if not words or not all(w in _UNIT_WORDS for w in words):
        return False
    return allow_single or not all(w in _AMBIGUOUS_UNIT_WORDS for w in words)


def _unit_of(text: str) -> str:
    """A unit label without its bracketed alternative: 'bar a (psia)' -> 'bar a'."""
    main = re.sub(r"\([^()]*\)", " ", text).strip()
    return re.sub(r"\s+", " ", main or text.strip("() ")).strip()


def _parse_value(text: str) -> dict[str, Any]:
    """A filled value: number + unit, range, bracketed unit, '@ condition'."""
    head, _, cond = text.partition("@")
    head = head.strip().translate(_DASHES)
    condition = f"@{cond}".strip() if cond else None
    m = _RANGE.match(head)
    if m and (not m.group("u") or is_unit_label(m.group("u"), allow_single=True)):
        return {"value": f"{m.group('a').strip()} - {m.group('b').strip()}",
                "unit": _unit_of(m.group("u")) or None, "condition": condition}
    m = _PAREN_UNIT.match(head)
    if m and is_unit_label(m.group("u")) and not is_unit_label(m.group("v")):
        head_value = split_value_unit(m.group("v"))
        return {"value": head_value["value"], "unit": _unit_of(m.group("u")), "condition": condition}
    parsed = split_value_unit(head)
    if parsed["unit"] is None:
        m = _NUM_REST.match(head)
        if m and is_unit_label(m.group("u"), allow_single=True):
            return {"value": re.sub(r"\s+", "", m.group("n")), "unit": _unit_of(m.group("u")),
                    "condition": condition}
    return {"value": parsed["value"], "unit": parsed["unit"], "condition": condition}


def _parse_form_value(text: str) -> dict[str, Any]:
    """Decide blank / unit-only / value - and NEVER call a field blank
    without evidence (addendum 3.7: not found is not blank).

    * BLANK needs evidence: an underscore or dash run (the drawn empty
      field), or a printed marker ("*", "By EPC", "(Note 3)").
    * UNIT ONLY ("cP", "bar a (psia)") with no run: the printed unit column.
      That is NOT a value and NOT proof of blank - `unit_only` = True, the
      value is missing and the caller must not report it as either.
    """
    had_run = bool(_BLANK_RUN.search(text))
    residue = re.sub(r"\s+", " ", _BLANK_RUN.sub(" ", text)).strip()
    star = re.match(r"^\*\s*(?P<rest>.*)$", residue)
    if star and (not star.group("rest") or is_unit_label(star.group("rest"), allow_single=True)):
        rest = star.group("rest")
        return {"value": None, "unit": None, "expected_units": [_unit_of(rest)] if rest else [],
                "is_blank": True, "blank_marker": "*", "unit_only": False, "condition": None}
    if residue and _BLANK_MARKER.match(residue):
        return {"value": None, "unit": None, "expected_units": [], "is_blank": True,
                "blank_marker": residue, "unit_only": False, "condition": None}
    parts = [x.strip() for x in residue.split("@")]
    unit_parts = [x for x in parts if x]
    units_only = bool(unit_parts) and all(is_unit_label(x) for x in unit_parts)
    if not re.search(r"[^\W_]", residue):
        # Nothing but a drawn run or printed punctuation ("-", "--", "/"):
        # the author's own mark for an empty field.
        return {"value": None, "unit": None, "expected_units": [], "is_blank": True,
                "blank_marker": residue or "______", "unit_only": False, "condition": None}
    if units_only:
        expected = [standalone_unit(x) or _unit_of(x) for x in unit_parts]
        if had_run:
            return {"value": None, "unit": expected[0] if len(expected) == 1 else None,
                    "expected_units": expected, "is_blank": True, "blank_marker": "______",
                    "unit_only": False, "condition": None}
        return {"value": None, "unit": None, "expected_units": expected, "is_blank": False,
                "blank_marker": None, "unit_only": True, "condition": None}
    note = None
    enclosed = _ENCLOSED_FIELD.match(text)
    if (enclosed and enclosed.group("after") and "@" not in enclosed.group("after")
            and not is_unit_label(enclosed.group("after"), allow_single=True)):
        # B4 FIX 2: THE FIELD IS WHAT THE RUNS ENCLOSE. "_ YES_ <HRC 25" is the
        # answer "YES" written inside its drawn field, then a note printed
        # after the field closes. The note is kept, apart - it is not the
        # value. A unit after the closing run ("_ -3__ OC") is still the
        # value's unit and never takes this branch.
        residue, note = enclosed.group("inside").strip(), enclosed.group("after").strip()
    parsed = _parse_value(residue)
    if parsed["value"] is None:
        # B4 FIX 3: a value that is ONLY a condition ("___@ SUPPLIERS__") is
        # still what the field says; before, the caller fell back to the raw
        # text with its underscore runs.
        parsed = {**parsed, "value": residue, "condition": None}
    return {**parsed, "expected_units": [], "is_blank": False, "blank_marker": None,
            "unit_only": False, "note": note}


def _label_name(text: str) -> str:
    """The label without its colon or a leading checkbox/bullet glyph."""
    name = re.sub(r"\s*:\s*(?=\(|$)", " ", text).strip()
    return re.sub(r"^[^\w(]+", "", name).strip()


def _label_like(seg: dict[str, Any]) -> bool:
    """A text segment ending in a clause reference reads as a label, not a value."""
    return bool(re.search(r"\(\s*[\d.]+[a-z.]*\s*\)\s*$", seg["text"]))


_DRAWN_RUN = re.compile(r"_{2,}")


def _label_line_has_run(segs: list[dict[str, Any]], lab: dict[str, Any]) -> bool:
    """The label's own line carries a drawn underscore field to its right,
    before any other label: this form draws its fields as runs."""
    tol = 0.6 * lab["h"]
    right = sorted((s for s in segs if s is not lab and abs(s["yc"] - lab["yc"]) <= tol
                    and s["bbox"][0] >= lab["bbox"][2] - 1.0),
                   key=lambda s: s["bbox"][0])
    for s in right:
        if s["kind"] == "label":
            return False
        if _DRAWN_RUN.search(s["text"]):
            return True
    return False


def _heads_a_field(segs: list[dict[str, Any]], cand: dict[str, Any]) -> bool:
    """`cand` has a drawn field (a segment opening with "_") on the NEXT line,
    left-aligned with it: `cand` is that field's label, not a value."""
    if _DRAWN_RUN.search(cand["text"]):
        return False  # a drawn field is a field, not a label
    return any(s is not cand and s["text"].startswith("_")
               and 0.6 * cand["h"] < s["yc"] - cand["yc"] <= 1.8 * cand["h"]
               and abs(s["bbox"][0] - cand["bbox"][0]) <= cand["h"]
               for s in segs)


def _below_candidates(segs: list[dict[str, Any]], lab: dict[str, Any], used: set[int]) -> list[int]:
    """Text directly under the label that can be its value.

    B4 FIX 4 - a heading, a section title or the next field's label is not a
    value. Two generic, geometric proofs:

    * RUN FORM: when the label's own line draws its field as an underscore
      run, a value below must itself be a filled run ("___BEARING HOUSING___").
      Plain text under such a label is the next row's label or a heading.
    * FIELD HEAD: text that has its own drawn field directly beneath it is
      that field's label.
    """
    lx0 = lab["bbox"][0]
    run_form = _label_line_has_run(segs, lab)
    aligned = sorted((k for k, s in enumerate(segs)
                      if s is not lab
                      and 0.6 * lab["h"] < s["yc"] - lab["yc"] <= 2.2 * lab["h"]
                      and abs(s["bbox"][0] - lx0) <= lab["h"]),
                     key=lambda k: segs[k]["yc"])
    # ONLY THE NEAREST aligned segment can be the value: a label or heading
    # between the label and a lower field means that field is someone else's.
    return [k for k in aligned[:1]
            if segs[k]["kind"] == "text" and k not in used
            and not _label_like(segs[k])
            and (not run_form or _DRAWN_RUN.search(segs[k]["text"]))
            and not _heads_a_field(segs, segs[k])]


#: B4 FIX 1: a value ending with a connector, or with a word that cannot end a
#: phrase, is cut by a line wrap. English function words and list connectors -
#: generic, not document vocabulary.
_OPEN_ENDING = re.compile(
    r"(?:[&,/+]|\b(?:and|or|of|the|a|an|to|on|in|for|with|at|by|from|per|as|than))\s*$",
    re.IGNORECASE)
#: How many wrapped lines one value may continue onto.
MAX_CONTINUATION_LINES = 3


def _continuation(segs: list[dict[str, Any]], lab: dict[str, Any], val: dict[str, Any],
                  used: set[int], text: str) -> int | None:
    """The segment on the next line that continues `val`, or None.

    B4 FIX 1 - A WRAPPED VALUE. Taken only when ALL hold:
    * it is on the next visual line (0.6-1.8 x the value's height below);
    * it lies in this field's band: starts at or right of the label's left
      edge, not right of the value's right edge, and nothing else on its line
      sits between the label's left edge and it (else it belongs to its own
      label);
    * it is plain text, not a label, not a blank run, not a unit alone;
    * AND the value is visibly unfinished (ends with "&", ",", "/", "+" or a
      function word), OR the segment is indented wholly under the value.
    """
    h = val["h"]
    band_x0 = lab["bbox"][0] - 1.0
    open_end = bool(_OPEN_ENDING.search(text))
    for k, s in sorted(enumerate(segs), key=lambda ks: ks[1]["yc"]):
        if k in used or s is val or s["kind"] != "text" or _label_like(s):
            continue
        if not 0.6 * h < s["yc"] - val["yc"] <= 1.8 * h:
            continue
        x0, x1 = s["bbox"][0], s["bbox"][2]
        if x0 < band_x0 or x0 > val["bbox"][2] or x1 > val["bbox"][2] + 2 * h:
            continue
        if any(o is not s and abs(o["yc"] - s["yc"]) <= 0.6 * h
               and o["bbox"][2] > band_x0 and o["bbox"][0] < val["bbox"][2] + 2 * h
               for o in segs):
            continue  # its line has something else in this band: its own field
        parsed = _parse_form_value(s["text"])
        if parsed["is_blank"] or parsed["unit_only"]:
            continue
        indented = x0 >= val["bbox"][0] - 1.0 and x1 <= val["bbox"][2] + 1.0
        if open_end or indented:
            return k
    return None


def _filled_below(segs: list[dict[str, Any]], lab: dict[str, Any], used: set[int]) -> bool:
    return any(not _parse_form_value(segs[k]["text"])["is_blank"]
               and not _parse_form_value(segs[k]["text"])["unit_only"]
               for k in _below_candidates(segs, lab, used))


def read_form(page: Any) -> dict[str, Any]:
    """Pair form labels with values by word position.

    RIGHT: the first segment to the right of the label on the same baseline
    (centres within 0.6 x label height), skipping clause references, before
    the next label and within FORM_MAX_GAP_SHARE of the page width. A numeric
    value followed by a unit-only segment takes that unit.
    BELOW: only when nothing is to the right - the nearest text segment on
    the next lines (within 2.2 x label height) whose left edge aligns with the
    label's (within one label height) and which is not itself label-like.
    """
    page_no = page.number + 1
    words = [w for w in page.get_text("words") if w[4].strip()]
    segs: list[dict[str, Any]] = []
    for line in _visual_lines(words):
        line_segs: list[dict[str, Any]] = []
        for phrase in _phrases(line):
            line_segs.extend(_split_phrase(phrase))
        # FIELD CUE ACROSS PHRASES: text followed on its line by an underscore
        # field is that field's label - unless the text is itself the value of
        # the label (or clause reference) just before it.
        for n in range(len(line_segs) - 1):
            a, b = line_segs[n], line_segs[n + 1]
            if (a["kind"] == "text" and _has_letter(a["text"])
                    and not a["text"].startswith("_") and b["text"].startswith("_")
                    and not (n > 0 and line_segs[n - 1]["kind"] in ("label", "qualifier"))):
                a["kind"], a["cue"] = "label", "field"
        segs.extend(line_segs)
    max_gap = FORM_MAX_GAP_SHARE * page.rect.width
    used: set[int] = set()
    pairs: list[dict[str, Any]] = []
    unpaired: list[dict[str, Any]] = []
    for li, lab in enumerate(segs):
        if lab["kind"] != "label":
            continue
        lx0, _ly0, lx1, _ly1 = lab["bbox"]
        tol = 0.6 * lab["h"]
        right = sorted((k for k, s in enumerate(segs)
                        if k != li and abs(s["yc"] - lab["yc"]) <= tol
                        and s["bbox"][0] >= lx1 - 1.0),
                       key=lambda k: segs[k]["bbox"][0])
        value_k = unit_k = None
        position = None
        prev_x1 = lx1
        for n, k in enumerate(right):
            s = segs[k]
            if s["bbox"][0] - prev_x1 > max_gap or s["kind"] == "label":
                break
            if s["kind"] == "qualifier":
                prev_x1 = s["bbox"][2]
                continue
            if k in used or _label_like(s):
                break
            if (s["bbox"][0] - lx1 > FORM_BLANK_NEAR
                    and _parse_form_value(s["text"])["is_blank"]
                    and _filled_below(segs, lab, used)):
                # A FAR empty run while a FILLED field sits right below the
                # label: the run is another column's field (two-column API
                # forms); the value below is this label's.
                break
            value_k, position = k, "right"
            if n + 1 < len(right):
                nxt = segs[right[n + 1]]
                if nxt["kind"] == "text" and standalone_unit(nxt["text"]) and \
                        nxt["bbox"][0] - s["bbox"][2] <= FORM_UNIT_GAP:
                    unit_k = right[n + 1]
            break
        if value_k is None:
            below = _below_candidates(segs, lab, used)
            if below:
                value_k, position = below[0], "below"
        if value_k is None:
            unpaired.append({"source": "form", "page": page_no, "label": lab["text"],
                             "label_bbox": _bbox(lab["bbox"])})
            continue
        val = segs[value_k]
        val_text = val["text"]
        val_box = val["bbox"]
        parsed = _parse_form_value(val_text)
        if unit_k is None and not parsed["is_blank"] and not parsed["unit_only"]:
            # B4 FIX 1: a value wrapped onto the next line(s) of its band.
            tail = val
            for _n in range(MAX_CONTINUATION_LINES):
                cont_k = _continuation(
                    # The band is the FIRST line's x-range, every time: a
                    # wide wrapped line must not widen what "indented under
                    # the value" means for the line after it.
                    segs, lab, {**tail, "bbox": (val["bbox"][0], tail["bbox"][1],
                                                 val["bbox"][2], tail["bbox"][3])},
                    used | {value_k}, val_text)
                if cont_k is None:
                    break
                used.add(cont_k)
                tail = segs[cont_k]
                val_text = f"{val_text} {tail['text']}"
                val_box = (min(val_box[0], tail["bbox"][0]), val_box[1],
                           max(val_box[2], tail["bbox"][2]), tail["bbox"][3])
            if val_text != val["text"]:
                parsed = _parse_form_value(val_text)
        if parsed["unit_only"] and unit_k is None:
            # The printed unit column: neither a value nor proof of blank.
            unpaired.append({"source": "form", "page": page_no, "label": lab["text"],
                             "label_bbox": _bbox(lab["bbox"]), "reason": "unit label only",
                             "expected_units": parsed["expected_units"]})
            continue
        used.add(value_k)
        unit_text = None
        if unit_k is not None and parsed["unit"] is None and parsed["value"] is not None:
            used.add(unit_k)
            unit_text = segs[unit_k]["text"]
            parsed["unit"] = standalone_unit(unit_text)
        pairs.append({
            "source": "form", "page": page_no,
            "label": _label_name(lab["text"]),
            "label_text": lab["text"], "label_cue": lab["cue"],
            "label_bbox": _bbox(lab["bbox"]),
            "value_text": val_text if unit_text is None else f"{val_text} {unit_text}",
            "value": parsed["value"], "unit": parsed["unit"],
            "is_blank": parsed["is_blank"], "blank_marker": parsed["blank_marker"],
            "condition": parsed["condition"], "note": parsed.get("note"),
            "expected_units": parsed["expected_units"], "position": position,
            "value_bbox": _bbox(val_box if unit_k is None else (
                val["bbox"][0], min(val["bbox"][1], segs[unit_k]["bbox"][1]),
                segs[unit_k]["bbox"][2], max(val["bbox"][3], segs[unit_k]["bbox"][3]))),
        })
    return {"source": "form", "page": page_no, "pairs": pairs,
            "unpaired_labels": unpaired}


# --------------------------------------------------------------------------
# One page, as rows (the shape `datasheets.extract_facts` writes when the
# `geometry_reader_enabled` flag is on)
# --------------------------------------------------------------------------

def _row_key(row: dict[str, Any]) -> tuple:
    """Two rows are ONE reading when page, label and answer agree: the label
    lowercased with punctuation and spacing folded, the value folded, and a
    blank keyed by being blank."""
    label = re.sub(r"\s+", " ", re.sub(r"[^\w\s/]", " ", row["label"] or "")).strip().lower()
    answer = ("<blank>" if row["is_blank"]
              else re.sub(r"\s+", " ", f"{row['value'] or ''} {row['unit'] or ''}").strip().lower())
    return row["page"], label, answer


def read_page_rows(page: Any, *, form: dict[str, Any] | None = None,
                   tables: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every label/value the two readers found on `page`, one row each.

    FORM pairs as `read_form` pairs them. TABLE cells labelled "<row key>
    <column label>", the row key being the row's first filled cell (a tag or
    mark such as N1) - which is itself not emitted. An EMPTY table cell is
    not emitted: an empty cell is not evidence of a blank field (addendum
    3.7; `datasheets.extract_facts` makes the same rule for its readers).

    DE-DUPLICATED (B4): a second row with the same page, label and answer as
    an earlier one is the same reading twice and is dropped - the first one,
    in reading order, keeps its provenance.

    Every row keeps where it came from: `source` ("form" / "table"), the
    value's box and the label's box (forms), and table id / row / column /
    column label (tables).
    """
    form = form if form is not None else read_form(page)
    tables = tables if tables is not None else read_tables(page)
    rows: list[dict[str, Any]] = []
    for p in form["pairs"]:
        rows.append({
            "source": "form", "page": p["page"], "label": p["label"],
            "label_text": p["label_text"], "value_text": p["value_text"],
            "value": p["value"], "unit": p["unit"], "is_blank": p["is_blank"],
            "blank_marker": p["blank_marker"], "condition": p["condition"],
            "note": p.get("note"), "bbox": p["value_bbox"],
            "label_bbox": p["label_bbox"], "position": p["position"],
            "table_id": None, "row": None, "column": None, "column_label": None,
        })
    for table in tables["tables"]:
        for data in table["rows"]:
            cells = sorted(data["cells"], key=lambda c: c["column"])
            key_cell = next((c for c in cells if c["text"]), None)
            if key_cell is None or not re.search(r"[^\W_]", key_cell["text"]):
                # A row whose first filled cell is a mark ("*", "-") has no
                # key: its cells cannot be told apart from another row's.
                continue
            for c in cells:
                if c is key_cell or not c["text"]:
                    continue
                rows.append({
                    "source": "table", "page": c["page"],
                    "label": f"{key_cell['text']} {c['label']}".strip(),
                    "label_text": c["label"], "value_text": c["text"],
                    "value": c["value"], "unit": c["unit"], "is_blank": c["is_blank"],
                    "blank_marker": c["blank_marker"], "condition": c.get("condition"),
                    "note": c.get("note"), "bbox": c["bbox"], "label_bbox": None,
                    "position": None, "table_id": c["table_id"], "row": c["row"],
                    "column": c["column"], "column_label": c["label"],
                })
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for row in rows:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
