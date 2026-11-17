"""The facts the AI reviewer's CRS header block prints, read from what the app already holds for the document (order 13).

Reads only. A value the app does not hold is '' (CLAUDE.md rule 4: null renders as nothing; never invented). No model name and no
run number here: those live on the Notes sheet of the internal copy only.
"""

from __future__ import annotations

import logging
import sqlite3
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


NOT_ON_COVER = "not found on the cover"


def with_cover(conn, document_id: str, head: dict[str, str]) -> dict[str, str]:
    """LPC (C5): sheet 1's document number and revision, read on the paper's COVER (`contract_package.cover_id`: the top lines of
    pages 1 and 2). The number: the cover's document number, else the one the app holds, else the cover's contract number (saying
    it is one), else "not found on the cover". The revision: the cover's revision value, else the one held, else "not found on
    the cover". Never guessed. A copy of `head`; the download name still reads `document_header`."""
    from . import contract_package

    try:
        cover = contract_package.cover_id(
            contract_package.load_pages(conn, document_id, contract_package.COVER_PAGES)
        )
    except (
        sqlite3.Error
    ):  # no page text to read: the value the app holds, else "not found"
        cover = contract_package.CoverId()
    # the paper's own document number first (the cover's, else the one held); a contract number only when neither is known
    contract = f"{cover.number} ({cover.number_label})" if cover.number else None
    number = cover.document_number or head.get("document_number") or contract
    revision = cover.revision or head.get("revision")
    return {
        **head,
        "document_number": number or NOT_ON_COVER,
        "revision": revision or NOT_ON_COVER,
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


LOCAL_AI_WORDS = "AI reviewer on the local model (this computer; nothing sent out)"

# ------------------------------------------------------------------------------------------------ which engine read a line (FTU-17)

#: FTU-17: the ONE home of "which engine read this line of the AI review": the page's points, the points route and the one CRS file
#: (`crs_one`) all take their engine from here, so a run on the local model is never labelled "on Claude" in one place and "Local" in
#: another. Read from what was STORED: the line's own engine or model, else the models the run stored (`agent_review_run.models_json`).
ENGINE_CLAUDE, ENGINE_LOCAL, ENGINE_BOTH, ENGINE_UNKNOWN = "claude", "local", "both", ""
AI_ON_CLAUDE = "AI reviewer on Claude"
AI_ON_LOCAL = "AI reviewer on the local model"
_ENGINE_WORDS = {
    ENGINE_CLAUDE: AI_ON_CLAUDE,
    ENGINE_LOCAL: AI_ON_LOCAL,
    ENGINE_BOTH: "AI reviewer on Claude and the local model",
    ENGINE_UNKNOWN: "AI reviewer (engine not recorded)",
}
_ENGINE_SHORT = {
    ENGINE_CLAUDE: "Claude",
    ENGINE_LOCAL: "Local",
    ENGINE_BOTH: "Claude and Local",
    ENGINE_UNKNOWN: "not recorded",
}


def _is_claude(model: object) -> bool:
    return "claude" in _text(model).lower()


def _local_models() -> frozenset[str]:
    """The model names the app's OWN settings run on this computer (the local reviewer's two readers, the answer model and the small
    task models): the positive fact behind "local". A name outside this list and not a Claude model is not recorded, never "local"."""
    from .config import settings

    names = ("agent_review_local_model_a", "agent_review_local_model_b", "answer_model", "ai_task_model", "p1_ai_model",
             "datasheet_ai_ollama_model")  # fmt: skip
    return frozenset(_text(getattr(settings, n, "")).lower() for n in names) - {""}


def engine_of_models(models) -> str:
    """The engine of a list of stored model names: Claude, the local model, both, or unknown. "Local" only for a name the app's own
    local settings name (review of PR #1872: never by exclusion); any name that is neither makes the whole list unknown."""
    names = [_text(m).lower() for m in (models or []) if _text(m)]
    if not names:
        return ENGINE_UNKNOWN
    local = _local_models()
    kinds = {
        ENGINE_CLAUDE
        if _is_claude(m)
        else ENGINE_LOCAL
        if m in local
        else ENGINE_UNKNOWN
        for m in names
    }
    if ENGINE_UNKNOWN in kinds:
        return ENGINE_UNKNOWN
    return kinds.pop() if len(kinds) == 1 else ENGINE_BOTH


def engine_of_line(line: Mapping, run_engine: str = ENGINE_UNKNOWN) -> str:
    """The engine that read ONE line: its own stored engine ("claude" / "local"), else its own stored model name, else the run's."""
    own = _text(line.get("engine")).lower()
    if own in (ENGINE_CLAUDE, ENGINE_LOCAL):
        return own
    if (
        _text(line.get("model"))
        and (got := engine_of_models([line.get("model")])) != ENGINE_UNKNOWN
    ):
        return got
    return run_engine


def run_engine(conn, run_id: str | None) -> str:
    """The engine of one AI review run from the models it stored; unknown when the run or its models are not recorded."""
    import json

    if (
        not run_id
        or not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_run'"
        ).fetchone()
    ):
        return ENGINE_UNKNOWN
    row = conn.execute(
        "SELECT models_json FROM agent_review_run WHERE run_id = ?", (run_id,)
    ).fetchone()
    try:
        return engine_of_models(json.loads(row["models_json"] or "[]") if row else [])
    except (TypeError, ValueError):
        return ENGINE_UNKNOWN


