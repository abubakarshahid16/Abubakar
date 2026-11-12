"""The facts the AI reviewer's CRS header block prints, read from what the app already holds for the document (order 13).

Reads only. A value the app does not hold is '' (CLAUDE.md rule 4: null renders as nothing; never invented). No model name and no
run number here: those live on the Notes sheet of the internal copy only.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

FIELDS = ("project", "document_number", "title", "revision", "date", "discipline")
#: The two extra header facts (12 Nov 2026, owner decision, #1584: "the engine on the sheet header"): who read the paper, in plain
#: words, never a model id and never a run number; and, for a kind not scored against an answer key, the draft sentence.
REVIEWED_BY, DRAFT_NOTE = "reviewed_by", "draft_note"


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def equipment_words(equipment_type: object) -> str:
    """An equipment type of the app's vocabulary in plain words ('pressure_relief_valve' -> 'pressure relief valve')."""
    return _text(str(equipment_type or "").replace("_", " "))


def document_header(
    conn, document_id: str, equipment_type: object = None
) -> dict[str, str]:
    """{project, document_number, title, revision, date, discipline} of one document from `document_classification`.
    The discipline is the stored one (the cover's own words, else its canonical spelling); when none is stored, the
    equipment type the CALLER names in plain words (a procedure's CRS names no equipment type: the normal reviewer names none); else ''."""
    row = conn.execute(
        "SELECT project, document_number, title, revision, effective_date, discipline, discipline_canonical, equipment_type"
        " FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    got: Mapping = dict(row) if row is not None else {}
    discipline = _text(got.get("discipline_canonical")) or _text(got.get("discipline"))
    discipline = discipline or equipment_words(equipment_type)
    return {
        "project": _text(got.get("project")),
        "document_number": _text(got.get("document_number")),
        "title": _text(got.get("title")),
        "revision": _text(got.get("revision")),
        "date": _text(got.get("effective_date")),
        "discipline": discipline,
    }


def header_for_run(conn, review_run_id: str) -> dict[str, str]:
    """`document_header` of the paper a review run reviewed (the normal reviewer's export knows only the run id); every value
    '' when the run or the paper is not found."""
    row = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    if not row:
        return dict.fromkeys(FIELDS, "")
    return {
        **document_header(conn, row[0]),
        **engine_facts(conn, review_run_id, row[0], ai=False),
    }


def reviewed_by(review_run_id: str, *, ai: bool, usd: float | None = None) -> str:
    """The ENGINE that ran, in plain words, for the header of both copies of a sheet. `ai`: the AI reviewer's sheet. Read from what
    the run really did, not from what was planned: the AI reviewer's own cost figure (`usd`, None when no model was asked) and, for the
    rule check, the spend ledger's lines for THIS run (a step that went to Claude left one; none means it all ran on the local
    model). A mixed run names each part. No model id, no run number."""
    if ai:
        # `usd` is None when no model was asked (the run's own record says so)
        if usd is not None:
            return "AI reviewer on Claude"
        return "AI reviewer (no model was asked on this run)"
    from . import claude_spend, local_engine_bar

    steps = sorted(
        {
            str(e.get("step") or "")
            for e in claude_spend.entries()
            if e.get("run") == review_run_id
            and not e.get("refused")
            and not e.get("estimated_refusal")
        }
        - {""}
    )
    if not steps:
        return "rule check on the local model"
    named = "; ".join(sorted({local_engine_bar._words(st) for st in steps}))
    return f"rule check on the local model, with Claude for: {named}"


def draft_note(conn, document_id: str) -> str:
    """The sentence for a paper whose kind has not been scored against an answer key; '' for a scored kind or an unknown one."""
    from . import agent_review_gate, agent_review_kind

    got = agent_review_kind.read_kind(conn, document_id)
    kind = got.get("kind") if got.get("known") else None
    if not kind or agent_review_gate.kind_scored(kind):
        return ""
    return agent_review_gate.UNSCORED_WORDS + "."


def engine_facts_of(run_id: str, document_id: str, usd: float | None) -> dict[str, str]:
    """`engine_facts` for the AI reviewer's sheet, on the calling thread's own connection."""
    from .db import connect

    return engine_facts(connect(), run_id, document_id, ai=True, usd=usd)


def engine_facts(
    conn, review_run_id: str, document_id: str, *, ai: bool, usd: float | None = None
) -> dict[str, str]:
    """{reviewed_by, draft_note} for a header; each '' when it cannot be read (never invented)."""
    try:
        return {
            REVIEWED_BY: reviewed_by(review_run_id, ai=ai, usd=usd),
            DRAFT_NOTE: draft_note(conn, document_id),
        }
    except Exception as exc:  # noqa: BLE001 - a header never breaks an export
        logging.getLogger(__name__).warning(
            "sheet header: engine facts unreadable (%s)", type(exc).__name__
        )
        return {REVIEWED_BY: "", DRAFT_NOTE: ""}
