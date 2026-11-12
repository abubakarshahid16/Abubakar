"""PR 1763 (order 13, owner 12 Nov 2026): the AI reviewer's CRS uses the app's one CRS layout. `crs_export.py` (danger zone, rule 6) hands
the normal reviewer's sheet to `crs_layout` for its header row, frozen panes and print setup; `crs_layout.py` draws the AI reviewer's
workbook (styled by code, one colour per Status). Ids M1763-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_L = APP / "crs_layout.py"
_E = APP / "crs_export.py"
_T = "tests/test_agent_review_crs.py"
_T2 = "tests/test_crs_one_layout.py"
_TAGS = ("honesty", "critical")


def _m(
    n: str, desc: str, path, anchor: str, repl: str, target: str, kw: str
) -> Mutation:
    return Mutation(
        id=f"M1763-{n}", phase=1763, description=desc, path=path, anchor=anchor, replacement=repl,
        target=target, keyword=kw, tags=_TAGS,
    )  # fmt: skip


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the header row loses its fill (a plain row, the table no longer reads as a table)",
        _L,
        "        cell.fill = HEADER_FILL\n",
        "        pass\n",
        _T,
        "styled_by_code",
    ),
    _m(
        "02",
        "the frozen panes sit on the header row itself, so the header scrolls away",
        _L,
        '    ws.freeze_panes = f"A{header_row + 1}"\n',
        '    ws.freeze_panes = f"A{header_row}"\n',
        _T,
        "styled_by_code",
    ),
    _m(
        "03",
        "an empty cell of the table (a Response cell the contractor fills later) has no border",
        _L,
        "            if cell.value is None and r < header_row:\n",
        "            if cell.value is None:\n",
        _T,
        "styled_by_code",
    ),
    _m(
        "04",
        "the sheet prints in portrait instead of landscape",
        _L,
        '    ws.page_setup.orientation = "landscape"\n',
        '    ws.page_setup.orientation = "portrait"\n',
        _T,
        "styled_by_code or styled_the_same_way",
    ),
    _m(
        "05",
        "the header row is not repeated on every printed page",
        _L,
        '    ws.print_title_rows = f"{header_row}:{header_row}"\n',
        "    pass\n",
        _T,
        "styled_by_code or styled_the_same_way",
    ),
    _m(
        "06",
        "two Statuses share one colour (a Fail and an AI opinion look alike)",
        _L,
        '    "AI opinion": PatternFill("solid", fgColor="FFEFE8F7"),\n',
        '    "AI opinion": PatternFill("solid", fgColor="FFF5D6D6"),\n',
        _T,
        "four_colours or styled_by_code",
    ),
    _m(
        "07",
        "no row takes the fill of its Status",
        _L,
        "        fill = STATUS_FILLS.get(statuses[n - 1]) if n - 1 < len(statuses) else None\n",
        "        fill = None\n",
        _T,
        "styled_by_code",
    ),
    _m(
        "08",
        "the column widths are not set (every column at the default width)",
        _L,
        "        ws.column_dimensions[get_column_letter(i)].width = width\n",
        "        pass\n",
        _T,
        "styled_by_code",
    ),
    _m(
        "09",
        "a string that starts with an equals sign is stored as a formula on the AI reviewer's sheet",
        _L,
        "    cell = _write(ws, row, col, value)\n    cell.font = Font(name=ARIAL, bold=bold, size=size)\n",
        "    cell = ws.cell(row=row, column=col)\n    cell.value = value\n    cell.font = Font(name=ARIAL, bold=bold, size=size)\n",
        _T,
        "equals_sign",
    ),
    _m(
        "10",
        "the normal reviewer's sheet is not given the shared header row, frozen panes and print setup",
        _E,
        '    crs_layout.style_header_and_print(ws, COLUMN_HEADER_ROW, len(view["columns"]))\n',
        "    pass\n",
        _T2,
        "shared_header_and_print_setup",
    ),
)