def engine_words(engine: str) -> str:
    """The engine in the words a point carries ("AI reviewer on the local model")."""
    return _ENGINE_WORDS.get(engine, _ENGINE_WORDS[ENGINE_UNKNOWN])


def engine_short(engine: str) -> str:
    """The engine in the words of the CRS header ("Local")."""
    return _ENGINE_SHORT.get(engine, _ENGINE_SHORT[ENGINE_UNKNOWN])


def reviewed_by(
    review_run_id: str,
    *,
    ai: bool,
    usd: float | None = None,
    local: bool = False,
    models=None,
) -> str:
    """The ENGINE that ran, in plain words, for the header of both copies of a sheet. `ai`: the AI reviewer's sheet. Read from what
    the run really did, not from what was planned: the AI reviewer's own cost figure (`usd`, None when no model was asked) and, for the
    rule check, the spend ledger's lines for THIS run (a step that went to Claude left one; none means it all ran on the local
    model). A mixed run names each part. No model id, no run number."""
    if ai and local:
        return LOCAL_AI_WORDS
    if ai:
        # `usd` is None when no model was asked (the run's own record says so)
        if usd is None:
            return "AI reviewer (no model was asked on this run)"
        # review of PR #1872: the one home of the engine (`engine_of_models`), never "on Claude" from a cost alone
        if models is None:
            from .db import connect

            got = run_engine(connect(), review_run_id)
        else:
            got = engine_of_models(models)
        return LOCAL_AI_WORDS if got == ENGINE_LOCAL else engine_words(got)
    from . import local_engine_bar, review_engine

    steps = review_engine.ran_steps(
        review_run_id
    )  # the fact saved at the end of the run, else the ledger's
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


def engine_facts_of(
    run_id: str, document_id: str, usd: float | None, local: bool = False, models=None
) -> dict[str, str]:
    """`engine_facts` for the AI reviewer's sheet, on the calling thread's own connection. `local`: the run read the paper on the
    local model (its cost is 0.0, never "on Claude")."""
    from .db import connect

    return engine_facts(
        connect(), run_id, document_id, ai=True, usd=usd, local=local, models=models
    )


def engine_facts(
    conn,
    review_run_id: str,
    document_id: str,
    *,
    ai: bool,
    usd: float | None = None,
    local: bool = False,
    models=None,
) -> dict[str, str]:
    """{reviewed_by, draft_note} for a header; each '' when it cannot be read (never invented)."""
    try:
        return {
            REVIEWED_BY: reviewed_by(
                review_run_id, ai=ai, usd=usd, local=local, models=models
            ),
            DRAFT_NOTE: draft_note(conn, document_id),
        }
    except Exception as exc:  # noqa: BLE001 - a header never breaks an export
        logging.getLogger(__name__).warning(
            "sheet header: engine facts unreadable (%s)", type(exc).__name__
        )
        return {REVIEWED_BY: "", DRAFT_NOTE: ""}
