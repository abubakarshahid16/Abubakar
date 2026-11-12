"""The files of a general review (#1690, #781; order 13: ONE layout).

The workbooks are drawn by `crs_layout.build_layout_crs`, the drawing code the rule review shares: the nine company columns and
Status on the CRS sheet, then the sheets "Not reviewed or not applicable", Evidence and Notes (internal copy). The words come
from `crs_ai_words` (the Statuses, the priority rule, the plain-text filter). A general review has no rule book to hold the paper
to, so a line is never Pass or Fail: an AI note is Status "AI opinion", a question for the engineer is "Query" (worded
"Contractor to confirm ..."), a line that was not reviewed or a rule book we do not hold goes to the second sheet. A comment has
three parts, one per line: what the rule (or checklist point, or project paper) requires, what the paper shows (a quote code
verified, with its page), what the contractor must do.

The contractor copy and the comment-only copy hold the nine company columns and NO rows: a general review proves no Fail, and the
contractor copy shows proven Fail only. Every line is re-run through the single exit first, so a writer can only ever carry a
line of the four classes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from . import agent_general_review as core
from . import crs_ai_words as words
from . import crs_export, crs_layout, kind_review_table
from .agent_general_review import (
    CLASS_NOT_CHECKED,
    CLASS_NOT_REVIEWED,
    CLASS_NOTE,
    CLASS_QUERY,
)
from .agent_run_crs import _cell, _page_cell

COPY_NAMES = ("crs-contractor.xlsx", "crs-scoring-comment-only.xlsx")
NO_FAIL_NOTE = "General review: no rule book, so no Pass or Fail. The contractor copy shows proven Fail only, so it holds no rows."
#: A line of the general review -> the Status word and the row order of the one layout.
ITEM_STATUS = {
    CLASS_NOTE: (words.STATUS_AI, words.ORDER_AI_NOT_MET),
    CLASS_QUERY: (words.STATUS_QUERY, words.ORDER_QUERY),
}
OTHER_KIND = {
    CLASS_NOT_REVIEWED: words.KIND_NOT_REVIEWED,
    CLASS_NOT_CHECKED: words.KIND_NOT_HELD,
}
EVIDENCE_COLUMNS = (
    "Item No", "Status", "Part", "Sub-kind", "Paper quote", "Paper page", "Other quote", "Other page", "Other document",
    "Quotes checked by code", "Figures (by code)", "Second reader's reason", "Text source", "Line id (internal)",
)  # fmt: skip
EVIDENCE_WIDTHS = (
    9.0,
    13.0,
    22.0,
    26.0,
    50.0,
    9.0,
    50.0,
    9.0,
    26.0,
    16.0,
    26.0,
    40.0,
    20.0,
    24.0,
)
OTHER_COLUMNS = (
    "Item No", "Document Name", "Part", "Rule book or document", "What it is", "Reason",
)  # fmt: skip
OTHER_WIDTHS = (9.0, 26.0, 20.0, 26.0, 30.0, 90.0)
UNREAD_WHAT = "the content of the pages that were not read as text"


def _c(text) -> str:
    return " ".join(str(text or "").split())


def _quote(q: Mapping | None) -> tuple[str, object]:
    """(quote text, page) of a verified quote, or ('', None)."""
    return (_c(q.get("text")), q.get("page")) if q else ("", None)


def _paper_quote(ln: Mapping) -> Mapping | None:
    return ln.get("quote_a") or ln.get("quote_paper")


def _other_quote(ln: Mapping) -> Mapping | None:
    return ln.get("quote_b") or ln.get("quote_other")


def _page_text(ln: Mapping) -> str | None:
    return _page_cell(_quote(_paper_quote(ln))[1])


def _what(ln: Mapping) -> str:
    """What a Query asks the contractor to confirm: the checklist point, the project paper's requirement, or the unread pages."""
    other = _c(ln.get("other_document"))
    if ln.get("subkind") == core.SUB_UNREAD:
        return UNREAD_WHAT
    if ln.get("topic"):
        return _c(ln["topic"])
    if other:
        return f"compliance with {other}"
    return words.plain(ln.get("text")) or "the point raised"


def _requires(ln: Mapping, status: str) -> str:
    """Part 1: what the rule requires. In this mode the 'rule' is the checklist point, the project paper's own requirement, the paper
    itself, or good practice; a question is worded 'Contractor to confirm ...'."""
    part, other = ln["part"], _c(ln.get("other_document"))
    oq = _quote(_other_quote(ln))[0]
    if status == words.STATUS_QUERY:
        tail = f', which requires: "{oq}".' if oq else "."
        return f"Contractor to confirm {_what(ln)}{tail}"
    if part == 2:
        topic = _c(ln.get("topic"))
        return (
            f"The completeness checklist for this kind of paper asks for: {topic}."
            if topic
            else "The completeness checklist for this kind of paper applies."
        )
    if part == 3:
        return (
            "The paper must agree with itself and every reference in it must resolve."
        )
    if part == 4:
        return (
            f'{other or "A project paper"} requires: "{oq}".'
            if oq
            else f"{other or 'A project paper'} applies to this paper."
        )
    return (
        "No rule book applies to this point; it is an engineering comment on the paper."
    )


