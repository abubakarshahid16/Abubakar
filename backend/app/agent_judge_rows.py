"""System A's CRS workbook as input and the judged workbook as output, for the agent judge mode (#1690, part of #805).

READ: the INPUT file is read from a byte copy and is never opened for writing here; the output goes to another path and
`write_judged` refuses the input path. A data row is a CLAIM ("this is wrong or missing: <comment>, page <p>, against
<standard clause>"): any row below the header row that has five or more filled cells (the answer-key scorer's own rule
for a comment row). Rows are named J1, J2, ... in sheet order.

WRITE: the same workbook (every sheet, the header block, styles, the footer block and its merged cells) with the rows the
judge removed taken out of sheet "CRS", so the scorer can read it exactly as it reads A's own file; a column "AI Review
Comments" note on each kept row ('confirmed' or 'AI could not confirm'); and a sheet "Removed by AI judge" (local file only:
it holds the verified quotes). Nothing here is sent anywhere.
"""

from __future__ import annotations

import io
import os
import re
from copy import copy
from pathlib import Path

import openpyxl

from .agent_judge_rules import parse_reference, row_pages
from .agent_run_crs import _cell

CRS_SHEET = "CRS"
REMOVED_SHEET = "Removed by AI judge"
MIN_FILLED = 5  # the scorer's definition of a comment row
H_PAGE, H_COMMENT, H_STANDARD = (
    "Page No./Section",
    "COMPANY Comments",
    "Standard Reference",
)
H_ITEM, H_AI = "Item No", "AI Review Comments"
REQUIRED = (H_PAGE, H_COMMENT, H_STANDARD)
REMOVED_HEADERS = (
    "Row",
    "Item No",
    "Page No./Section",
    "Reason code",
    "Page (verified)",
    "Document quote",
    "Clause",
    "Clause quote",
    "Second opinion",
    "Original comment",
)


class WorkbookLayout(ValueError):
    """The workbook has no CRS sheet or no header row with the columns the scorer reads."""


def _filled(row) -> int:
    return sum(1 for c in row if c not in (None, ""))


def _load(path: str | os.PathLike) -> openpyxl.Workbook:
    """A workbook from a BYTE COPY of the file: the original is never held open."""
    return openpyxl.load_workbook(io.BytesIO(Path(path).read_bytes()))


def _header(ws) -> tuple[int, dict[str, int]]:
    for r in range(1, min(ws.max_row, 40) + 1):
        names = {
            str(c.value).strip(): c.column for c in ws[r] if c.value not in (None, "")
        }
        if all(h in names for h in REQUIRED):
            return r, names
    raise WorkbookLayout("no header row with the page, comment and standard columns")


def read_rows(path: str | os.PathLike) -> list[dict]:
    """A's claim rows: {'id','excel_row','item','page_section','page_hint','comment','standard_reference'}."""
    wb = _load(path)
    if CRS_SHEET not in wb.sheetnames:
        raise WorkbookLayout("no CRS sheet")
    ws = wb[CRS_SHEET]
    head, cols = _header(ws)
    rows = []
    for r in range(head + 1, ws.max_row + 1):
        cells = [c.value for c in ws[r]]
        if _filled(cells) < MIN_FILLED:
            continue
        get = lambda name, r=r: ws.cell(r, cols[name]).value if name in cols else None  # noqa: E731
        row = {
            "id": f"J{len(rows) + 1}",
            "excel_row": r,
            "item": get(H_ITEM),
            "page_section": get(H_PAGE),
            "comment": get(H_COMMENT),
            "standard_reference": get(H_STANDARD),
        }
        row["reference"] = parse_reference(
            row["standard_reference"]
        )  # {"standard", "clause"} or None
        row["pages"] = row_pages(
            row
        )  # the pages the row NAMES ('p. 3', 'pages 3 and 5'); a section number is not a page
        row["page_hint"] = row["pages"][0] if row["pages"] else None
        rows.append(row)
    return rows


_ROW_ITEM = re.compile(r"^J?(\d+)(?:-J?(\d*))?$", re.IGNORECASE)


def parse_row_ids(spec: str | None, total: int) -> list[str] | None:
    """'1-5,9' or 'J1-J5,J9' -> ['J1',...,'J5','J9']; '8-' is row 8 to the LAST row; None when there is no spec.

    A bad spec is an error, never a silent empty selection: '8-5' (backwards), 'abc', '0', a negative number, an empty
    item ('1,,2'), a row the file does not have."""
    if spec is None or not str(spec).strip():
        if spec is not None:
            raise ValueError("--rows is empty")
        return None
    out: list[str] = []
    for part in str(spec).split(","):
        found = _ROW_ITEM.match(part.strip())
        if not found:
            raise ValueError(
                f"--rows item '{part.strip()}' is not a row id or a range (use 3, J3, 2-5, 8-)"
            )
        lo = int(found.group(1))
        hi = (
            total
            if (found.group(2) == "" and "-" in part)
            else int(found.group(2) or lo)
        )
        if lo < 1 or hi < 1:
            raise ValueError("--rows numbers start at 1")
        if hi < lo:
            raise ValueError(f"--rows range '{part.strip()}' runs backwards")
        if hi > total:
            raise ValueError(
                f"--rows names row {hi}, but the workbook has {total} rows"
            )
        out += [f"J{n}" for n in range(lo, hi + 1)]
    return list(dict.fromkeys(out))


