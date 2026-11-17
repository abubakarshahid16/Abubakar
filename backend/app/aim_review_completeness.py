"""COMPLETENESS IS A HARD RULE, for the general review's file (order 14, piece C; owner, 15 Nov 2026).

Three counts of ONE general run are compared, and the file is refused when they differ:
  page       the points the page serves (`aim_review_view.build`),
  database   the lines stored for the run (a separate `COUNT(*)` on `aim_lines`),
  file rows  the rows on the sheet "All points" of the workbook AS BUILT, read back from the bytes (never the builder's own number);
and the comments the page serves = the rows on the sheet "Comments".
Also read back: every sheet carries the mark, the first sheet states "N points reviewed, N in this file", a cell cut on "Comments" is
cut only with `crs_completeness.CUT_MARK` and is whole on "All points", and "All points" holds every text whole.

It runs after every review ends (`record_after_run`, the result is stored with the run) and again at every download
(`file_or_refuse`: a difference raises `crs_completeness.Incomplete`, the route answers 409 with the sentence). Counts, line numbers and
pages only: no document text is logged or put in a sentence. No model, no network.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from io import BytesIO

from openpyxl import load_workbook

from . import aim_review_gate, aim_review_sheet, aim_review_store, aim_review_view
from .crs_completeness import CUT_MARK, Incomplete, team_statement
from .crs_export import safe_cell_text
from .db import connect

log = logging.getLogger(__name__)
LIST_AT_MOST = 10

__all__ = ["Incomplete", "file_or_refuse", "record_after_run", "report_for", "verify"]


def _table(wb, sheet: str) -> list[list]:
    """The data rows of one table sheet as built: the rows under the header whose first cell is "No."."""
    if sheet not in wb.sheetnames:
        return []
    values = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
    start = next(
        (
            i
            for i, r in enumerate(values)
            if r and r[0] == aim_review_sheet.FIRST_HEADER
        ),
        None,
    )
    if start is None:
        return []
    return [r for r in values[start + 1 :] if any(c is not None for c in r)]


def _database_lines(conn, run_id: str) -> list[dict]:
    """The stored lines by a query of their own (not the view's): the database side of the comparison."""
    rows = conn.execute(
        f"SELECT line_no, item_id, page FROM {aim_review_store.LINES} WHERE run_id = ? ORDER BY line_no",
        (run_id,),
    ).fetchall()
    return [
        {"n": i, "item": r["item_id"], "page": r["page"]} for i, r in enumerate(rows, 1)
    ]


def _named(line: dict) -> str:
    page = f", page {line['page']}" if line.get("page") else ""
    return f"point {line['n']}{' (' + str(line['item']) + ')' if line.get('item') else ''}{page}"


def _text(cell) -> str:
    return "" if cell is None else str(cell)


def _cut_check(
    comments_rows: list[list], points_rows: list[list]
) -> tuple[int, list[str]]:
    """(cells cut with the mark, problems). A Comments cell must equal its All points text, or be that text cut with the mark."""
    full = {r[0]: r for r in points_rows if isinstance(r[0], int)}
    marked, problems = 0, []
    for r in comments_rows:
        n = r[0]
        if n not in full:
            problems.append(
                f"comment {n} has no row on the sheet {aim_review_sheet.ALL_POINTS}"
            )
            continue
        for col, full_col, name in ((4, 7, "comment"), (5, 8, "quote")):
            cell, whole = _text(r[col]), _text(full[n][full_col])
            if cell == whole:
                continue
            if (
                cell.endswith(CUT_MARK)
                and whole.startswith(cell[:-1])
                and len(whole) >= len(cell)
                and _text(r[10])
            ):
                marked += 1
            else:
                problems.append(
                    f"the {name} of point {n} is cut without the mark or without its full text beside it"
                )
    return marked, problems


def _row_problems(
    view: dict, wb, comments_rows: list[list], points_rows: list[list]
) -> list[str]:
    mark = aim_review_gate.AI_MARK
    problems = [f"the sheet {s} does not carry the mark" for s in aim_review_sheet.SHEETS
                if s not in wb.sheetnames or wb[s].cell(row=1, column=1).value != mark]  # fmt: skip
    if any(r[-1] != mark for r in (*comments_rows, *points_rows)):
        problems.append("a row does not carry the mark")
    first = (
        wb[aim_review_sheet.SUMMARY]
        if aim_review_sheet.SUMMARY in wb.sheetnames
        else None
    )
    statement = team_statement(view["counts"]["points"], view["counts"]["comments"])
    if first is None or not any(
        statement in _text(c) for r in first.iter_rows(values_only=True) for c in r
    ):
        problems.append("the first sheet does not state the counts")
    for r in (
        points_rows
    ):  # All points holds every text whole: its cell is the page's own text
        p = (
            view["points"][r[0] - 1]
            if isinstance(r[0], int) and 0 < r[0] <= len(view["points"])
            else None
        )
        if p is not None and (
            _text(r[7]) != safe_cell_text(p["comment"])
            or _text(r[8]) != safe_cell_text(p["quote"])
        ):
            problems.append(
                f"the text of point {r[0]} is cut on the sheet {aim_review_sheet.ALL_POINTS}"
            )
    return problems


def _sentence(rep: dict) -> str:
    parts = [
        f"This general review's file is not complete and was not given out: the page has {rep['page']} points, "
        f"the database holds {rep['database']} lines, the file has {rep['file_rows']} rows on the sheet {aim_review_sheet.ALL_POINTS} "
        f"and {rep['comment_rows']} on the sheet {aim_review_sheet.COMMENTS} (the page has {rep['comments']} comments)."
    ]
    if rep["missing"]:
        shown = "; ".join(rep["missing"][:LIST_AT_MOST])
        more = (
            f" and {len(rep['missing']) - LIST_AT_MOST} more"
            if len(rep["missing"]) > LIST_AT_MOST
            else ""
        )
        parts.append(f"Missing: {shown}{more}.")
    if rep["problems"]:
        parts.append("Also: " + "; ".join(rep["problems"][:LIST_AT_MOST]) + ".")
    return " ".join(parts)


def checked(conn, run: dict, view: dict) -> tuple[bytes, dict]:
    """(the workbook of this run as built, the counted report). The rows are read back from the built bytes."""
    data = aim_review_sheet.build(view)
    wb = load_workbook(BytesIO(data))
    points_rows = _table(wb, aim_review_sheet.ALL_POINTS)
    comments_rows = _table(wb, aim_review_sheet.COMMENTS)
    db_lines = _database_lines(conn, run["run_id"])
    in_file = {r[0] for r in points_rows if isinstance(r[0], int)}
    marked, cut_problems = _cut_check(comments_rows, points_rows)
    problems = [*cut_problems, *_row_problems(view, wb, comments_rows, points_rows)]
    rep = {
        "run_id": run["run_id"],
        "page": view["counts"]["points"],
        "database": len(db_lines),
        "file_rows": len(points_rows),
        "comments": view["counts"]["comments"],
        "comment_rows": len(comments_rows),
        "missing": [_named(ln) for ln in db_lines if ln["n"] not in in_file],
        "cut_cells_marked": marked,
        "problems": problems,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    same = (
        rep["page"] == rep["database"] == rep["file_rows"]
        and rep["comments"] == rep["comment_rows"]
    )
    rep["ok"] = same and not problems
    rep["sentence"] = None if rep["ok"] else _sentence(rep)
    return data, rep


def report_for(conn, run: dict, view: dict) -> dict:
    """The page's `completeness` answer: {ok, page, database, file_rows, sentence, ...counts}. `sentence` is None when all agree."""
    return checked(conn, run, view)[1]


def _run_and_view(run_id: str, scope):
    conn = connect()
    run = aim_review_store.run(conn, run_id)
    if run is None or (
        scope is not None and not scope.may_read(run["paper_document_id"])
    ):
        raise LookupError("no general review with that id")
    return conn, run, aim_review_view.build(conn, run, scope)


def verify(run_id: str, scope) -> dict:
    """The counted report of one general run (raises `LookupError` for an unknown run or one the scope may not read, and
    `aim_review_view.NotFinished` for a run that has not ended)."""
    conn, run, view = _run_and_view(run_id, scope)
    return report_for(conn, run, view)


def file_or_refuse(run_id: str, scope) -> bytes:
    """THE HARD RULE: the file's bytes, or `Incomplete` carrying the report and the sentence naming what is missing."""
    conn, run, view = _run_and_view(run_id, scope)
    data, rep = checked(conn, run, view)
    if not rep["ok"]:
        raise Incomplete(rep)
    return data


def record_after_run(run_id: str) -> dict | None:
    """After a general review ends: check the file and store the result with the run (`aim_runs.completeness_json`). Never fails the
    run: a failure is logged by type and None is returned."""
    from . import access

    try:
        report = verify(run_id, access.unrestricted_scope())
        conn = connect()
        # the one writer (piece D)
        aim_review_store.set_completeness(conn, run_id, report)
        if not report["ok"]:
            log.error(
                "general review completeness: run %s differs (page %s, database %s)",
                run_id,
                report["page"],
                report["database"],
            )
        return report
    except Exception as exc:  # noqa: BLE001 - logged by type; a failed check never fails the review
        log.warning(
            "general review completeness: the check could not run (%s)",
            type(exc).__name__,
        )
        return None