def _paper_shows(ln: Mapping, status: str) -> str:
    """Part 2: what the paper shows: only a quote code verified, with its page; then the AI reviewer's own words, marked as its view."""
    text, page = _quote(_paper_quote(ln))
    where = f", page {page}" if page not in (None, "") else ""
    out = (
        f'The paper states "{text}"{where}.'
        if text
        else "The AI reviewer holds no verified quote from the paper for this point."
    )
    b_text, b_page = _quote(_other_quote(ln)) if ln["part"] == 3 else ("", None)
    if b_text:
        out += (
            f' It also states "{b_text}"'
            + (f", page {b_page}" if b_page not in (None, "") else "")
            + "."
        )
    view = words.plain(ln.get("text"))
    if view:
        out += (
            f" The AI reviewer's view, not proven by code: {view}"
            if status == words.STATUS_AI
            else f" {view}"
        )
    if ln.get("figures"):
        out += f" Figures: {_c(ln['figures'])}."
    return out


def _contractor_to(ln: Mapping, status: str) -> str:
    """Part 3: ONE fixed sentence per Status, completed with a label the line already carries. No free text of the reader."""
    if status == words.STATUS_QUERY:
        if ln.get("subkind") == core.SUB_UNREAD:
            return f"Contractor to confirm {UNREAD_WHAT}, or give them as text."
        return f"Contractor to state {_what(ln)}, or the page where it is shown."
    return "Contractor to check the point against the paper and confirm or correct it."


def comment_of(ln: Mapping, status: str) -> str:
    return "\n".join(
        (_requires(ln, status), _paper_shows(ln, status), _contractor_to(ln, status))
    )


def _sentence(text) -> str:
    said = words.plain(text) or "No reason was given."
    return said[:1].upper() + said[1:]


def _item_lines(final: list[Mapping]) -> list[tuple[Mapping, str, int]]:
    keyed = [
        (
            ITEM_STATUS[ln["verdict_class"]][1],
            pos,
            ln,
            ITEM_STATUS[ln["verdict_class"]][0],
        )
        for pos, ln in enumerate(final)
        if ln["verdict_class"] in ITEM_STATUS
    ]
    keyed.sort(key=lambda k: k[:2])
    return [(ln, st, order) for order, _p, ln, st in keyed]


def _row(n: int, ln: Mapping, paper: str, status: str, order: int, by: str) -> list:
    return [
        n,
        paper,
        _page_text(ln),
        comment_of(ln, status),
        by,
        None,
        None,
        _c(ln.get("other_document")) or None,
        words.priority(status, ln, order) or None,
        status,
    ]


def _table(rows: list[list]) -> list[list]:
    return [[_cell(v) for v in r] for r in rows]


def _evidence_row(n: int, ln: Mapping, status: str) -> list:
    qa, pa = _quote(_paper_quote(ln))
    qb, pb = _quote(_other_quote(ln))
    return [
        n, status, core.PART_WORDS[ln["part"]], ln.get("subkind") or "", qa, pa, qb, pb, _c(ln.get("other_document")),
        "verified by code" if ln.get("quotes_verified_by_code") else "no quote", ln.get("figures") or "",
        _c(ln.get("second_model_reason")), _c(ln.get("text_source")) or "", ln.get("line_id") or "",
    ]  # fmt: skip


