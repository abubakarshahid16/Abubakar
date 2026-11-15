"""The ONE CELL of a field label on a stored table (owner, 12 Nov 2026; `redesign/TABLE-VALUE.md`; rule 13: any table, no label or layout of one sheet).

Reads `pages.tables_json` (the stored table rows of a page: cell strings, no coordinates) and answers, for a field label and the text of the value the
reader took, WHICH cell that is: one row, the label's cell, the value's cell to its right with only empty cells between them. The cell is the proof
the datasheet's own row gives: the quote is the row's own two cells, as stored, each found on the page text. More than one candidate is a refusal
with the reason, never a guess. A compound row ("Inlet/Outlet pressure | 7.5 / 3.25 barg") is split by position only when the counts match
and the unit applies to every part (`split_compound`); anything else is a refusal. Pure: no database, no model, no network; no document text logged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .reader_api import _fold

NO_HEADER = "no cell of the page's tables is the header"


@dataclass(frozen=True)
class Cell:
    """Where a value stands: page, table, row, the label's column and the value's column, and the two cells' own text as stored."""

    page: int
    table: int
    row: int
    label_col: int
    value_col: int
    label_text: str
    value_text: str
    #: set for a compound row: which part of the label and the figure this value is, in plain words
    split: str | None = None
    #: the text of the column header over the value cell (the nearest text cell above it in its column), when there is one
    header: str | None = None
    #: how many cells of the header's row name a condition (normal, design, operating ...): 1 means this is the table's only value column
    conditions_in_header_row: int = 0

    @property
    def quote(self) -> str:
        """The row's own two cells, as stored, in the order they stand."""
        return f"{self.label_text} {self.value_text}".strip()

    def ref(self) -> dict:
        return {
            "page": self.page,
            "table": self.table,
            "row": self.row,
            "label_col": self.label_col,
            "value_col": self.value_col,
            "header": self.header,
        }


_FIGURE = re.compile(
    r"[\d\s.,+\-/%()]+"
)  # a cell that is only a figure is not a header


#: Words that say WHICH value of a quantity a column or a rule means.
CONDITION_WORDS = frozenset(
    {
        "design",
        "operating",
        "normal",
        "maximum",
        "minimum",
        "test",
        "rated",
        "max",
        "min",
        "built",
    }
)
_STALE = re.compile(
    r"\b(?:previous|prev|prior|old|superseded|obsolete|earlier)\b|\brev(?:ision)?\b\.?\s*[a-z0-9]{1,3}\b",
    re.IGNORECASE,
)


def condition_words(text: object) -> set[str]:
    return {
        w
        for w in _fold(str(text or "").replace("_", " ").replace("-", " ")).split()
        if w in CONDITION_WORDS
    }


def stale_header(header: object) -> str | None:
    """The word that marks a column as another state of the value (previous, old, superseded, a revision), else None."""
    m = _STALE.search(str(header or ""))
    return m.group(0) if m else None


def header_row_of(table: Sequence[Sequence[str]], row: int, col: int) -> int | None:
    """The row of the column header over a value cell (see `header_of`), else None."""
    for r in range(row - 1, -1, -1):
        cells = table[r]
        text = str(cells[col]).strip() if col < len(cells) else ""
        if text and not _FIGURE.fullmatch(text):
            return r
    return None


def conditions_in_row(table: Sequence[Sequence[str]], row: int | None) -> int:
    return 0 if row is None else sum(1 for c in table[row] if condition_words(c))


def header_of(table: Sequence[Sequence[str]], row: int, col: int) -> str | None:
    """The column header over a value cell: the nearest cell ABOVE it, in its own column, that holds words (a figure alone is no header; "Normal", "Design", "Revision B"). None when
    there is none (a sheet whose columns carry no header)."""
    for r in range(row - 1, -1, -1):
        cells = table[r]
        text = str(cells[col]).strip() if col < len(cells) else ""
        if text and not _FIGURE.fullmatch(text):
            return text
    return None