def _snap(ws, r: int, ncols: int):
    return (
        [
            (ws.cell(r, c).value, copy(ws.cell(r, c)._style))
            for c in range(1, ncols + 1)
        ],
        ws.row_dimensions[r].height,
    )


def _put(ws, r: int, snap, ncols: int) -> None:
    cells, height = snap
    for c, (value, style) in enumerate(cells[:ncols], 1):
        cell = ws.cell(r, c)
        cell.value = value
        cell._style = copy(style)
    if height:
        ws.row_dimensions[r].height = height


def is_removed(decision: dict) -> bool:
    """REMOVE and the second opinion agreed (`kept` marks a removal that did not stand: the row stays)."""
    return decision.get("decision") == "REMOVE" and not decision.get("kept")


def _note(decision: dict) -> str:
    kind = decision.get("decision")
    if kind == "CONFIRM":
        return (
            f"AI judge: confirmed (p.{decision.get('page')})"
            if decision.get("page")
            else "AI judge: confirmed"
        )
    if kind == "REMOVE":  # a REMOVE that stays (the second opinion did not agree)
        return "AI judge: removal not confirmed by the second opinion"
    return f"AI judge: AI could not confirm ({decision.get('unsure_code') or 'claim_unclear'})"


def write_judged(
    src: str | os.PathLike,
    out: str | os.PathLike,
    rows: list[dict],
    decisions: dict[str, dict],
) -> Path:
    """The judged workbook. `decisions`: row id -> {'decision', 'reason_code', 'page', 'doc_quote', 'clause',
    'clause_quote', 'second'} where decision 'REMOVE' means REMOVED (the second opinion agreed). Rows with no decision stay."""
    if Path(out).resolve() == Path(src).resolve() or (
        Path(out).exists() and Path(out).samefile(src)
    ):
        raise FileExistsError("the judged workbook must be a different file from A's")
    wb = _load(src)
    ws = wb[CRS_SHEET]
    head, cols = _header(ws)
    ncols = ws.max_column
    first, last = min(r["excel_row"] for r in rows), max(r["excel_row"] for r in rows)
    below = [rng for rng in list(ws.merged_cells.ranges) if rng.min_row > head]
    spans = [(m.min_row, m.max_row, m.min_col, m.max_col) for m in below]
    for m in below:
        ws.unmerge_cells(str(m))
    data = {r["excel_row"]: _snap(ws, r["excel_row"], ncols) for r in rows}
    footer = {r: _snap(ws, r, ncols) for r in range(last + 1, ws.max_row + 1)}
    gap = min(footer) - last - 1 if footer else 0
    ws.delete_rows(first, ws.max_row - first + 1)
    kept = [r for r in rows if not is_removed(decisions.get(r["id"], {}))]
    at = first
    ai_col = cols.get(H_AI)
    for r in kept:
        _put(ws, at, data[r["excel_row"]], ncols)
        decision = decisions.get(r["id"])
        if decision and ai_col:
            old = ws.cell(at, ai_col).value
            note = _note(decision)
            ws.cell(at, ai_col).value = f"{old} | {note}" if old else note
        at += 1
    shift = (at + gap) - (last + 1)
    for r, snap in footer.items():
        _put(ws, r + shift, snap, ncols)
    for lo, hi, c1, c2 in spans:
        if lo > last:
            ws.merge_cells(
                start_row=lo + shift, end_row=hi + shift, start_column=c1, end_column=c2
            )
    sheet = wb.create_sheet(REMOVED_SHEET)
    sheet.append(list(REMOVED_HEADERS))
    for r in rows:
        d = decisions.get(r["id"], {})
        if is_removed(d):
            sheet.append(
                [
                    _cell(v)
                    for v in (
                        r["id"],
                        r["item"],
                        r["page_section"],
                        d.get("reason_code"),
                        d.get("page"),
                        d.get("doc_quote"),
                        " ".join(x for x in (d.get("standard"), d.get("clause")) if x)
                        or None,
                        d.get("clause_quote"),
                        d.get("second"),
                        r["comment"],
                    )
                ]
            )
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