def layout_view(
    lines: list[Mapping],
    meta: Mapping,
    project_papers: list[Mapping],
    dropped: Mapping,
    copy: str,
) -> dict:
    """The whole workbook as plain values for `crs_layout.build_layout_crs`. copy = 'internal' | 'contractor'. The contractor copy
    holds the nine company columns and no rows (a general review proves no Fail)."""
    paper = str(meta.get("paper") or "")
    h = meta.get("header") or {}
    contractor = copy == "contractor"
    final = [
        core.finalize_line(ln) for ln in lines
    ]  # the exporter takes nothing that did not leave through the exit
    items = [] if contractor else _item_lines(final)
    discipline = (
        meta.get("discipline")
        or h.get("discipline")
        or kind_review_table.discipline(meta.get("kind"))
    )
    by = "" if contractor else words.comment_by(discipline)
    books = sorted({_c(ln.get("rule_book")) for ln in final if ln.get("rule_book")})
    view: dict = {
        "title": "\n".join(
            p for p in (crs_export.default_company(), _c(h.get("project"))) if p
        ),
        "header": [
            ("Project:", _c(h.get("project"))),
            ("Document number:", _c(h.get("document_number"))),
            ("Document title:", _c(h.get("title"))),
            ("Revision:", _c(h.get("revision"))),
            ("Date:", _c(h.get("date"))),
            ("Discipline:", _c(discipline)),
            ("Review mode:", core.MODE_WORD + ": " + NO_FAIL_NOTE),
        ],
        "sentence": words.generated_by(crs_export.default_company()),
        "rows": _table(
            [
                _row(n, ln, paper, st, o, by)
                for n, (ln, st, o) in enumerate(items, start=1)
            ]
        ),
        "statuses": [st for _l, st, _o in items],
    }
    if contractor:
        view["columns"] = list(crs_layout.LAYOUT_COLUMNS[:9])
        view["rows"] = [r[:9] for r in view["rows"]]
        view["plain"] = True
        return view
    others = [
        (ln, OTHER_KIND[ln["verdict_class"]])
        for ln in final
        if ln["verdict_class"] in OTHER_KIND
    ]
    view["other"] = {
        "name": words.OTHER_SHEET,
        "columns": OTHER_COLUMNS,
        "rows": _table(
            [
                [
                    len(items) + k,
                    paper,
                    core.PART_WORDS[ln["part"]],
                    _c(
                        ln.get("rule_book")
                        or ", ".join(ln.get("held_rule_books") or [])
                    )
                    or None,
                    kind,
                    _sentence(ln.get("text")),
                ]
                for k, (ln, kind) in enumerate(others, start=1)
            ]
        ),
        "widths": OTHER_WIDTHS,
    }
    ev = [_evidence_row(n, ln, st) for n, (ln, st, _o) in enumerate(items, start=1)]
    ev += [
        _evidence_row(len(items) + k, ln, kind)
        for k, (ln, kind) in enumerate(others, start=1)
    ]
    view["evidence"] = {
        "columns": EVIDENCE_COLUMNS,
        "rows": _table(ev),
        "statuses": [st for _l, st, _o in items] + [None] * len(others),
        "widths": EVIDENCE_WIDTHS,
    }
    count = Counter(st for _l, st, _o in items)
    used = [_c(p.get("name")) for p in project_papers if p.get("name")]
    notes: list[list] = [
        ["Review mode", core.MODE_WORD + ": " + NO_FAIL_NOTE],
        ["Priority rule", words.priority_rule((words.STATUS_AI, words.STATUS_QUERY))],
        ["Rule books not held", "; ".join(books) or "none"],
        ["Papers used", "; ".join(used) or core.NO_PROJECT_PAPER],
        *[
            [f"Count: {s}", count.get(s, 0)]
            for s in (words.STATUS_AI, words.STATUS_QUERY)
        ],
        ["Count: rows on the CRS sheet", len(items)],
        *[
            [f"Count: {k}", sum(1 for _l, kk in others if kk == k)]
            for k in OTHER_KIND.values()
        ],
        ["Count: rows on the sheet '" + words.OTHER_SHEET + "'", len(others)],
        *[
            [f"Dropped, {core.PART_WORDS[int(p)]}: {r}", n]
            for p, c in dropped.items()
            for r, n in c.items()
        ],
        ["Run id", _c(meta.get("run_id")) or "not reported"],
        ["Date", _c(meta.get("date")) or "not reported"],
        [
            "First reader models",
            ", ".join(meta.get("lead_models") or []) or "not reported",
        ],
        [
            "Second reader models",
            ", ".join(meta.get("second_models") or []) or "not reported",
        ],
    ]
    view["notes"] = {
        "columns": ("Topic", "Detail"),
        "rows": _table(notes),
        "widths": (44.0, 120.0),
    }
    return view


def write_empty_copy(path: Path, meta: Mapping | None = None) -> None:
    path.write_bytes(
        crs_layout.build_layout_crs(layout_view([], meta or {}, [], {}, "contractor"))
    )


def write_all(
    lines: list[Mapping],
    folder: Path,
    meta: Mapping,
    project_papers: list[Mapping],
    dropped: Mapping,
) -> dict:
    """Write the internal workbook and the two nine-column copies (no rows); returns counts only."""
    folder.mkdir(parents=True, exist_ok=True)
    final = [
        core.finalize_line(ln) for ln in lines
    ]  # the writer takes nothing that did not leave through the exit
    (folder / "crs-internal.xlsx").write_bytes(
        crs_layout.build_layout_crs(
            layout_view(final, meta, project_papers, dropped, "internal")
        )
    )
    for name in COPY_NAMES:
        (folder / name).write_bytes(
            crs_layout.build_layout_crs(
                layout_view(final, meta, project_papers, dropped, "contractor")
            )
        )
    return {
        "lines": len(final),
        "per_class": dict(Counter(ln["verdict_class"] for ln in final)),
    }


__all__ = [
    "COPY_NAMES",
    "NO_FAIL_NOTE",
    "comment_of",
    "layout_view",
    "write_all",
    "write_empty_copy",
]
