"""The files of a general review (#1690, #781): the internal CRS, and two copies that are EMPTY on purpose.

Nothing of this mode ever reaches the contractor copy or the comment-only copy: both are written with the one line "general
review: internal only", whatever the lines are. The internal workbook has a sheet per class (AI notes, Queries and lines not
reviewed, Not checked) and a sheet that names the project papers that were used, the papers that were not (held rule books)
and the counts of what was dropped, by reason (counts only, no text). Every line is re-run through the single exit first, so a
writer can only ever carry a line of the four classes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from . import agent_general_review as core
from .agent_general_review import (
    CLASS_NOT_CHECKED,
    CLASS_NOT_REVIEWED,
    CLASS_NOTE,
    CLASS_QUERY,
)
from .agent_review_crs import _sheet, _wb

NOTE_TOP = "AI review, engineer to confirm. General review: no rule book. Internal only. No Pass or Fail in this mode."
HEADERS = (
    "Line",
    "Part",
    "Class",
    "Word",
    "Sub-kind",
    "Text",
    "Quote A (document, page)",
    "Quote B (document, page)",
    "Text source",
    "Figures (by code)",
    "Severity (model's opinion)",
    "Second model",
    "Second model's reason",
    "Rule book",
)
COPY_NAMES = ("crs-contractor.xlsx", "crs-scoring-comment-only.xlsx")


def _q(q: Mapping | None) -> str:
    return "" if not q else f"{q.get('document')} p.{q.get('page')}: {q.get('text')}"


def row_of(ln: Mapping) -> list:
    """One workbook row. The text is the WHOLE text of the line: nothing is cut."""
    q_a = ln.get("quote_a") or ln.get("quote_paper")
    q_b = ln.get("quote_b") or ln.get("quote_other")
    return [
        ln["line_id"],
        core.PART_WORDS[ln["part"]],
        ln["verdict_class"],
        ln["word"],
        ln.get("subkind") or "",
        ln["text"],
        _q(q_a),
        _q(q_b),
        ln.get("text_source") or "",
        ln.get("figures") or "",
        ln.get("severity_models_opinion") or "",
        ", ".join(ln.get("second_model") or []),
        ln.get("second_model_reason") or "",
        ln.get("rule_book") or ", ".join(ln.get("held_rule_books") or []),
    ]


def write_empty_copy(path: Path) -> None:
    wb = _wb()
    ws = wb.active
    ws.title = "CRS"
    ws.append([core.INTERNAL_ONLY])
    wb.save(path)


def write_all(
    lines: list[Mapping],
    folder: Path,
    meta: Mapping,
    project_papers: list[Mapping],
    dropped: Mapping,
) -> dict:
    """Write the internal workbook and the two empty copies; returns counts only."""
    folder.mkdir(parents=True, exist_ok=True)
    final = [
        core.finalize_line(ln) for ln in lines
    ]  # the writer takes nothing that did not leave through the exit
    wb = _wb()
    notes = [ln for ln in final if ln["verdict_class"] == CLASS_NOTE]
    _sheet(
        wb,
        "General review",
        meta,
        NOTE_TOP,
        HEADERS,
        [row_of(ln) for ln in notes],
        first=True,
    )
    _sheet(wb, "Queries", meta, "Query for the engineer (silence is a Query) and lines that were not reviewed.", HEADERS,
           [row_of(ln) for ln in final if ln["verdict_class"] in (CLASS_QUERY, CLASS_NOT_REVIEWED)])  # fmt: skip
    _sheet(wb, "Not checked", meta, "Rule books the paper cites that we do not hold, and held rule books not used here. Not a finding.",
           HEADERS, [row_of(ln) for ln in final if ln["verdict_class"] == CLASS_NOT_CHECKED])  # fmt: skip
    used = [[p["document_id"], p["name"]] for p in project_papers] or [
        ["", core.NO_PROJECT_PAPER]
    ]
    _sheet(wb, "Papers used", meta, "The project papers this paper was checked against (named by the person who started the run).",
           ("Document", "Name"), used)  # fmt: skip
    _sheet(wb, "Dropped (counts only)", meta, "Findings not shown, counted by reason. No text.", ("Part", "Reason", "Count"),
           [[core.PART_WORDS[int(p)], r, n] for p, c in dropped.items() for r, n in c.items()])  # fmt: skip
    wb.save(folder / "crs-internal.xlsx")
    for name in COPY_NAMES:  # nothing of this mode reaches them
        write_empty_copy(folder / name)
    return {
        "lines": len(final),
        "per_class": dict(Counter(ln["verdict_class"] for ln in final)),
    }


__all__ = [
    "COPY_NAMES",
    "HEADERS",
    "NOTE_TOP",
    "row_of",
    "write_all",
    "write_empty_copy",
]
