"""The general review's Excel file (order 14, piece C). Built from the view's dict (`aim_review_view.build`), never from the database
a second time, so the page and the file say the same thing. Five sheets: Summary, Comments, Confirmations (not sent), All points,
How it was reviewed.

Honesty:
  * EVERY sheet carries the mark `aim_review_gate.AI_MARK` in its first cell, and every row of Comments and All points carries it in
    its last column.
  * The first sheet states "N points reviewed, N in this file" (`crs_completeness.team_statement`, the one statement) and
    "N points reviewed, M comments sent, K confirmations not sent" (`sent_statement`).
  * A cell of the Comments sheet longer than `COMMENT_CELL_LIMIT` is cut ONLY with `crs_completeness.CUT_MARK`, says where the full
    text is, and the full text stands on All points. All points is cut only beyond Excel's own limit, with the mark, and the
    completeness check refuses a file in which that happens.
  * Every string is stored as TEXT (never a formula); control characters become a space. No null is written as 0.
There is no contractor copy: this module has no such function.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from . import aim_review_gate
from .crs_completeness import CUT_MARK, team_statement
from .crs_export import safe_cell_text

SUMMARY = "Summary"
COMMENTS = "Comments"
ALL_POINTS = "All points"
CONFIRMATIONS = "Confirmations (not sent)"
HOW = "How it was reviewed"
SHEETS = (SUMMARY, COMMENTS, CONFIRMATIONS, ALL_POINTS, HOW)


def sent_statement(points: int, comments: int, confirmations: int) -> str:
    """The first sheet's count of what is sent: "N points reviewed, M comments sent, K confirmations not sent"."""
    return f"{points} points reviewed, {comments} comments sent, {confirmations} confirmations not sent"


#: A comment-sheet cell is cut beyond this many characters (the mark is the last one); the full text is on "All points".
COMMENT_CELL_LIMIT = 1200
#: Excel's own limit for one cell; beyond it even "All points" must cut (and then the file is refused).
EXCEL_CELL_LIMIT = 32000

#: The header row of the two tables. "No." is the first header: the check finds the table by it.
FIRST_HEADER = "No."
COMMENT_HEADERS = (
    "No.",
    "Lines",
    "Field",
    "Page",
    "Shown label",
    "Comment",
    "Quote",
    "Standard",
    "Clause",
    "Source",
    "Item",
    "Note",
    "Status",
)
POINT_HEADERS = (
    "No.", "Item", "Field", "Page", "Shown label", "Topic", "Comment", "Quote", "Quote not verified by code",
    "Code note", "Standard", "Clause", "Source", "Asks", "Value left open", "Numbers", "Status",
)  # fmt: skip
HEADER_ROW = 4
#: Column widths BY HEADER NAME (never by position: a header added or moved once shifted every width by one, so Field was 7 wide and
#: Shown label 70). Short bookkeeping columns are narrow; the text columns are wide. A header not listed gets DEFAULT_WIDTH.
COLUMN_WIDTHS = {
    "No.": 6, "Lines": 9, "Item": 7, "Note": 14, "Status": 12, "Page": 7, "Field": 28, "Shown label": 20, "Comment": 70,
    "Quote": 45, "Standard": 18, "Clause": 10, "Source": 14, "Topic": 26, "Quote not verified by code": 30, "Code note": 20,
    "Asks": 10, "Value left open": 10, "Numbers": 22,
}  # fmt: skip
DEFAULT_WIDTH = 14


def cut(text: str, limit: int = COMMENT_CELL_LIMIT) -> tuple[str, bool]:
    """(the text, or its first `limit - 1` characters plus the cut mark; whether it was cut)."""
    text = text or ""
    return (text, False) if len(text) <= limit else (text[: limit - 1] + CUT_MARK, True)


def _put(ws: Worksheet, row: int, col: int, value):
    """One cell as TEXT or number: control characters cleaned, a string never a formula, a None left empty."""
    cell = ws.cell(row=row, column=col)
    clean = safe_cell_text(value)
    cell.value = clean if clean != "" else None
    if isinstance(clean, str):
        cell.data_type = "s"
    return cell


def _head(ws: Worksheet, title: str) -> None:
    """Row 1: the mark, on every sheet; row 2: the sheet's title."""
    _put(ws, 1, 1, aim_review_gate.AI_MARK).font = Font(bold=True, color="9C0006")
    _put(ws, 2, 1, title).font = Font(bold=True, size=13)


