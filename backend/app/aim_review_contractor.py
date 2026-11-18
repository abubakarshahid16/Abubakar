"""The CONTRACTOR COPY of a signed-off general review (order 14, the engineer's sign-off; lead's design points 5 to 7).

Built from the SAME view the page and the team file read, after the engineer decided every comment: the accepted and edited comments (the
engineer's text replaces the AI's "We ask"; the original stays in the team file) and the accepted confirmations, in the card columns
(Severity, Title, Paper says, Rule says, We ask, Applies to, Page). Left out: rejected comments, All points, every technical column, the
notes, the model's words, cost, the measured score and the "why" of the rule books. The AI mark gives way to the signer's
name and date.

HARD RULES, in code: (1) no internal text reaches the file: every cell is scanned for ids, the AI mark, model names and recorded code
notes, and the copy is refused (the comment is named) rather than issued with one; (2) a card that carries the fixed words of a book the
signer may not read is refused the same way (the engineer edits or rejects it: a contractor never reads a book's name through us);
(3) the first sheet states "N points reviewed, M in this file, K not issued: <reasons with counts>" in POINTS, and the file's rows are
read back: M must equal the points the rows say they cover.

No model, no network, no database: a pure function of the view and the sign-off's name, date and code.
"""

from __future__ import annotations

import re
from collections import Counter
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font

from . import aim_review_decisions as D
from . import aim_review_view
from .aim_review_gate import AI_MARK
from .aim_review_sheet import (
    COLUMN_WIDTHS,
    HEADER_ROW,
    SEVERITY_FILLS,
    _put,
    applies_text,
)
from .crs_export import safe_cell_text

SUMMARY, COMMENTS, CONFIRM = "Summary", "Comments", "Please confirm"
HEADERS = (
    "No.",
    "Severity",
    "Title",
    "Paper says",
    "Rule says",
    "We ask",
    "Applies to",
    "Page",
    "Places",
    "Contractor response",
)
REASON_REJECTED = "rejected by the engineer"
REASON_NOT_COMMENT = "points that need no comment (met, not applicable, not judged)"
#: What a contractor file must never carry: ids, the AI mark, model names, recorded code notes. A hit names the comment.
INTERNAL = (
    (r"\bdoc_[0-9a-f]{6,}\b", "a document id"),
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "a run id"),
    (r"\bu_[A-Za-z0-9_]{3,}\b", "a user id"),
    (re.escape(AI_MARK) + r"|\bAI opinion\b|\bAI\b", "the AI mark"),
    (r"(?i)\b(claude|sonnet|opus|haiku|anthropic|ollama|qwen)\b", "a model name"),
    (
        r"(?i)reference_checked|provisional_|compare_kind|code_note|not_judged|paper_compare_passed",
        "a recorded code note",
    ),
    (r"aim-1", "the method version"),
)
#: The fixed words a page shows instead of a book or a package part the viewer may not read (the second is the reference-paper step's; it
#: is repeated here so this module does not depend on that branch).
HIDDEN = (
    aim_review_view.HIDDEN_BOOK_WORDS,
    "Checked against a part of the contract package that you may not open.",
)


class NotIssuable(ValueError):
    """The copy cannot be issued; `blockers` names each comment and why (plain words, comment numbers, no text of the paper)."""

    def __init__(self, blockers: list[dict]) -> None:
        super().__init__(
            "; ".join(f"{b['part']} {b['n']}: {b['why']}" for b in blockers)
        )
        self.blockers = blockers


def _issued(view: dict) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """([(part, comment) issued], [(part, comment) rejected]) in page order; undecided cannot occur (the caller checked)."""
    mine, rejected = [], []
    for part, group in (
        ("comment", view["comments"]),
        ("confirmation", view.get("confirmations") or []),
    ):
        for c in group:
            (
                rejected if (c.get("decision") or {}).get("state") == D.REJECT else mine
            ).append((part, c))
    return mine, rejected


def _ask(c: dict) -> str:
    d = c.get("decision") or {}
    return (d.get("text") if d.get("state") == D.EDIT else c.get("we_ask")) or ""


def _problems(part: str, c: dict, cells: dict) -> list[dict]:
    out = []
    for text in cells.values():
        text = str(text or "")
        for pattern, what in INTERNAL:
            if re.search(pattern, text):
                out.append(
                    {
                        "part": part,
                        "n": c["n"],
                        "why": f"its text carries {what}: edit it or reject it",
                    }
                )
        if any(h and h in text for h in HIDDEN):
            out.append(
                {
                    "part": part,
                    "n": c["n"],
                    "why": "it rests on a book or paper this copy cannot name: edit it or reject it",
                }
            )
    seen, unique = set(), []
    for b in out:
        key = (b["part"], b["n"], b["why"])
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def _row(c: dict, number: int) -> dict:
    pages = c.get("pages") or ([c["page"]] if c.get("page") is not None else [])
    return {
        "No.": number, "Severity": c.get("severity"), "Title": c.get("title"), "Paper says": c.get("paper_says") or None,
        "Rule says": c.get("rule_says") or None, "We ask": _ask(c) or None, "Applies to": applies_text(c.get("applies_to")),
        "Page": pages[0] if len(pages) == 1 else (", ".join(map(str, pages)) or None), "Places": len(c.get("lines") or [c["n"]]),
        "Contractor response": None,
    }  # fmt: skip


