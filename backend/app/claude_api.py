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

TWO LIMITS ON EVERY CALL, BOTH INSIDE `_model_call_or_409(step)` so no route
can reach the transport without them:

  1. The USD caps (owner rule 2026-09-25: USD 5 per step, USD 20 in total).
     The transport is wrapped in `claude_spend.metered(transport, step)`:
     each call's worst case is checked BEFORE it leaves, and each call is
     written to the one `claude_spend` ledger AFTER it returns, so the total
     cap sees these routes' spend. A refusal is a 409 `model_disabled`; the
     refused call is never sent. Each route is its own step (`STEPS`).
  2. The per-run call cap in `claude_budget` (default 200 calls), which
     stops a run early and reports it as incomplete.

WRITES NEED AN IDENTITY, the same rule every other write in `main.py` follows;
the draft route is a read and needs only read access to the run.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fastapi import APIRouter, Depends, HTTPException, Request

from . import access, errors
from . import claude_budget, claude_spend
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

#: The `claude_spend` step each route is charged to - one per route, so the
#: USD 5 per-step cap applies to each route's own spend.
STEP_SELECT_STANDARDS = "claude-select-standards"
STEP_READ_DATASHEET = "claude-read-datasheet"
STEP_RECHECK = "claude-recheck"
STEP_CRS_DRAFT = "claude-crs-draft"
STEPS = (STEP_SELECT_STANDARDS, STEP_READ_DATASHEET, STEP_RECHECK, STEP_CRS_DRAFT)


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


def _model_call_or_409(step: str):
    """A `model_call` closed over the real transport, or 409 when the flags
    say nothing may leave. Returns (model_call, transport) so the route can
    report `transport.usage` afterwards.

    THE ONLY WAY A ROUTE HERE REACHES THE TRANSPORT, and it carries both
    limits: the transport is wrapped in `claude_spend.metered(..., step)` (USD
    caps checked before each call, ledger written after it) and the result in
    `claude_budget.Budget` (the per-run call cap). `step` is required so every
    call is charged to a named step."""
    if step not in STEPS:
        raise ValueError(f"unknown Claude route step {step!r}")
    transport = reader_transport_mod.transport()
    if transport is None:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            MODEL_DISABLED,
            "the standards reader is off: set STANDARDS_READER_ENABLED and "
            "STANDARDS_READER_ALLOW_PUBLIC_EGRESS in backend/.env"))
    budget = claude_budget.Budget(
        reader_api.model_call_via(claude_spend.metered(transport, step)))
    budget.step = step
    return budget, transport


def _usage(transport) -> dict:
    usage = getattr(transport, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    return {key: getattr(usage, key) for key in
            ("calls", "input_tokens", "output_tokens") if hasattr(usage, key)}


def _capped(model_call, run, transport=None) -> tuple[dict, bool]:
    """Run `run(model_call)`; when the call cap is hit, return what it managed
    plus `True`. The modules return per-item results as they go only through
    their own aggregation, so a cap hit mid-run gives back an empty shape
    marked exhausted - the earlier calls were still made and still paid for,
    and `spend_total` says so.

    When a USD cap refuses the next call (`claude_spend.BudgetExceeded`), the
    route answers 409 `model_disabled`: that call was never sent. Calls made
    before it are already in the `claude_spend` ledger (written per call) and
    their tokens are added to the running total here before the 409. The
    message names the step and dollar figures only - never document text."""
    try:
        return run(model_call), False
    except claude_budget.BudgetExhausted:
        return {}, True
    except claude_spend.BudgetExceeded as exc:
        if transport is not None:
            claude_budget.record(_usage(transport))
        raise HTTPException(status_code=409, detail=errors.safe_error(
            MODEL_DISABLED,
            f"the Claude USD budget refused the next call, which was not sent "
            f"({_calls_before_refusal(model_call)} calls made before it): {exc}")) from None


def _calls_before_refusal(model_call) -> int:
    """`Budget` counts a call before handing it on, so the call the USD check
    refused is in `calls`; it was never sent."""
    return max(0, int(getattr(model_call, "calls", 0) or 0) - 1)


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
        "usd_spent": _usd_spent(getattr(model_call, "step", None)),
    }


def _usd_spent(step: str | None) -> dict:
    """What the `claude_spend` ledger - the one the USD caps read - says has
    been spent on this route's step and in total, beside the caps."""
    caps = claude_spend.Caps.from_settings()
    return {"step": step,
            "step_usd": claude_spend.spent(step) if step else None,
            "total_usd": claude_spend.spent(),
            "cap_per_step_usd": caps.per_step, "cap_total_usd": caps.total}


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
    usd_spent: dict = {}


@router.post("/api/reviews/runs/{review_run_id}/claude/select-standards", response_model=ClaudeRouteResult)
def claude_select_standards(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    run = _run_or_404(review_run_id, scope)
    model_call, transport = _model_call_or_409(STEP_SELECT_STANDARDS)
    candidates = claude_selection.candidates_from_corpus(
        allowed_document_ids=scope.allowed_document_ids)
    summary = _datasheet_summary(run["submittal_document_id"], scope)
    result, exhausted = _capped(
        model_call, lambda call: claude_selection.select_standards(summary, candidates, call),
        transport)
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
    model_call, transport = _model_call_or_409(STEP_READ_DATASHEET)
    submittal_id = run["submittal_document_id"]
    result, exhausted = _capped(model_call, lambda call: claude_datasheet.read_datasheet(
        submittal_id, allowed_document_ids=scope.allowed_document_ids, model_call=call),
        transport)
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
    model_call, transport = _model_call_or_409(STEP_RECHECK)
    result, exhausted = _capped(model_call, lambda call: claude_recheck.recheck_run(
        review_run_id, call, allowed_document_ids=scope.allowed_document_ids), transport)
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
    model_call, transport = _model_call_or_409(STEP_CRS_DRAFT)
    drafted, exhausted = _capped(model_call, lambda call: claude_crs_comments.draft_run(
        review_run_id, call, allowed_document_ids=scope.allowed_document_ids,
        submittal_name=submittal_name), transport)
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


class WebCheckResult(BaseModel):
    """What the public web standards check did: counts and reasons, never
    text - the same shape as `AiCheckResult`, kind D beside kind C."""

    review_run_id: str
    ran: bool
    reason: str | None = None
    checked: int = 0
    kept: int = 0


@router.post("/api/reviews/runs/{review_run_id}/web-check", response_model=WebCheckResult)
def review_web_check(
    review_run_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Owner order 2d-2: check the standards this run cites but the library
    does not hold, against a PUBLIC web copy - a company standard is never
    attempted. Drafts only - pending, unconfirmed, never counted in the
    review code. 409 when the flag or the market lane is off; nothing is
    sent then."""
    from . import web_standards
    from .main import _missing_references
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    run = _run_or_404(review_run_id, scope)
    ok, why = web_standards.available()
    if not ok:
        raise HTTPException(status_code=409, detail=errors.safe_error(MODEL_DISABLED, why))
    from . import market_transport
    result = web_standards.run_check(
        review_run_id, allowed_document_ids=scope.allowed_document_ids,
        missing_identifiers=_missing_references(
            run["submittal_document_id"], scope.allowed_document_ids),
        fetch_search=market_transport.transport(),
        fetch_text=lambda url, timeout: market_transport.fetch_text(url, timeout=timeout))
    return {"review_run_id": review_run_id, **result}