def tables_of(tables_json: str | None) -> list[list[list[str]]]:
    """The stored rows of every table of a page: a list of tables, each a list of rows of cell strings. Unreadable or absent: no tables."""
    try:
        data = json.loads(tables_json or "{}")
    except (TypeError, ValueError):
        return []
    out = []
    for t in (data.get("tables") if isinstance(data, Mapping) else None) or []:
        rows = t.get("rows") if isinstance(t, Mapping) else None
        if isinstance(rows, list):
            out.append(
                [
                    [str(c if c is not None else "") for c in r]
                    for r in rows
                    if isinstance(r, list)
                ]
            )
    return out


def _gap_empty(row: Sequence[str], i: int, j: int) -> bool:
    return all(not _fold(c) for c in row[i + 1 : j])


def locate(
    tables: Sequence[Sequence[Sequence[str]]], *, page: int, label: str, value_text: str
) -> tuple[Cell | None, str]:
    """(the cell, "") or (None, why). Exactly one (label cell, value cell) pair of one row: the label cell's text is the label, the value cell's
    text is the value's text, and only empty cells stand between. None found, or several, is a refusal in words."""
    want_label, want_value = _fold(label), _fold(value_text)
    if not want_label or not want_value:
        return None, "no label or no value text to find"
    found: list[Cell] = []
    label_seen = False
    for ti, table in enumerate(tables):
        for ri, row in enumerate(table):
            for i, c in enumerate(row):
                if _fold(c) != want_label:
                    continue
                label_seen = True
                found += [
                    Cell(
                        page,
                        ti,
                        ri,
                        i,
                        j,
                        str(c).strip(),
                        str(row[j]).strip(),
                        None,
                        header_of(table, ri, j),
                        conditions_in_row(table, header_row_of(table, ri, j)),
                    )
                    for j in range(i + 1, len(row))
                    if _fold(row[j]) == want_value and _gap_empty(row, i, j)
                ]
    if len(found) == 1:
        return found[0], ""
    if len(found) > 1:
        return (
            None,
            "the label and the value stand in more than one place of the page's tables",
        )
    return (
        None,
        "no cell holds the value next to the label"
        if label_seen
        else "the label is not a cell of any table on this page",
    )


def locate_column(
    tables: Sequence[Sequence[Sequence[str]]], *, page: int, label: str, header: str
) -> tuple[Cell | None, str]:
    """A table with one column per case or tag: the cell where the label's row crosses the header's column. The header is a cell of ONE row of the same table
    whose text is the header, or holds it, or is held by it (3 characters or more on both sides); the label is a cell of exactly ONE row of that table. An empty cell, a header
    that matches two columns, or a label on two rows is a refusal in words."""
    want_label, want_head = _fold(label), _fold(header)
    if not want_label or not want_head:
        return None, "no label or no header to cross"
    found: list[Cell] = []
    heads = rows_seen = 0
    for ti, table in enumerate(tables):
        cols = {
            j
            for row in table
            for j, c in enumerate(row)
            if _fold(c)
            and (
                _fold(c) == want_head
                or (
                    len(_fold(c)) >= 3
                    and (_fold(c) in want_head or want_head in _fold(c))
                )
            )
        }
        heads += len(cols)
        label_rows = [
            (ri, i)
            for ri, row in enumerate(table)
            for i, c in enumerate(row)
            if _fold(c) == want_label
        ]
        rows_seen += len(label_rows)
        if len(cols) == 1 and len(label_rows) == 1:
            ri, i = label_rows[0]
            j = next(iter(cols))
            if j != i and j < len(table[ri]) and _fold(table[ri][j]):
                found.append(
                    Cell(
                        page,
                        ti,
                        ri,
                        i,
                        j,
                        str(table[ri][i]).strip(),
                        str(table[ri][j]).strip(),
                        None,
                        header_of(table, ri, j),
                        conditions_in_row(table, header_row_of(table, ri, j)),
                    )
                )
    if len(found) == 1:
        return found[0], ""
    if len(found) > 1:
        return None, "the label and the header cross in more than one table of the page"
    if heads == 0:
        return None, NO_HEADER
    if rows_seen == 0:
        return None, "the label is not a cell of any table on this page"
    return (
        None,
        "the header matches more than one column, the label more than one row, or the crossing cell is empty",
    )


# ---------------------------------------------------------------------------------------- compound rows


