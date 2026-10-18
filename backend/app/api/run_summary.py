"""Order 95 piece 1: `GET /api/reviews/runs/{id}/summary` for the CRS-first screen.

The tiers (`review_tiers`), the headline counts and the "How this was reviewed"
data, read from what the run stored. No model is called, nothing is written,
no new counting: the same stored fields the run detail already returns.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import access, errors, review_jobs, review_tiers, review_trace, schemas
from .. import ai_engineering_check as ai_engineering_check_mod
from .. import ai_numbers as ai_numbers_mod
from .. import clause_coverage as clause_coverage_mod
from .. import comparison as comparison_mod
from .. import crs_wording as crs_wording_mod
from .. import requirement_split as requirement_split_mod
from .. import submittal_review as submittal_review_mod
from ..api_utils import reject_unknown_params
from ..applicability import normalise_identifier

router = APIRouter()

#: Every count below is over these findings, and no others.
BOUNDARY = "findings of this run, on the submittal you may read"


class TierCounts(BaseModel):
    comment: int
    needs_you: int
    met_or_not_applicable: int
    removed: int
    total: int


class TierRow(BaseModel):
    finding_id: str
    tier: Literal["comment", "needs_you", "met_or_not_applicable"]
    reason: str
    compliance_status: str | None = None
    standard_clause: str | None = None
    contractor_page: int | None = None
    equipment_tag: str | None = None
    #: order 96: the cited standard not held that this finding rests on
    missing_standard_id: str | None = None


class StandardClauses(BaseModel):
    #: null: requirements of a standard the caller may not read, counted together
    standard_document_id: str | None = None
    counts: dict[str, int]


class HowReviewed(BaseModel):
    """The stored fields, as the run detail returns them; null when not stored."""
    requirement_split: dict | None = None
    page_coverage: dict | None = None
    completeness: dict | None = None
    reader: dict | None = None
    #: order 96: pages the AI reader timed out on; null when no reader record
    timed_out_pages: list[int] | None = None
    #: order 96: stamped on the run's job; null when the run has no job row
    code_version: str | None = None
    config_version: str | None = None
    #: order 96: seconds per stage from the stored trace; null when none stored
    stage_seconds: dict[str, float] | None = None
    #: order 96: clause states per standard from the run's coverage ledger;
    #: null when the run recorded none
    clauses_by_standard: list[StandardClauses] | None = None


class RunSummary(BaseModel):
    review_run_id: str
    status: str
    boundary: str
    counts: TierCounts
    rows: list[TierRow]
    how_reviewed: HowReviewed


@router.get("/api/reviews/runs/{review_run_id}/summary", response_model=RunSummary,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def review_run_summary(
    review_run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The run as the CRS-first screen shows it. A run the caller may not
    read is 404, indistinguishable from one that is not there. Read only."""
    reject_unknown_params(request, set())
    allowed = scope.allowed_document_ids
    run = submittal_review_mod.get_review_run(review_run_id, allowed_document_ids=allowed)
    if run is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    outcome = comparison_mod.run_outcome(review_run_id, allowed_document_ids=allowed) or {}
    steps = ai_numbers_mod.for_run(
        outcome,
        ai_engineering_check_mod.ai_check_status(review_run_id, allowed_document_ids=allowed),
        crs_wording_mod.summary_of(review_run_id)) or {}
    missing = {normalise_identifier(m["identifier"]): m["identifier"]
               for m in outcome.get("missing_references") or [] if m.get("identifier")}
    tiers = review_tiers.summarise(
        comparison_mod.list_findings(review_run_id, allowed_document_ids=allowed), missing)
    split = (outcome.get("requirement_split")
             or requirement_split_mod.from_counts(outcome.get("unchecked_counts")))
    reader_record = (split or {}).get("reader")
    versions = review_jobs.last_run_versions(review_run_id) or {}
    return {
        "review_run_id": review_run_id,
        "status": run.get("status") or "pending",
        "boundary": BOUNDARY,
        **tiers,
        "how_reviewed": {
            "requirement_split": split,
            "page_coverage": outcome.get("page_coverage"),
            "completeness": outcome.get("completeness"),
            "reader": steps.get("reader"),
            "timed_out_pages": (sorted(reader_record.get("timed_out") or [])
                                if isinstance(reader_record, dict) else None),
            "code_version": versions.get("code_version"),
            "config_version": versions.get("config_version"),
            "stage_seconds": _stage_seconds(review_trace.stored(review_run_id, scope)),
            "clauses_by_standard": _clauses_by_standard(
                clause_coverage_mod.for_run(review_run_id, allowed_document_ids=allowed)),
        },
    }


def _stage_seconds(trace: dict | None) -> dict[str, float] | None:
    """Seconds per step of the stored trace; None when no trace was stored."""
    if trace is None:
        return None
    return {s["step"]: s["timing"]["seconds"] for s in trace.get("steps") or []
            if isinstance(s.get("timing"), dict) and s["timing"].get("seconds") is not None}


def _clauses_by_standard(coverage: dict) -> list[dict] | None:
    """The coverage ledger's states counted per standard, in first-seen order."""
    if not coverage.get("recorded"):
        return None
    out: dict[str | None, dict[str, int]] = {}
    for row in coverage["rows"]:
        counts = out.setdefault(row["standard_document_id"], {})
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return [{"standard_document_id": k, "counts": v} for k, v in out.items()]
