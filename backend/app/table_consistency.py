"""Internal consistency of a numeric table (W5b-07, #531).

A numeric reference table can be wrong inside itself: two bands that overlap, a
band whose upper end is below its lower end, a Total that is not the sum, a
column defined as "A = B x C" whose cells are not B times C. None of that needs
another document to find. This module checks exactly that, on the tables the
parser (`tables.py`) already reads, and states what it found WITH WHERE:
the page, the chunk, the data rows and the cells' own text, so an engineer can
open the table and see it.

WHAT IT DOES NOT SAY. It never says a table is "consistent". It says which
checks it could run on it and which found nothing; a table with no band, total
or declared formula in it ran no check, and that is reported as such (a
silent pass would be a claim). A table the parser could not read is counted as
unparsed, never as clean.

ROUNDING IS NOT AN ERROR. A printed total is the sum of printed, rounded terms:
10.2 + 5.3 = 15.5, printed "15.5", is right, and so is a printed "15.6" when the
terms were 10.24 and 5.33 and rounded for display. The allowed difference is
the sum of the half-units of the last printed digit of every number involved,
no more and no less, so a real error one unit off in the last digit of the
coarsest number is not hidden.

Pure functions over rows of text. No database, no network, no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import numparse

#: Header words naming the low and high end of a band, in pairs.
_BAND_PAIRS = (
    ("from", "to"), ("min", "max"), ("minimum", "maximum"), ("lower", "upper"),
    ("low", "high"), ("start", "end"), ("over", "up to"), ("above", "not over"),
)
_TOTAL_WORD = re.compile(r"^(?:grand\s+)?(?:total|sum|subtotal)\b", re.IGNORECASE)
_SUBTOTAL_WORD = re.compile(r"^subtotal\b", re.IGNORECASE)
#: A cell made only of digits and separators. The VALUE is numparse's (#616: the
#: project reads numbers one way); this only gates what counts as a plain cell.
_PLAIN_CELL = re.compile(r"^[-+]?\d[\d.,]*$")
_RANGE = re.compile(
    r"^\s*(?P<lo>[-+]?\d+(?:\.\d+)?)\s*(?:–|—|to|-)\s*(?P<hi>[-+]?\d+(?:\.\d+)?)"
    r"\s*[A-Za-z%°/]*\s*$")
_FORMULA = re.compile(
    r"^(?P<name>[^=]+?)\s*=\s*(?P<a>.+?)\s*(?P<op>\s[x×*/÷+\-]\s|[×*/÷+])\s*(?P<b>.+)$")


@dataclass(frozen=True)
class Num:
    """A number read from a cell, with the precision it was printed to."""

    value: float
    decimals: int
    raw: str

    @property
    def half_unit(self) -> float:
        return 0.5 * 10 ** (-self.decimals)


def read_number(cell: str | None) -> Num | None:
    """A plain number in a cell, or None. "1,250.5" is 1250.5; "12 mm" and
    "10-20" are not plain numbers (a unit or a range is a different reading).
    The value is `numparse.parse_value`'s, so a decimal comma and a thousands
    group are read the way the rest of the system reads them."""
    text = numparse.normalise_text((cell or "").strip())
    if not text or not _PLAIN_CELL.match(text):
        return None
    value = numparse.parse_value(text)
    if value is None:
        return None
    if "." in text:
        decimals = len(text.rsplit(".", 1)[1].replace(",", ""))
    elif "," in text and value != int(value):       # a decimal comma: "10,5"
        decimals = len(text.rsplit(",", 1)[1])
    else:                                            # whole, or a thousands comma: "1,250"
        decimals = 0
    return Num(value, decimals, (cell or "").strip())


def _fold_header(text: str) -> str:
    """A header without its unit in brackets, folded: "Mass (kg)" -> "mass"."""
    return numparse.fold(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text or "")).strip()


def _finding(kind: str, message: str, *, rows: list[int], columns: list[str],
             cells: list[str], page: int | None, chunk_id: str | None) -> dict:
    return {"kind": kind, "message": message, "rows": rows, "columns": columns,
            "cells": cells, "page": page, "chunk_id": chunk_id,
            "status": "needs_engineer_review"}


def _step(*nums: Num) -> float:
    return 10 ** (-max(n.decimals for n in nums))


# ------------------------------------------------------------------- bands

def _band_rows(header: list[str], data: list[list[str]]):
    """[(label, [(row_index_1based, lo Num, hi Num)])]: every band column pair
    (from/to, min/max ...) and every column of written ranges ("10-20")."""
    folded = [_fold_header(h) for h in header]
    out = []
    for lo_word, hi_word in _BAND_PAIRS:
        for lo_i, lo_h in enumerate(folded):
            if lo_h != lo_word:
                continue
            for hi_i, hi_h in enumerate(folded):
                if hi_h != hi_word or hi_i == lo_i:
                    continue
                bands = []
                for r, row in enumerate(data, start=1):
                    lo = read_number(row[lo_i] if lo_i < len(row) else "")
                    hi = read_number(row[hi_i] if hi_i < len(row) else "")
                    if lo is not None and hi is not None:
                        bands.append((r, lo, hi))
                if len(bands) >= 2:
                    out.append((f"{header[lo_i]} / {header[hi_i]}", bands))
    for col, name in enumerate(header):
        bands = []
        for r, row in enumerate(data, start=1):
            cell = numparse.normalise_text((row[col] if col < len(row) else "") or "")
            m = _RANGE.match(cell)
            if m and read_number(cell) is None:
                lo_raw, hi_raw = m.group("lo"), m.group("hi")
                bands.append((r, read_number(lo_raw), read_number(hi_raw)))
        bands = [b for b in bands if b[1] is not None and b[2] is not None]
        if len(bands) >= 2:
            out.append((name, bands))
    return out


def check_bands(header, data, *, page, chunk_id) -> tuple[list[dict], int]:
    findings, ran = [], 0
    for label, bands in _band_rows(header, data):
        ran += 1
        for r, lo, hi in bands:
            if lo.value > hi.value:
                findings.append(_finding(
                    "band_inverted",
                    f"In '{label}', row {r} runs from {lo.raw} to {hi.raw}: the low end is above the high end.",
                    rows=[r], columns=[label], cells=[lo.raw, hi.raw], page=page, chunk_id=chunk_id))
        ordered = sorted((b for b in bands if b[1].value <= b[2].value), key=lambda b: b[1].value)
        for (r1, lo1, hi1), (r2, lo2, hi2) in zip(ordered, ordered[1:]):
            if lo2.value < hi1.value:
                findings.append(_finding(
                    "band_overlap",
                    f"In '{label}', rows {r1} and {r2} overlap: {lo1.raw} to {hi1.raw} and {lo2.raw} to {hi2.raw}.",
                    rows=[r1, r2], columns=[label], cells=[lo1.raw, hi1.raw, lo2.raw, hi2.raw],
                    page=page, chunk_id=chunk_id))
            elif lo2.value == hi1.value:
                findings.append(_finding(
                    "band_shared_boundary",
                    f"In '{label}', rows {r1} and {r2} both include {hi1.raw}: the boundary belongs to two bands.",
                    rows=[r1, r2], columns=[label], cells=[hi1.raw, lo2.raw], page=page, chunk_id=chunk_id))
            elif lo2.value - hi1.value > _step(hi1, lo2) * 1.0000001:
                findings.append(_finding(
                    "band_gap",
                    f"In '{label}', nothing covers {hi1.raw} to {lo2.raw} between rows {r1} and {r2}.",
                    rows=[r1, r2], columns=[label], cells=[hi1.raw, lo2.raw], page=page, chunk_id=chunk_id))
    return findings, ran


# ------------------------------------------------------------------ totals

def check_totals(header, data, *, page, chunk_id) -> tuple[list[dict], int]:
    findings, ran = [], 0
    # A Total COLUMN: equals the numbers to its left in the same row, when every
    # cell between the label and the total is a plain number.
    for col, name in enumerate(header):
        if col < 2 or not _TOTAL_WORD.match(name.strip()):
            continue
        for r, row in enumerate(data, start=1):
            total = read_number(row[col] if col < len(row) else "")
            terms = [read_number(row[c] if c < len(row) else "") for c in range(1, col)]
            if total is None or len(terms) < 2 or any(t is None for t in terms):
                continue
            ran += 1
            allowed = sum(t.half_unit for t in terms) + total.half_unit
            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:
                findings.append(_finding(
                    "total_column_mismatch",
                    f"Row {r}: '{name}' is {total.raw}, but the numbers to its left add up to "
                    f"{sum(t.value for t in terms):g}.",
                    rows=[r], columns=[name], cells=[t.raw for t in terms] + [total.raw],
                    page=page, chunk_id=chunk_id))
    # A Total ROW: each numeric column equals the numbers above it.
    start = 0
    for r, row in enumerate(data):
        label = (row[0] if row else "").strip()
        if not _TOTAL_WORD.match(label):
            continue
        for col in range(1, len(header)):
            total = read_number(row[col] if col < len(row) else "")
            terms = [read_number(d[col] if col < len(d) else "") for d in data[start:r]
                     if not _TOTAL_WORD.match((d[0] if d else "").strip())]
            terms = [t for t in terms if t is not None]
            if total is None or len(terms) < 2:
                continue
            ran += 1
            allowed = sum(t.half_unit for t in terms) + total.half_unit
            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:
                findings.append(_finding(
                    "total_row_mismatch",
                    f"The '{label}' row gives {total.raw} in '{header[col]}', but the rows above add up to "
                    f"{sum(t.value for t in terms):g}.",
                    rows=[r + 1], columns=[header[col]], cells=[t.raw for t in terms] + [total.raw],
                    page=page, chunk_id=chunk_id))
        if _SUBTOTAL_WORD.match(label):
            start = r + 1
    return findings, ran


# ---------------------------------------------------------------- formulas

_OPS = {
    "+": lambda a, b: a + b, "-": lambda a, b: a - b,
    "x": lambda a, b: a * b, "×": lambda a, b: a * b, "*": lambda a, b: a * b,
    "/": lambda a, b: a / b if b else None, "÷": lambda a, b: a / b if b else None,
}


def check_formulas(header, data, *, page, chunk_id) -> tuple[list[dict], int]:
    """A column whose own header states how it is derived: "Area = Width x Height"."""
    findings, ran = [], 0
    folded = {_fold_header(h): i for i, h in enumerate(header)}
    for col, name in enumerate(header):
        m = _FORMULA.match(name.strip())
        if not m:
            continue
        a_i, b_i = folded.get(_fold_header(m.group("a"))), folded.get(_fold_header(m.group("b")))
        op = m.group("op").strip()
        if a_i is None or b_i is None or op not in _OPS or col in (a_i, b_i):
            continue
        ran += 1
        for r, row in enumerate(data, start=1):
            cells = [read_number(row[i] if i < len(row) else "") for i in (a_i, b_i, col)]
            if any(c is None for c in cells):
                continue
            a, b, got = cells
            want = _OPS[op](a.value, b.value)
            if want is None:
                continue
            if op in "+-":
                allowed = a.half_unit + b.half_unit + got.half_unit
            else:     # relative rounding of the operands, absolute of the result
                rel = (a.half_unit / abs(a.value) if a.value else 0) + (b.half_unit / abs(b.value) if b.value else 0)
                allowed = abs(want) * rel + got.half_unit
            if abs(want - got.value) > allowed + 1e-12:
                findings.append(_finding(
                    "formula_mismatch",
                    f"Row {r}: '{name}' is {got.raw}, but {a.raw} {op} {b.raw} is {want:g}.",
                    rows=[r], columns=[name], cells=[a.raw, b.raw, got.raw], page=page, chunk_id=chunk_id))
    return findings, ran


# ------------------------------------------------------------ the entry points

def check_table(rows: list[list[str]], *, page: int | None = None,
                chunk_id: str | None = None) -> dict:
    """Run every check that applies to one table (header row first).

    Returns {"findings": [...], "checks_run": {...}}. `checks_run` counts the
    structures found to check (band columns, total cells, declared formulas);
    all zero means NOTHING WAS CHECKED, not that the table is consistent.
    """
    if len(rows) < 3:
        return {"findings": [], "checks_run": {"bands": 0, "totals": 0, "formulas": 0}}
    header, data = rows[0], rows[1:]
    b, nb = check_bands(header, data, page=page, chunk_id=chunk_id)
    t, nt = check_totals(header, data, page=page, chunk_id=chunk_id)
    f, nf = check_formulas(header, data, page=page, chunk_id=chunk_id)
    return {"findings": b + t + f, "checks_run": {"bands": nb, "totals": nt, "formulas": nf}}


def check_document(document_id: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """Every parsed table of one document, checked. Tables the parser could not
    read are counted as unparsed; tables with nothing to check are counted as
    such. Neither is ever reported as consistent."""
    from . import tables as tables_mod

    parses = tables_mod.parse_document_tables(document_id, allowed_document_ids=allowed_document_ids)
    findings: list[dict] = []
    totals = {"bands": 0, "totals": 0, "formulas": 0}
    checked = unparsed = nothing = 0
    for parse in parses:
        if not parse.parsed:
            unparsed += 1
            continue
        result = check_table(parse.rows, page=parse.page, chunk_id=parse.chunk_id)
        findings += result["findings"]
        for k, v in result["checks_run"].items():
            totals[k] += v
        if sum(result["checks_run"].values()) == 0:
            nothing += 1
        else:
            checked += 1
    if not parses:
        state = "no_tables"
    elif checked == 0:
        state = "nothing_checked"
    else:
        state = "ok"
    return {"document_id": document_id, "state": state, "tables_total": len(parses),
            "tables_checked": checked, "tables_unparsed": unparsed,
            "tables_with_nothing_to_check": nothing, "checks_run": totals,
            "findings": findings}
