"""The AI reviewer's routes (#1690). Every route answers 404 "feature_off" while `agent_review_gate.enabled()` is off.

    POST /api/reviews/agent-run                          start an AI review of one datasheet (rule review) or of one
                                                         procedure or contract (general review, no rule book); 409 for any
                                                         other kind
    GET  /api/reviews/agent-status                       {enabled, claude_lane_open}
    GET  /api/reviews/runs/{id}/agent/summary            counts per class, spend, stop reason, missing rule books
    GET  /api/reviews/runs/{id}/agent/lines              the CRS lines, one page at a time
    GET  /api/reviews/runs/{id}/agent/lines/{item}/trace page, quote, rule, clause, model, reason, every gate step
    GET  /api/reviews/runs/{id}/agent/crs?copy=...       the CRS as xlsx: internal, or contractor (proven Fail only)
    GET  /api/reviews/runs/{id}/rules-used               every rule asked or left out, and the books we do not hold

SCOPE: the same check as the other review routes (`access.current_scope`, `submittal_review.get_review_run`): a run the caller
may not read is a 404, indistinguishable from one that does not exist. A filter may only NARROW what the caller may read.
A GET never writes (no table is created by a read; a switch just turned on with no run yet answers 404). Every line is built
with the contract model's constructor, so its class / word / tier table is validated on the way out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .. import (
    access,
    agent_general_review,
    agent_review_book_table,
    agent_review_coverage,
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    agent_review_schema,
    agent_review_text,
    crs_ai_workbook,
    agent_review_wording,
    errors,
    review_jobs,
    schemas,
    submittal_review,
)
from .. import (
    admin as admin_mod,
)
from ..api_utils import (
    _require_identity_to_write,
    reject_unknown_params,
    require_document,
)
from ..db import connect
from . import agent_review_schemas as contract

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PAGE_MAX = 500


def _require_on() -> None:
    if not agent_review_gate.enabled():
        raise HTTPException(status_code=404, detail=agent_review_gate.FEATURE_OFF)
    try:  # an older line table is upgraded (data kept) here; a table that cannot be upgraded answers 503 on every route
        agent_review_schema.upgrade_if_old()
    except agent_review_schema.UpgradeFailed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


router = APIRouter(dependencies=[Depends(_require_on)])


#: whose books the count of other-book rules covers (rule 4: every count states its boundary).
OTHER_BOOKS_BOUNDARY = "rule books the person who started this review may read"


def _equipment(run: dict) -> dict:
    try:
        return json.loads(run.get("equipment_json") or "{}")
    except ValueError:
        return {}


def _run_or_404(run_id: str, scope: access.AccessScope) -> dict:
    """The run row of an AI review the caller may read; 404 otherwise (and when no table exists yet: a read creates none)."""
    run = submittal_review.get_review_run(
        run_id, allowed_document_ids=scope.allowed_document_ids
    )
    conn = connect()
    if run is None or not agent_review_schema.has_tables(conn):
        raise HTTPException(status_code=404, detail="no such AI review")
    row = conn.execute(
        "SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such AI review")
    return dict(row)


@router.get("/api/reviews/agent-status", response_model=contract.AgentStatus)
def agent_status(request: Request):
    reject_unknown_params(request, set())
    return contract.AgentStatus(
        enabled=True, claude_lane_open=agent_review_gate.claude_lane_open()
    )


@router.post(
    "/api/reviews/agent-run",
    response_model=schemas.ReviewRunSummary,
    responses={
        **schemas.ERRORS_401,
        **schemas.ERRORS_404,
        **schemas.ERRORS_409,
        **schemas.ERRORS_422,
    },
)
def start_agent_run(
    body: contract.AgentRunRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Queue an AI review of one submittal. ADMIN-GATED like the classic review. A datasheet gets the rule review; a procedure or a
    contract gets the GENERAL review (no rule book; owner, 11 Nov 2026, STATE 16.4). Any other kind, or one that is unknown, is a
    409 `kind_not_enabled` with no job, no call and no charge. `project_document_ids` (general review only) names the papers part 4
    checks against: each must be readable by the caller, else the request is refused before any job exists."""
    _require_identity_to_write(scope)
    reject_unknown_params(request, set())
    document_id = body.submittal_document_id
    require_document(document_id, scope)
    reading = agent_review_kind.decide(document_id, scope.allowed_document_ids)
    no_text = agent_review_text.read(connect(), document_id).state == "no text"
    # a paper with no stored text is queued whatever its kind: the run stops before any call and says why (never a 409 about kind)
    if not no_text and not (
        reading.known and agent_review_gate.any_kind_enabled(reading.kind)
    ):
        detail = errors.safe_error(
            errors.INVALID_PARAMETER,
            agent_review_gate.refusal_reason(),
            document_id=document_id,
        )
        raise HTTPException(
            status_code=409,
            detail={**detail, "code": agent_review_gate.KIND_NOT_ENABLED},
        )
    general = reading.known and agent_review_gate.general_kind_enabled(reading.kind)
    project = _checked_project_papers(body, document_id, scope, general)
    try:
        run_id, _job = agent_review_jobs.enqueue(
            document_id,
            allowed_document_ids=scope.allowed_document_ids,
            requested_by=scope.user_id,
            project_document_ids=project if general else None,
            fresh=body.fresh,
        )
    except review_jobs.ReviewAlreadyActive as exc:
        raise HTTPException(
            status_code=409,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                f"a review of this submittal is already queued or running ({exc.args[0]})",
            ),
        ) from exc
    from .. import main as main_mod  # main imports this module through run_summary

    run = submittal_review.get_review_run(
        run_id, allowed_document_ids=scope.allowed_document_ids
    )
    return main_mod._run_summary(run, scope)