def _table(ws: Worksheet, headers: tuple[str, ...], rows: list[list]) -> None:
    for c, h in enumerate(headers, 1):
        _put(ws, HEADER_ROW, c, h).font = Font(bold=True)
    for r, values in enumerate(rows, HEADER_ROW + 1):
        for c, v in enumerate(values, 1):
            cell = _put(ws, r, c, v)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for c, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(c)].width = COLUMN_WIDTHS.get(
            h, DEFAULT_WIDTH
        )
    # a filter on the header row, so an engineer can sort and filter the table
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(headers))}{HEADER_ROW + max(len(rows), 1)}"
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)


def lines_cell(lines: list[int]) -> str:
    """The "Lines" cell of a comment: the All points numbers it covers ("3, 7, 12"). The completeness check reads it back."""
    return ", ".join(str(n) for n in lines)


def comment_rows(model: dict, part: str = "comments") -> list[list]:
    """One row per COMMENT (one point, every place it applies to; `aim_review_view.comments_and_confirmations`); `part`
    "confirmations": one row per confirmation not sent, in the same columns."""
    out = []
    for p in model.get(part) or []:
        comment, c1 = cut(p["comment"])
        quote, c2 = cut(p["quote"])
        lines = p.get("lines") or [p["n"]]
        note = (
            f"Cut: the full text of each place is on the sheet {ALL_POINTS}, No. {lines_cell(lines)}."
            if c1 or c2
            else None
        )
        pages = p.get("pages") or ([p["page"]] if p["page"] is not None else [])
        page = pages[0] if len(pages) == 1 else (", ".join(map(str, pages)) or None)
        out.append([p["n"], lines_cell(lines), p["field"], page, p["shown_label"], comment, quote, p["standard"], p["clause"],
                    p["source"], p["item_id"], note, model["mark"]])  # fmt: skip
    return out


def numbers_text(nums) -> str | None:
    """The judge's numbers in one line: "paper 25 bar <= rule 20 bar" (a part not given is left out); None when none."""
    if not isinstance(nums, dict):
        return None
    paper = " ".join(
        str(nums.get(k) or "") for k in ("paper_value", "paper_unit")
    ).strip()
    rule = " ".join(str(nums.get(k) or "") for k in ("rule_value", "rule_unit")).strip()
    words = " ".join(
        x
        for x in (
            paper and f"paper {paper}",
            str(nums.get("operator") or ""),
            rule and f"rule {rule}",
        )
        if x
    )
    return words or None


def point_rows(model: dict) -> list[list]:
    out = []
    for p in model["points"]:
        comment, _ = cut(p["comment"], EXCEL_CELL_LIMIT)
        quote, _ = cut(p["quote"], EXCEL_CELL_LIMIT)
        # no bare method word ("Met", "Not met") where a person reads: the file shows the shown label only (review R1, N2)
        out.append([p["n"], p["item_id"], p["field"], p["page"], p["shown_label"], p["topic"], comment, quote,
                    "yes" if p["quote_unverified"] else None, p["code_note"], p["standard"], p["clause"], p["source"],
                    p.get("ask") or None, "yes" if p.get("deferred") else None, numbers_text(p.get("numbers")),
                    model["mark"]])  # fmt: skip
    return out


def _summary(ws: Worksheet, model: dict) -> None:
    _head(ws, "General review: summary")
    counts = model["counts"]
    lines: list[tuple[str, object]] = [
        (
            "",
            team_statement(counts["points"], counts["comments"])
            + f" ({counts['boundary']}).",
        ),
        (
            "",
            sent_statement(
                counts["points"], counts["comments"], counts.get("confirmations") or 0
            )
            + ".",
        ),
        (
            "Status",
            model["status"]
            + (f": {model['stop_reason']}" if model.get("stop_reason") else ""),
        ),
        ("Kind of paper", model["identity"].get("kind")),
        ("Equipment type", model["identity"].get("equipment_type")),
        ("Subject", model["identity"].get("subject")),
        ("Method", model["method"]),
        # piece G: the measured score of this paper's kind; a null prints as an empty cell ("below target" / "not measured yet")
        ("Measured score of this kind", (model.get("measured") or {}).get("sentence")),
    ]
    row = 4
    for label, value in lines:
        _put(ws, row, 1, label).font = Font(bold=True)
        _put(ws, row, 2, value)
        row += 1
    row += 1
    _put(ws, row, 1, "Points by label").font = Font(bold=True)
    row += 1
    for label, n in counts["by_shown_label"].items():
        _put(ws, row, 1, label or "(no label stored)")
        _put(ws, row, 2, n)
        row += 1
    row = _books_part(ws, model, row)
    row += 1
    usd = model["cost"]["usd"]
    _put(ws, row, 1, "Cost of this review (USD)").font = Font(bold=True)
    _put(ws, row, 2, None if usd is None else round(usd, 4))
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 80