def _split_slash(text: str) -> list[str]:
    """Cut on "/" outside brackets."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch in "(["
        depth -= ch in ")]" and depth > 0
        if ch == "/" and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def label_parts(label: str) -> list[str]:
    """The full labels of a slash-joined label: "Inlet/Outlet pressure" gives "Inlet pressure" and "Outlet pressure". Every part but the last must be
    ONE word, and the last more than one, so the tail they share is certain; otherwise the parts as written."""
    parts = [p for p in _split_slash(label) if p]
    if len(parts) < 2:
        return []
    last = parts[-1].split()
    if len(last) > 1 and all(len(p.split()) == 1 for p in parts[:-1]):
        tail = " ".join(last[1:])
        return [f"{p} {tail}" for p in parts[:-1]] + [parts[-1]]
    return parts


_BRACKET = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_UNIT_TAIL = re.compile(r"^\s*(?P<num>[-+]?\d[\d.,]*)\s*(?P<unit>[^\d\s(][^\s(]*)?\s*$")


def split_compound(
    label_cell: str, value_cell: str, wanted_label: str
) -> tuple[int, str, str, str] | None:
    """For a compound row whose label has n parts and whose value cell holds n figures: (the part's index, the figure, its unit, the plain words), when
    `wanted_label` is one of the label's parts. None unless the counts match, every part has ONE number, and the unit applies to every part (stated once
    at the end, or the same on each). A unit on one part only, or two different units, is None: no guess."""
    names = label_parts(label_cell)
    if len(names) < 2:
        return None
    figures = [_BRACKET.sub(" ", p).strip() for p in _split_slash(value_cell)]
    if len(figures) != len(names):
        return None
    read = [_UNIT_TAIL.match(f) for f in figures]
    if not all(read):
        return None
    units = [(m.group("unit") or "").strip() for m in read]
    if units[-1] and not any(units[:-1]):
        units = [units[-1]] * len(
            units
        )  # stated once, at the end: it applies to every part
    elif not (units[0] and len(set(units)) == 1):
        return None
    folded = [_fold(n) for n in names]
    if _fold(wanted_label) not in folded or folded.count(_fold(wanted_label)) != 1:
        return None
    k = folded.index(_fold(wanted_label))
    ordinal = (
        ("first", "second", "third", "fourth", "fifth")[k]
        if k < 5
        else f"number {k + 1}"
    )
    count = {2: "two", 3: "three", 4: "four", 5: "five"}.get(
        len(names), str(len(names))
    )
    return (
        k,
        read[k].group("num"),
        units[k],
        f"read as the {ordinal} of {count} values in '{label_cell.strip()}'",
    )


def locate_compound(
    tables: Sequence[Sequence[Sequence[str]]], *, page: int, label: str
) -> tuple[Cell | None, str, str | None]:
    """(cell, figure, unit) of a label that is ONE PART of a compound row, else (None, why, None). Exactly one such row on the page."""
    found = []
    for ti, table in enumerate(tables):
        for ri, row in enumerate(table):
            for i, c in enumerate(row):
                if "/" not in str(c) or len(label_parts(str(c))) < 2:
                    continue
                for j in range(i + 1, len(row)):
                    if _fold(row[j]):
                        if _gap_empty(row, i, j):
                            got = split_compound(str(c), str(row[j]), label)
                            if got:
                                found.append(
                                    (
                                        Cell(
                                            page,
                                            ti,
                                            ri,
                                            i,
                                            j,
                                            str(c).strip(),
                                            str(row[j]).strip(),
                                            got[3],
                                            header_of(table, ri, j),
                                            conditions_in_row(
                                                table, header_row_of(table, ri, j)
                                            ),
                                        ),
                                        got[1],
                                        got[2],
                                    )
                                )
                        break
    if len(found) == 1:
        return found[0]
    return (
        None,
        (
            "the label is a part of more than one compound row"
            if found
            else "no compound row of this page splits into this label"
        ),
        None,
    )


def in_page(cell: Cell, page_text: object) -> bool:
    """Each of the two cells' words is found on the stored page text: a cell never invents a word."""
    flat = _fold(str(page_text or ""))
    return bool(flat) and all(
        _fold(t) in flat for t in (cell.label_text, cell.value_text) if _fold(t)
    )