def _checked_project_papers(
    body: contract.AgentRunRequest,
    document_id: str,
    scope: access.AccessScope,
    general: bool,
) -> tuple[str, ...]:
    """The project papers a request names, checked BEFORE any job exists (a filter may only narrow what the caller may read):
    unreadable is a 404 like every other document; a rule book, the paper itself or a document with no text is a 422."""
    if not body.project_document_ids:
        return ()
    if not general:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "project_document_ids belong to a general review (a procedure or a contract) only",
            ),
        )
    for d in body.project_document_ids:
        require_document(d, scope)
    accepted, problems = agent_general_review.check_project_papers(
        connect(), document_id, body.project_document_ids, scope.allowed_document_ids
    )
    if problems:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER,
                "project paper refused: " + "; ".join(problems),
            ),
        )
    return tuple(p["document_id"] for p in accepted)


def _counts_of(run) -> dict:
    try:
        got = json.loads(run["counts_json"] or "{}")
        return got if isinstance(got, dict) else {}
    except (ValueError, TypeError):
        return {}


def _two_reader_step(
    run, key: str = "two_reader_step"
) -> contract.AgentTwoReaderStep | None:
    """The second-reader step of the run as the run row stored it (counts and one code); None when it was off or never stored."""
    try:
        got = json.loads(run["counts_json"] or "{}").get(key)
        return contract.AgentTwoReaderStep(**got) if isinstance(got, dict) else None
    except (ValueError, TypeError):
        return None


