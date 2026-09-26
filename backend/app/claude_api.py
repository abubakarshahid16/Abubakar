"""The four places a reviewer may ask Claude for a second pair of eyes.

ONE ROUTER, FOUR ROUTES, ONE SWITCH. Each route runs one of the model-assisted
modules over one review run and stores only what the module's own gate
accepted, marked as the model's, for an engineer to confirm:

  POST /api/reviews/runs/{id}/claude/select-standards   claude_selection
  POST /api/reviews/runs/{id}/claude/read-datasheet     claude_datasheet
  POST /api/reviews/runs/{id}/claude/recheck            claude_recheck
  GET  /api/reviews/runs/{id}/claude/crs-draft          claude_crs_comments

THE SWITCH IS THE READER'S. `reader_transport.transport()` returns None
unless BOTH `STANDARDS_READER_ENABLED` and
`STANDARDS_READER_ALLOW_PUBLIC_EGRESS` are on, and every route here answers
409 `model_disabled` in that case. There is no second flag to forget: the
setting that lets a sentence of a standard leave the machine is the setting
that lets a datasheet page or a finding leave it, because they are the same
kind of text and the same client's.

WHAT EACH ROUTE MAY AND MAY NOT DO - the rules live in the modules and are
repeated here so the router cannot be read as granting more:

  select-standards  proposes rows in `review_applicable_standards` with
                    `selection_method='model'`; never touches a row an
                    engineer or the deterministic selector wrote.
  read-datasheet    proposes rows in `submittal_facts` with
                    `extraction_method='model'`; never overwrites a field the
                    extractor already found on that page.
  recheck           appends a note to a finding's rationale; may raise a
                    COMPLIANT or NON_COMPLIANT finding to
                    NEEDS_ENGINEER_REVIEW and may do nothing else to a status.
  crs-draft         WRITES NOTHING. Returns the CRS preview with each row's
                    comment replaced by a gated draft under
                    `MODEL_DRAFT_PREFIX`, the machine text kept beside it.

Every response carries the gate's counts by reason and the transport's token
usage, so what the model was allowed to say and what it cost are on the same
screen as what it said.

WRITES NEED AN IDENTITY, the same rule every other write in `main.py` follows;
the draft route is a read and needs only read access to the run.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fastapi import APIRouter, Depends, HTTPException, Request

from . import access, errors
from . import claude_budget
from . import claude_crs_comments, claude_datasheet, claude_recheck, claude_selection
from . import classification as classification_mod
from . import crs_export as crs_export_mod
from . import datasheets, reader_api
from . import reader_transport as reader_transport_mod
from . import submittal_review as submittal_review_mod
from .api_utils import reject_unknown_params
from .db import connect

router = APIRouter()

#: Reported through `errors.MODEL_UNAVAILABLE`, the code the answer model
#: already uses when it cannot be reached; the message says which flags.
MODEL_DISABLED = errors.MODEL_UNAVAILABLE


def _run_or_404(review_run_id: str, scope: access.AccessScope) -> dict:
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids)
    if run is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    return run


def _require_identity_to_write(scope: access.AccessScope) -> None:
    if scope.unrestricted or scope.user_id:
        return
    raise HTTPException(status_code=401, detail=errors.safe_error(
        errors.UNAUTHENTICATED, "sign in to continue"))


def _model_call_or_409():
    """A `model_call` closed over the real transport, or 409 when the flags
    say nothing may leave. Returns (model_call, transport) so the route can
    report `transport.usage` afterwards."""
    transport = reader_transport_mod.transport()
    if transport is None:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            MODEL_DISABLED,
            "the standards reader is off: set STANDARDS_READER_ENABLED and "
            "STANDARDS_READER_ALLOW_PUBLIC_EGRESS in backend/.env"))
    return claude_budget.Budget(reader_api.model_call_via(transport)), transport


def _usage(transport) -> dict:
    usage = getattr(transport, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    return {key: getattr(usage, key) for key in
            ("calls", "input_tokens", "output_tokens") if hasattr(usage, key)}


def _capped(model_call, run) -> tuple[dict, bool]:
    """Run `run(model_call)`; when the cap is hit, return what it managed
    plus `True`. The modules return per-item results as they go only through
    their own aggregation, so a cap hit mid-run gives back an empty shape
    marked exhausted - the earlier calls were still made and still paid for,
    and `spend_total` says so."""
    try:
        return run(model_call), False
    except claude_budget.BudgetExhausted:
        return {}, True


def _settle(transport, result: dict, exhausted: bool, model_call) -> dict:
    """The lines every route ends with: usage, running total, cap status."""
    usage = _usage(transport)
    counts = dict(result.get("counts") or {})
    if exhausted:
        counts[claude_budget.BUDGET_EXHAUSTED] = 1
    return {
        **result,
        "counts": counts,
        "complete": not exhausted,
        "calls_this_run": getattr(model_call, "calls", None),
        "call_cap": getattr(model_call, "max_calls", None),
        "usage": usage,
        "spend_total": claude_budget.record(usage),
    }


def _by_finding(findings) -> dict:
    """`recheck_run` reports per-finding results; accept either a dict keyed
    by finding id or a list of results each carrying `finding_id`."""
    if isinstance(findings, dict):
        return findings
    out: dict = {}
    for item in findings or []:
        fid = item.get("finding_id") or (item.get("finding") or {}).get("id")
        if fid:
            out[fid] = item
    return out


def _datasheet_summary(submittal_id: str, scope: access.AccessScope) -> dict:
    stored = classification_mod.of_document(submittal_id) or {}
    facts = datasheets.list_facts(
        submittal_id, allowed_document_ids=scope.allowed_document_ids)
    text_rows = connect().execute(
        "SELECT text FROM chunks WHERE document_id = ? ORDER BY ordinal",
        (submittal_id,)).fetchall()
    text = "\n".join((row["text"] or "") for row in text_rows)
    return {
        "equipment_type": stored.get("equipment_type"),
        "discipline": stored.get("discipline"),
        "service": stored.get("service"),
        "field_names": [f.get("field_label") or f.get("field_name") for f in facts],
        "text": text,
    }


class ClaudeRouteResult(BaseModel):
    """What every Claude-lane route answers: the settlement fields `_settle`
    adds (counts, whether the run completed or hit its call cap, usage and
    the running spend) plus the route's own result fields, which differ per
    route and are carried as extras. Typed where the lane is uniform."""

    model_config = ConfigDict(extra="allow")

    counts: dict = {}
    complete: bool
    calls_this_run: int | None = None
    call_cap: int | None = None
    usage: dict = {}
    spend_total: dict = {}


@router.post("/api/reviews/runs/{review_run_id}/claude/select-standards", response_model=ClaudeRouteResult)
def claude_select_standards(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    run = _run_or_404(review_run_id, scope)
    model_call, transport = _model_call_or_409()
    candidates = claude_selection.candidates_from_corpus(
        allowed_document_ids=scope.allowed_document_ids)
    summary = _datasheet_summary(run["submittal_document_id"], scope)
    result, exhausted = _capped(
        model_call, lambda call: claude_selection.select_standards(summary, candidates, call))
    stored = claude_selection.store_selection(
        review_run_id, result.get("accepted", []), candidates,
        allowed_document_ids=scope.allowed_document_ids)
    return _settle(transport, {
        "review_run_id": review_run_id,
        "candidates": len(candidates),
        "accepted": result.get("accepted", []),
        "declined": result.get("declined", []),
        "rejected": result.get("rejected", []),
        "counts": result.get("counts", {}),
        "error": result.get("error"),
        "stored": {key: len(value) for key, value in stored.items()},
    }, exhausted, model_call)


@router.post("/api/reviews/runs/{review_run_id}/claude/read-datasheet", response_model=ClaudeRouteResult)
def claude_read_datasheet(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    run = _run_or_404(review_run_id, scope)
    model_call, transport = _model_call_or_409()
    submittal_id = run["submittal_document_id"]
    result, exhausted = _capped(model_call, lambda call: claude_datasheet.read_datasheet(
        submittal_id, allowed_document_ids=scope.allowed_document_ids, model_call=call))
    stored = claude_datasheet.store_facts(
        review_run_id, submittal_id, result.get("accepted", []),
        allowed_document_ids=scope.allowed_document_ids)
    return _settle(transport, {
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_id,
        "pages": result.get("pages", []),
        "accepted": result.get("accepted", []),
        "rejected": result.get("rejected", []),
        "counts": result.get("rejection_counts") or result.get("counts") or {},
        "errors": result.get("errors", []),
        "stored": {key: (len(value) if isinstance(value, list) else value)
                   for key, value in stored.items()},
    }, exhausted, model_call)


@router.post("/api/reviews/runs/{review_run_id}/claude/recheck", response_model=ClaudeRouteResult)
def claude_recheck_findings(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    _run_or_404(review_run_id, scope)
    model_call, transport = _model_call_or_409()
    result, exhausted = _capped(model_call, lambda call: claude_recheck.recheck_run(
        review_run_id, call, allowed_document_ids=scope.allowed_document_ids))
    stored = 0
    for finding_id, per in _by_finding(result.get("findings")).items():
        if claude_recheck.store_recheck(finding_id, per) is not None:
            stored += 1
    return _settle(transport, {
        "review_run_id": review_run_id,
        "agreed": result.get("agreed", 0),
        "disagreed": result.get("disagreed", 0),
        "raised": result.get("raised", 0),
        "rejected": result.get("rejected", {}),
        "counts": result.get("rejected", {}),
        "states": result.get("states", {}),
        "stored": stored,
        "total": result.get("total", 0),
        "findings": result.get("findings"),
    }, exhausted, model_call)


@router.get("/api/reviews/runs/{review_run_id}/claude/crs-draft", response_model=ClaudeRouteResult)
def claude_crs_draft(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The CRS preview with model-drafted comments laid over it. Writes
    nothing; the download route still exports the machine text until an
    engineer copies a draft in."""
    reject_unknown_params(request, set())
    from .main import _crs_content  # the same composition the preview uses
    rows, meta, submittal_name, _stamp = _crs_content(review_run_id, scope)
    model_call, transport = _model_call_or_409()
    drafted, exhausted = _capped(model_call, lambda call: claude_crs_comments.draft_run(
        review_run_id, call, allowed_document_ids=scope.allowed_document_ids,
        submittal_name=submittal_name))
    view = crs_export_mod.build_crs_view(rows, meta)
    return _settle(transport, {
        **claude_crs_comments.apply_drafts(view, drafted.get("drafts", {})),
        "drafted": drafted.get("drafted", 0),
        "rejected": drafted.get("rejected", 0),
        "counts": drafted.get("counts", {}),
    }, exhausted, model_call)