def _books_part(ws: Worksheet, model: dict, row: int) -> int:
    """The summary's rule-book part (used, with each reason; not readable, counted; not held; not listed); returns the next row."""
    row += 1
    _put(ws, row, 1, "Rule books used").font = Font(bold=True)
    row += 1
    listed = model.get("documents_listed")
    if (
        listed
    ):  # an older run has no stored list: nothing is said (null renders as nothing)
        _put(ws, row, 1, listed["sentence"])
        row += 1
    for b in model["books"]:
        _put(ws, row, 1, b["title"])
        _put(ws, row, 2, b["why"])
        row += 1
    if model.get("books_not_readable"):
        _put(
            ws,
            row,
            1,
            f"{model['books_not_readable']} more rule book(s) the reader of this file may not open (counted, not named)",
        )
        row += 1
    if not model["books"] and not model.get("books_not_readable"):
        _put(ws, row, 1, "none")
        row += 1
    row += 1
    _put(ws, row, 1, "Rule books not held").font = Font(bold=True)
    row += 1
    for nh in model["not_held"]:
        _put(ws, row, 1, nh["name"])
        _put(ws, row, 2, nh["why"])
        row += 1
    if not model["not_held"]:
        _put(ws, row, 1, "none")
        row += 1
    if model["unlisted_books"]["sentence"]:
        row += 1
        _put(ws, row, 1, model["unlisted_books"]["sentence"])
        row += 1
    return row


def _how(ws: Worksheet, model: dict) -> None:
    _head(ws, "How this review was made")
    ck = model["checklist"]
    reused = ck["reused"]
    facts = [
        ("Checklist key", ck["key"]),
        ("Checklist items", ck["items"]),
        ("Items every review checks besides the checklist", ck.get("always_items")),
        ("Checklist built from", ck["built_from"]),
        (
            "Checklist",
            None
            if reused is None
            else (
                "reused from an earlier review" if reused else "built for this review"
            ),
        ),
        ("Run", model["run_id"]),
        ("Started", model["created_at"]),
        ("Finished", model["finished_at"]),
        (
            "Seconds",
            None if model.get("seconds") is None else round(float(model["seconds"]), 1),
        ),
    ]
    row = 4
    for label, value in facts:
        _put(ws, row, 1, label).font = Font(bold=True)
        _put(ws, row, 2, value)
        row += 1
    row += 1
    for c, h in enumerate(
        (
            "Step",
            "Model",
            "USD",
            "Seconds",
            "Input tokens",
            "Output tokens",
            "Finished ok",
            "Code",
        ),
        1,
    ):
        _put(ws, row, c, h).font = Font(bold=True)
    for call in model["calls"]:
        row += 1
        ok = call.get("ok")
        for c, v in enumerate(
            (call.get("step"), call.get("model"), call.get("usd"), call.get("seconds"), call.get("input_tokens"),
             call.get("output_tokens"), None if ok is None else ("yes" if ok else "no"), call.get("code")), 1,
        ):  # fmt: skip
            _put(ws, row, c, v)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50


def build(model: dict) -> bytes:
    """The workbook of ONE general run, from the view's dict. Team copy only."""
    wb = Workbook()
    summary = wb.active
    summary.title = SUMMARY
    _summary(summary, model)
    ws = wb.create_sheet(COMMENTS)
    _head(
        ws,
        f"Comments: {model['counts']['comments']} of {model['counts']['points']} points",
    )
    _put(
        ws,
        3,
        1,
        f"{model['counts']['comments']} comments from {model['counts']['points']} points reviewed; every point is on the sheet {ALL_POINTS}.",
    )
    _table(
        ws,
        COMMENT_HEADERS,
        comment_rows(model),
    )
    ws = wb.create_sheet(CONFIRMATIONS)
    _head(ws, f"Confirmations (not sent): {model['counts'].get('confirmations') or 0}")
    _put(
        ws,
        3,
        1,
        "Points the AI only asks the vendor to confirm (the value is stated and nothing is suspected): kept here, not sent; "
        f"every point is on the sheet {ALL_POINTS}.",
    )
    _table(ws, COMMENT_HEADERS, comment_rows(model, "confirmations"))
    ws = wb.create_sheet(ALL_POINTS)
    _head(ws, f"All points: {model['counts']['points']}")
    _put(ws, 3, 1, team_statement(model["counts"]["points"]))
    _table(
        ws,
        POINT_HEADERS,
        point_rows(model),
    )
    ws = wb.create_sheet(HOW)
    _how(ws, model)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
