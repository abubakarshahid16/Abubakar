"""#645 slice 2: a standard's TABLE row whose comparator is in the column header.

A limits table ("Parameter | Min | Max | Unit", or a header "Maximum allowable
working pressure") states the direction in the HEADER, not in the row, so
`ai_requirement_chunks.verify_item` refuses the row (the comparator is not in
its words). The model only LOCATES the row (its quote); CODE reads the rest:

  * the table is the chunk's own table render (`chunker.table_block_parts`
    writes header lines then rows); header lines come from
    `chunker._table_header`, the reader that wrote them, so a multi-row header
    is read the way it was stored;
  * the comparator is parsed from the column's header cell with the same
    operator words the sentence reader uses (`ai_requirements._OPERATOR_WORDS`),
    minus the words that are usually a CONDITION in a header ("below 50 C");
    a header cell with two directions, a number of its own, or none states
    nothing: the row stays unknown and is refused (rule 4, never guessed). A
    short caption line right above the table is used only when no header cell
    of the table states a direction;
  * the value is the row cell's own single number; the unit is the cell's, else
    the column header's bracket ("Pressure (barg)"), else the row's cell under
    a "Unit" column; it must be a unit (`claims`);
  * every numeric cell of the located row whose column header states a
    direction becomes one limit (a Min and a Max column give >= and <=); the
    model's value must be one of those cells, and its direction and unit must
    agree with what code read;
  * the stored quote is [caption] + header line(s) + the row line, each taken
    from the chunk by code, so the engineer sees the words the direction came
    from; the same `ai_requirements.verify_proposal` then checks value, unit and
    condition against that quote, and again at accept.

No per-standard layout code: any pipe table with a header row is read the same
way. Behind `settings.ai_requirement_extraction_enabled` (the caller). Counts
only; never a quote.
"""

from __future__ import annotations

import re

from . import ai_requirements as air
from . import numparse

COMPARATOR_NOT_STATED = "the quote states no comparator, so it stays unknown"
UNIT_DISAGREED = "the unit is not the one the table states"

#: Words that, in a header, usually give the CONDITION a column applies under
#: ("Temperature below 50 C"), not the direction of its limit.
_CONDITION_WORDS = frozenset({"under", "above", "below", "exceeding", "up to"})
_WORDS = sorted(
    ((w, op) for w, op in air._OPERATOR_WORDS if w not in _CONDITION_WORDS),
    key=lambda pair: -len(pair[0]),
)
_WORD_RX = [
    (re.compile(r"(?<![^\W\d_])" + re.escape(w) + r"(?![^\W\d_])"), op)
    for w, op in _WORDS
]
_BRACKET = re.compile(r"[(\[]([^()\[\]]*)[)\]]")
_RULE = re.compile(r"^[\s|:\-]+$")
_UNIT_COLUMN = re.compile(r"^(units?|uom|unit of measure)$", re.IGNORECASE)
_CAPTION_WORDS = 15


def header_operator(cell: str) -> str | None:
    """The direction one header cell states, or None. Exactly one direction;
    a number of its own outside brackets means the cell holds a condition."""
    text = _BRACKET.sub(" ", (cell or "").casefold())
    if re.search(r"\d", text):
        return None
    found: set[str] = set()
    for rx, op in _WORD_RX:
        if rx.search(text):
            found.add(op)
            text = rx.sub(" ", text)
    return found.pop() if len(found) == 1 else None


def _is_unit(unit: str) -> bool:
    from . import claims

    return claims.is_unit(unit) or claims.unit_dimension(unit) is not None


def header_unit(cell: str) -> str | None:
    """The unit in the LAST bracket of a header cell ("Pressure (barg)"), when
    it is a unit."""
    groups = [g.strip() for g in _BRACKET.findall(cell or "") if g.strip()]
    return groups[-1] if groups and _is_unit(groups[-1]) else None


def _cells(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [" ".join(c.split()) for c in text.split("|")]


def read_tables(chunk_text: str) -> list[dict]:
    """The pipe tables of a chunk: {caption, header (cell names), header_lines,
    rows: [(line, cells)]}. `header` is None when the first row is not a
    header (`chunker._table_header`)."""
    from . import chunker

    lines = (chunk_text or "").splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue
        start = i
        block = []
        while i < len(lines) and "|" in lines[i]:
            if not _RULE.match(lines[i]):
                block.append(lines[i].strip())
            i += 1
        if len(block) < 2:
            continue
        grid = [_cells(line) for line in block]
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]
        header, data = chunker._table_header(grid)
        used = len(block) - len(data)
        before = next((ln.strip() for ln in reversed(lines[:start]) if ln.strip()), "")
        caption = before if before and len(before.split()) <= _CAPTION_WORDS else ""
        out.append(
            {
                "caption": caption,
                "header": header,
                "header_lines": block[:used] if header else [],
                "rows": list(zip(block[used:], data, strict=True)),
            }
        )
    return out