class AiCheckResult(BaseModel):
    """What the AI engineering check did: counts and reasons, never text."""

    review_run_id: str
    ran: bool
    reason: str | None = None
    proposed: int = 0
    kept: int = 0
    rejected: dict = {}
    cost_usd: float | None = None


@router.post("/api/reviews/runs/{review_run_id}/ai-check", response_model=AiCheckResult)
def review_ai_check(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Owner order 2d: run the AI engineering check for a run again. Drafts
    only - pending, unconfirmed, never counted in the review code. 409 when
    the flag or the Claude lane is off; nothing is sent then."""
    from . import ai_engineering_check, claude_spend
    from . import reasoning_provider as rp
    from .main import _missing_references
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    run = _run_or_404(review_run_id, scope)
    ok, why = ai_engineering_check.available()
    if not ok:
        raise HTTPException(status_code=409, detail=errors.safe_error(MODEL_DISABLED, why))
    try:
        result = ai_engineering_check.run_check(
            review_run_id, allowed_document_ids=scope.allowed_document_ids,
            cited=_missing_references(run["submittal_document_id"], scope.allowed_document_ids))
    except (claude_spend.BudgetExceeded, rp.ProviderRefused) as exc:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            MODEL_DISABLED, f"the AI engineering check did not run: {type(exc).__name__}")) from None
    return {"review_run_id": review_run_id, **result}