def counts_of(view: dict) -> dict:
    """The points: N reviewed, M in the file, K not issued with their reasons (points, so M + K = N always)."""
    mine, rejected = _issued(view)
    n = view["counts"]["points"]
    covered = sum(len(c.get("lines") or [c["n"]]) for _p, c in (*mine, *rejected))
    m = sum(len(c.get("lines") or [c["n"]]) for _p, c in mine)
    reasons = Counter({REASON_REJECTED: covered - m, REASON_NOT_COMMENT: n - covered})
    return {"points": n, "in_file": m, "not_issued": n - m, "reasons": {k: v for k, v in reasons.items() if v},
            "comments": sum(1 for p, _ in mine if p == "comment"), "confirmations": sum(1 for p, _ in mine if p == "confirmation")}  # fmt: skip


def statement(counts: dict) -> str:
    why = "; ".join(f"{v} {k}" for k, v in sorted(counts["reasons"].items())) or "none"
    return f"{counts['points']} points reviewed, {counts['in_file']} in this file, {counts['not_issued']} not issued: {why}"


def build(
    view: dict, *, signed_by: str, signed_at: str, code: str
) -> tuple[bytes, dict]:
    """(the contractor workbook, its counts). Raises `NotIssuable` naming each comment that carries internal text."""
    mine, _rejected = _issued(view)
    counts = counts_of(view)
    rows: dict[str, list[dict]] = {"comment": [], "confirmation": []}
    blockers: list[dict] = []
    for part, c in mine:
        row = _row(c, len(rows[part]) + 1)
        blockers += _problems(part, c, row)
        rows[part].append(row)
    if blockers:
        raise NotIssuable(blockers)
    wb = Workbook()
    ws = wb.active
    ws.title = SUMMARY
    _put(
        ws, 1, 1, f"Comment sheet: signed off by {signed_by}, {signed_at[:10]}"
    ).font = Font(bold=True, size=13)
    lines = [("Review code", code), ("Points", statement(counts)),
             ("Comments", f"{counts['comments']} comments" + (f" and {counts['confirmations']} to confirm" if counts["confirmations"] else ""))]  # fmt: skip
    for r, (label, value) in enumerate(lines, 3):
        _put(ws, r, 1, label).font = Font(bold=True)
        _put(ws, r, 2, value)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 16, 110
    for name, part in ((COMMENTS, "comment"), (CONFIRM, "confirmation")):
        if part == "confirmation" and not rows[part]:
            continue
        sheet = wb.create_sheet(name)
        _put(
            sheet, 1, 1, f"{name}: signed off by {signed_by}, {signed_at[:10]}"
        ).font = Font(bold=True)
        for c, h in enumerate(HEADERS, 1):
            _put(sheet, HEADER_ROW, c, h).font = Font(bold=True)
            sheet.column_dimensions[chr(64 + c)].width = (
                COLUMN_WIDTHS.get(h, 12) if h != "Places" else 8
            )
        for r, row in enumerate(rows[part], HEADER_ROW + 1):
            for c, h in enumerate(HEADERS, 1):
                cell = _put(sheet, r, c, row[h])
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            sev = sheet.cell(row=r, column=2)
            if sev.value in SEVERITY_FILLS:
                from openpyxl.styles import PatternFill

                sev.fill = PatternFill("solid", fgColor=SEVERITY_FILLS[sev.value])
        sheet.auto_filter.ref = f"A{HEADER_ROW}:{chr(64 + len(HEADERS))}{HEADER_ROW + max(len(rows[part]), 1)}"
        sheet.freeze_panes = sheet.cell(row=HEADER_ROW + 1, column=1)
    out = BytesIO()
    wb.save(out)
    data = out.getvalue()
    read_back(data, counts)
    return data, counts


def read_back(data: bytes, counts: dict) -> None:
    """The file's rows against its own statement: the points the rows say they cover must equal M, and no cell carries internal text.
    Raises `NotIssuable` otherwise (a bug or a hand-edited file: never issued)."""
    wb = load_workbook(BytesIO(data))
    covered = 0
    for name in (COMMENTS, CONFIRM):
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        places = HEADERS.index("Places") + 1
        for r in range(HEADER_ROW + 1, ws.max_row + 1):
            if ws.cell(row=r, column=1).value is not None:
                covered += int(ws.cell(row=r, column=places).value or 0)
    if (
        covered != counts["in_file"]
        or counts["in_file"] + counts["not_issued"] != counts["points"]
    ):
        raise NotIssuable(
            [
                {
                    "part": "file",
                    "n": 0,
                    "why": "the rows do not add up to the points stated on the first sheet",
                }
            ]
        )
    bad = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if isinstance(v, str) and any(
                    re.search(p, safe_cell_text(v)) for p, _w in INTERNAL
                ):
                    bad.append(
                        {
                            "part": "file",
                            "n": 0,
                            "why": f"a cell of the sheet {ws.title} carries internal text",
                        }
                    )
    if bad:
        raise NotIssuable(bad[:1])