@router.get(
    "/api/reviews/runs/{review_run_id}/agent/summary",
    response_model=contract.AgentRunSummary,
)
def agent_summary(
    review_run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    run = _run_or_404(review_run_id, scope)
    conn = connect()
    counts = {
        r["verdict_class"]: r["n"]
        for r in conn.execute(
            "SELECT verdict_class, COUNT(*) AS n FROM agent_review_line WHERE run_id = ? GROUP BY verdict_class",
            (review_run_id,),
        )
    }
    pairs = [
        (r["verdict_class"], r["word"])
        for r in conn.execute(
            "SELECT verdict_class, word FROM agent_review_line WHERE run_id = ?",
            (review_run_id,),
        )
    ]
    books = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name",
            (review_run_id,),
        )
    ]
    return contract.AgentRunSummary(
        paper_kind=run["paper_kind"],
        paper_kind_source=run["kind_source"],
        equipment_type=run["equipment_type"],
        counts_by_class=counts,
        usd=run["usd"],
        models=json.loads(run["models_json"] or "[]"),
        stop_reason=run["stop_reason"],
        missing_books=books,
        not_reviewed=counts.get("Not reviewed", 0),
        **_mode_of(conn, review_run_id),
        equipment_state=_equipment(run).get("state"),
        equipment_notes=_equipment(run).get("notes") or [],
        two_reader_step=_two_reader_step(run),
        two_reader_absence_step=_two_reader_step(run, "two_reader_absence_step"),
        two_reader_other_step=_two_reader_step(run, "two_reader_other_step"),
        decisions=contract.AgentDecisions(**agent_review_wording.decisions_of(pairs)),
        paper_text=_paper_text(run),
        page_reread_stopped=_equipment(run).get("page_reread"),
        answers_reused=_counts_of(run).get("answers_reused"),
        changed_since_previous=_counts_of(run).get("changed_since_previous"),
    )


def _paper_text(run: dict) -> contract.AgentPaperText | None:
    """The paper's stored-text state the run recorded; None for a run stored before it was kept (shown as nothing)."""
    got = _equipment(run).get("paper_text")
    if not isinstance(got, dict):
        return None
    try:
        return contract.AgentPaperText.model_validate(got)
    except ValueError:
        return None


@router.get(
    "/api/reviews/runs/{review_run_id}/agent/lines",
    response_model=contract.AgentLineList,
)
def agent_lines(
    review_run_id: str,
    request: Request,
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=PAGE_MAX),
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"cursor", "limit"})
    _run_or_404(review_run_id, scope)
    rows = (
        connect()
        .execute(
            "SELECT rowid AS rid, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, part, text_source,"
            " line_json FROM agent_review_line WHERE run_id = ? AND rowid > ? ORDER BY rowid LIMIT ?",
            (review_run_id, cursor, limit + 1),
        )
        .fetchall()
    )
    page = rows[:limit]
    lines = [_read_line(dict(r)) for r in page]
    more = len(rows) > limit
    return contract.AgentLineList(
        lines=lines, next=str(page[-1]["rid"]) if more and page else None
    )


def _read_line(row: dict) -> contract.AgentLine:
    """One stored line as the contract's line. A pair the contract refuses but that maps by its own one table
    (`contract.legal_word`: a row stored before the fix) is read through that map; stored rows are never rewritten. A row that
    still fails the contract's checks is shown as a "Not reviewed" stand-in saying so, so one bad row never takes the list down."""
    row = {k: v for k, v in row.items() if k != "rid"}
    row["reason"] = crs_ai_workbook.screen_text(row.pop("line_json", None)) or row.get(
        "reason"
    )  # the file's three lines
    word = contract.legal_word(str(row.get("verdict_class")), str(row.get("word")))
    if word is not None:
        row["word"] = word
    try:
        return contract.AgentLine.model_validate(row)  # the contract's own table checks
    except ValueError:
        return contract.AgentLine(
            item_id=str(row.get("item_id") or ""),
            verdict_class="Not reviewed",
            word="Not reviewed",
            page=row.get("page")
            if isinstance(row.get("page"), int) and row["page"] >= 1
            else None,
            clause=str(row.get("clause") or ""),
            rule_book=str(row.get("rule_book") or ""),
            reason="a stored line could not be read: its class, word or tier is not allowed by the contract",
            rule_tier=None,
        )