def _columns(table: dict) -> dict[int, str]:
    """{column: direction} from the header cells; the caption's direction for
    every column only when NO header cell states one."""
    header = table["header"] or []
    by_cell = {i: header_operator(h) for i, h in enumerate(header)}
    stated = {i: op for i, op in by_cell.items() if op}
    if stated or not table["caption"]:
        return stated
    caption = header_operator(table["caption"])
    return dict.fromkeys(range(len(header)), caption) if caption else {}


def _unit_for(table: dict, column: int, cells: list[str]) -> str | None:
    """Unit of the cell at `column`: its own, the column header's, the row's
    cell under a Unit column."""
    figures = air.read_figures(cells[column])
    if len(figures) == 1 and figures[0]["unit"]:
        return figures[0]["unit"]
    header = table["header"] or []
    if column < len(header) and header_unit(header[column]):
        return header_unit(header[column])
    for i, name in enumerate(header):
        if _UNIT_COLUMN.match(name) and cells[i] and _is_unit(cells[i]):
            return cells[i]
    return None


def _number(cell: str) -> str | None:
    """The cell's single number as text, or None (no number, or several)."""
    found = numparse.find_numbers(numparse.fold(cell))
    if len(found) != 1 or found[0].value is None:
        return None
    return f"{found[0].value:g}"


def read_row(item: dict, chunk_text: str):
    """None when the item is not a located row of a headed table whose column
    states a direction (the prose path then decides). Else
    (checks, refusals): checks are the verified limits of the row, refusals the
    reasons of those code refused."""
    if set(item.get("flags") or []) - {air.MODEL_VALUE_DISAGREED}:
        return None  # the unit may stand in the header, so a figure-less row is no disagreement
    if item.get("operator") == "none":
        return None
    quote = air._squash(item.get("quote"))
    model_value = air.hint(item.get("value"))
    if not quote or model_value is None:
        return None
    for table in read_tables(chunk_text):
        if table["header"] is None:
            continue
        for line, cells in table["rows"]:
            if quote in air._squash(line):
                return _limits_of_row(item, table, line, cells, model_value)
    return None


def _limits_of_row(item, table, line, cells, model_value):
    directions = _columns(table)
    numeric = {
        i: n for i, c in enumerate(cells) if i >= 1 and (n := _number(c)) is not None
    }
    matched = [i for i in numeric if numparse.value_in_text(model_value, cells[i])]
    if not matched:
        return (
            None  # the value is in no single-number cell: the sentence path refuses it
        )
    if not any(i in directions for i in matched):
        # the column states no direction: unknown, unless the cell's own words do
        if any(f["operator"] for i in matched for f in air.read_figures(cells[i])):
            return None
        return [], [COMPARATOR_NOT_STATED]
    if item.get("operator") in {"<=", "<", ">=", ">", "="} and not any(
        directions.get(i) == item["operator"] for i in matched
    ):
        return [], [air.OPERATOR_DISAGREED]
    asked = air.hint(item.get("unit"))
    if asked and any(
        air._squash(asked) != air._squash(_unit_for(table, i, cells) or "")
        for i in matched
    ):
        return [], [UNIT_DISAGREED]
    uses_caption = bool(table["caption"]) and not any(
        header_operator(h) for h in table["header"]
    )
    quote = "\n".join(
        ([table["caption"]] if uses_caption else []) + table["header_lines"] + [line]
    )
    checks: list[dict] = []
    refusals: list[str] = []
    for column in sorted(i for i in numeric if i in directions):
        unit = _unit_for(table, column, cells)
        check, why = air.verify_proposal(
            {
                "has_limit": True,
                "field": item.get("subject"),
                "operator": directions[column],
                "value": numeric[column],
                "unit": unit,
                "condition": item.get("condition"),
                "quote": quote,
            },
            quote,
        )
        if check is None:
            refusals.append(why)
        elif check["operator"] != directions[column]:
            refusals.append(air.OPERATOR_DISAGREED)
        else:
            checks.append(check)
    return checks, refusals


def already_drafted(conn, standard_document_id: str, check: dict) -> bool:
    """A draft for these words, direction and figure exists (any status: a
    rejected one is not proposed again)."""
    return (
        conn.execute(
            "SELECT 1 FROM clause_check_drafts d JOIN standard_requirements r"
            " ON r.id = d.requirement_id WHERE r.standard_document_id = ?"
            " AND d.quote = ? AND d.operator = ? AND d.value = ?",
            (standard_document_id, check["quote"], check["operator"], check["value"]),
        ).fetchone()
        is not None
    )