def _mode_of(conn, run_id: str) -> dict:
    """The mode of a run and the project papers a general review used: a run with a row in `agent_review_general` is a general
    review. Read only."""
    row = conn.execute(
        "SELECT project_json FROM agent_review_general WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return {"mode": "rule review", "project_papers_used": []}
    try:
        used = json.loads(row["project_json"] or "[]")
    except ValueError:
        used = []
    return {
        "mode": "general review",
        "project_papers_used": [
            contract.AgentProjectPaper(
                document_id=str(p["document_id"]), name=str(p["name"])
            )
            for p in used
        ],
    }


def _gate_steps(line: dict) -> list[contract.AgentGateStep]:
    """What code checked on one line, in order, from the stored line (words only)."""
    qc = line.get("quotes_checked") or {}
    steps = [
        (
            "paper quote",
            "verified" if qc.get("paper") else "not verified",
            str(qc.get("paper_why") or ""),
        ),
        (
            "rule quote",
            "verified" if qc.get("clause") else "not verified",
            str(qc.get("clause_why") or ""),
        ),
    ]
    if line.get("compare"):
        steps.append(
            (
                "numbers compared by code",
                str((line["compare"] or {}).get("decided") or "compared"),
                "",
            )
        )
    second = line.get("second_opinion")
    if second:
        steps.append(
            (
                "second opinion (another model)",
                {True: "agrees", False: "disagrees"}.get(
                    second.get("agree"), "no answer"
                ),
                "",
            )
        )
    if line.get("context_check"):
        steps.append(
            (
                "rule-book page context check",
                str(line["context_check"]),
                str(line.get("why") or ""),
            )
        )
    for key, step in (
        ("conditional_hold", "conditional rule"),
        ("table_note_hold", "table row or note"),
        ("unapproved_cap", "rule not approved"),
    ):
        if line.get(key):
            steps.append((step, "held: not proven", str(line.get("why") or "")))
    steps.append(
        (
            "decision",
            str(line.get("verdict_label") or line.get("verdict") or ""),
            str(line.get("not_proven_reason") or ""),
        )
    )
    return [contract.AgentGateStep(step=a, outcome=b, reason=c) for a, b, c in steps]


def _general_trace(item_id: str, line: dict, reason: str) -> contract.AgentTrace:
    """The trace of a general review line: the verified quote(s), what code checked, the second model's answer. No rule."""
    q_a = line.get("quote_a") or line.get("quote_paper") or {}
    q_b = line.get("quote_b") or line.get("quote_other") or {}
    steps = [
        (
            "quote verified by code",
            "verified"
            if line.get("quotes_verified_by_code")
            else "no quote on this line",
            "",
        )
    ]
    if line.get("figures"):
        steps.append(("figures", str(line["figures"]), ""))
    if line.get("second_model_reason") is not None:
        steps.append(
            (
                "second opinion (another model)",
                "keeps it",
                str(line["second_model_reason"]),
            )
        )
    steps.append(
        ("decision", str(line.get("word") or ""), str(line.get("subkind") or ""))
    )
    page = q_a.get("page")
    return contract.AgentTrace(
        item_id=item_id, page=page if isinstance(page, int) and page >= 1 else None,
        paper_quote=str(q_a.get("text") or ""), rule_quote="", rule_book=str(line.get("rule_book") or ""), clause="",
        model=", ".join(line.get("second_model") or []), reason=reason,
        gate=[contract.AgentGateStep(step=a, outcome=b, reason=c) for a, b, c in steps],
        other_quote=str(q_b.get("text")) if q_b.get("text") else None, part=line.get("part_word"),
    )  # fmt: skip


@router.get(
    "/api/reviews/runs/{review_run_id}/agent/lines/{item_id}/trace",
    response_model=contract.AgentTrace,
)
def agent_trace(
    review_run_id: str,
    item_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    _run_or_404(review_run_id, scope)
    row = (
        connect()
        .execute(
            "SELECT line_json, reason FROM agent_review_line WHERE run_id = ? AND item_id = ?",
            (review_run_id, item_id),
        )
        .fetchone()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no such line")
    line = json.loads(row["line_json"])
    if line.get("general"):
        return _general_trace(item_id, line, str(row["reason"] or ""))
    page = line.get("paper_page")
    return contract.AgentTrace(
        item_id=item_id,
        page=page if isinstance(page, int) and page >= 1 else None,
        paper_quote=str(line.get("paper_quote") or ""),
        rule_quote=str(line.get("clause_quote") or line.get("requirement") or ""),
        rule_book=str(line.get("standard") or ""),
        clause=str(line.get("clause") or ""),
        model=str(line.get("model") or ""),
        reason=str(row["reason"] or ""),
        gate=_gate_steps(line),
    )


@router.get(
    "/api/reviews/runs/{review_run_id}/agent/crs",
    response_class=FileResponse,
    responses={
        200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def agent_crs(
    review_run_id: str,
    request: Request,
    copy: Literal["internal", "contractor"] = Query(...),
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"copy"})
    _run_or_404(review_run_id, scope)
    path: Path = agent_review_jobs.run_dir(review_run_id) / f"crs-{copy}.xlsx"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="the CRS is not written yet")
    return FileResponse(path, media_type=XLSX, filename=f"agent-review-{copy}.xlsx")


def _coverage_for(rules: list) -> list[contract.AgentBookCoverage]:
    """One entry per rule book that was asked or left out; numbers from the coverage file, None without a row."""
    coverage = agent_review_coverage.load()
    seen: dict[tuple, None] = {}
    for r in rules:
        seen.setdefault((r["standard_document_id"], r["rule_book"]), None)
    return [
        contract.AgentBookCoverage(
            **agent_review_coverage.row_for(coverage.get(str(doc)), str(name or ""))
        )
        for doc, name in sorted(seen, key=lambda k: (str(k[1]), str(k[0])))
    ]


def _book_table(
    conn, run_id: str, scope: access.AccessScope
) -> contract.AgentBookTable:
    """Which held rule books were candidates and which were not; only books the caller may read are named (rule 5)."""
    got = agent_review_book_table.build(conn, run_id, scope.may_read)
    return contract.AgentBookTable(
        books=[contract.AgentBookRow(**b) for b in got["books"]],
        boundary=agent_review_book_table.BOUNDARY,
        hidden_books=got["hidden_books"],
        note=got["note"],
    )


@router.get(
    "/api/reviews/runs/{review_run_id}/rules-used",
    response_model=contract.AgentRulesUsed,
)
def rules_used(
    review_run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    run = _run_or_404(review_run_id, scope)
    conn = connect()
    rules = conn.execute(
        "SELECT * FROM agent_review_rule WHERE run_id = ? ORDER BY rule_book, clause, rule_key",
        (review_run_id,),
    ).fetchall()
    asked = [
        contract.AgentAskedRule(
            rule_book=r["rule_book"] or "", clause=r["clause"] or "", quote=r["quote"] or "",
            paper_kind=r["paper_kind"] or run["paper_kind"], field=r["field"], equipment=r["equipment"],
            tier=r["tier"] or "Not AI approved", read_from=r["read_from"],
        )
        for r in rules if r["asked"]
    ]  # fmt: skip
    left = [
        contract.AgentLeftOutRule(rule_book=r["rule_book"] or "", clause=r["clause"] or "", reason=r["left_out_reason"])
        for r in rules if not r["asked"]
    ]  # fmt: skip
    counts: dict[str, int] = {}
    for r in left:
        counts[r.reason] = counts.get(r.reason, 0) + 1
    missing = [
        contract.AgentMissingBook(name=r["name"], why=r["why"])
        for r in conn.execute(
            "SELECT name, why FROM agent_review_missing_book WHERE run_id = ? ORDER BY name",
            (review_run_id,),
        )
    ]
    cand = _equipment(run).get("candidates") or {}
    other = cand.get("books_not_selected")
    return contract.AgentRulesUsed(
        paper_kind=run["paper_kind"], equipment_type=run["equipment_type"], asked=asked, left_out=left,
        left_out_counts=counts, missing_books=missing, books=_coverage_for(rules),
        rule_set_changed_by=run["rule_set_changed_by"],
        equipment_state=_equipment(run).get("state"),
        equipment_notes=_equipment(run).get("notes") or [],
        book_table=_book_table(conn, review_run_id, scope),
        stop_reason=run["stop_reason"], paper_text=_paper_text(run),
        candidates_from=cand.get("source"), same_rule_repeats=cand.get("repeats") if cand else None,
        other_books=None if not other else contract.AgentOtherBooks(
            books=other["books"], ai_approved_rules=other["ai_approved_of_this_kind"], boundary=OTHER_BOOKS_BOUNDARY),
    )  # fmt: skip
