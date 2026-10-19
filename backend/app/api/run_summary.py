"""Order 95 piece 1: `GET /api/reviews/runs/{id}/summary` for the CRS-first screen.

The tiers (`review_tiers`), the headline counts and the "How this was reviewed"
data, read from what the run stored. No model is called, nothing is written,
no new counting: the same stored fields the run detail already returns.
`GET /api/reviews/runs/counts` (order 117 item 5) gives only the tier counts
of many runs, from the same helper as the summary's.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import (
    access,
    dashboard_pool,
    errors,
    review_jobs,
    review_tiers,
    review_trace,
    schemas,
)
from .. import ai_engineering_check as ai_engineering_check_mod
from .. import ai_numbers as ai_numbers_mod
from .. import clause_coverage as clause_coverage_mod
from .. import comparison as comparison_mod
from .. import crs_mapping as crs_mapping_mod
from .. import crs_wording as crs_wording_mod
from .. import page_ledger as page_ledger_mod
from .. import requirement_split as requirement_split_mod
from .. import submittal_review as submittal_review_mod
from ..api_utils import reject_unknown_params, require_document
from ..db import connect
from ..paging import ListPage

router = APIRouter()

#: Every count below is over these findings, and no others.
BOUNDARY = "findings of this run, on the submittal you may read"

#: the largest page `GET /api/reviews/runs` returns (order 117 item 5)
RUNS_MAX_PAGE_SIZE = 200

#: the most runs one `GET /api/reviews/runs/counts` asks for (order 117 item 5)
RUN_COUNTS_MAX_IDS = 200


def _ts(name: str) -> dict:
    """The TypeScript type a `dict` field is written as (order 119.1)."""
    return {"tsType": name}


class ReviewRunList(ListPage):
    runs: list[schemas.ReviewRunSummary]


class TierCounts(BaseModel):
    """Counts over every finding of the run; `removed` = rejected by an
    engineer (in no tier); `total` includes the removed ones."""

    met: int
    not_applicable: int
    another_document: int
    comment: int
    needs_you: int
    removed: int
    total: int


class TierRow(BaseModel):
    """One finding still in a tier, in the server's order (Comment, Needs you,
    Met; then page, no page last; then clause). The sheet keys rows by id and
    lays out its own order."""

    finding_id: str
    #: A met / not applicable, B comment, C needs you (tiers.ts `Tier`)
    tier: Literal["A", "B", "C"]
    label: Literal["Met", "Not applicable", "Another document", "Comment", "Needs you"]
    #: only a Tier C row carries a reason (tiers.ts `TierReason`)
    reason: (
        Literal[
            "page not read",
            "standard not in library",
            "AI guess",
            "rule not proven",
            "safety field",
            "condition unsettled",
            "value conflict",
            "unit unknown",
        ]
        | None
    ) = None
    compliance_status: str | None = None
    standard_clause: str | None = None
    contractor_page: int | None = None
    equipment_tag: str | None = None
    #: order 96: the cited standard not held that this finding rests on
    missing_standard_id: str | None = None
    #: order 139 part 2: the CRS row this finding lands on
    #: (`crs_mapping.crs_groups`); findings sharing it are ONE row on screen
    #: and in the file. Null: not a row of the CRS, or not computed (/counts)
    crs_group: str | None = None
    #: order 139 part 2: the rank of the CRS row this finding lands on, 1 first
    #: (`crs_mapping.PRIORITY_WORDS`), from the rows the file is built from;
    #: null for a finding on no row, and from `/counts`
    crs_priority: int | None = None
    #: order 139 part 2: the rank's word, as the internal copy prints it;
    #: null when there is no rank
    crs_priority_label: (
        Literal[
            "Out of limit", "Missing value", "Engineer to check", "Engineer's comment"
        ]
        | None
    ) = None
    #: order 139 part 2: the row's place in the sheet's order (0 first) among
    #: this run's finding rows - the file's order
    crs_order: int | None = None
    #: order 139 part 2: the row's first line as the file prints it ("Contractor
    #: to provide Corrosion allowance."), on a field row asking two or more
    #: things (clauses, or requirements of one clause); null on a row whose
    #: one sentence is the finding's own
    crs_action: str | None = None
    #: order 139 part 2: true on a finding that would be a comment but that
    #: the CRS file put on NO row - a standard's engineer-to-check finding
    #: counted in the file's Review notes (an unread page, a value only the
    #: page reader looked for, a requirement with no datasheet field), or a
    #: datasheet check about a value a breach or blank row already raises.
    #: The screen shows it as a note, never as a comment to decide. Null
    #: otherwise
    crs_note: bool | None = None


class StandardClauses(BaseModel):
    #: null: requirements of a standard the caller may not read, counted together
    standard_document_id: str | None = None
    counts: dict[str, int]


class HowReviewed(BaseModel):
    """The stored fields, as the run detail returns them; null when not stored."""

    requirement_split: dict | None = Field(
        None, json_schema_extra=_ts("RequirementSplit")
    )
    page_coverage: dict | None = Field(None, json_schema_extra=_ts("PageCoverage"))
    completeness: dict | None = Field(
        None, json_schema_extra=_ts('ReviewRunSummary["completeness"]')
    )
    reader: dict | None = Field(None, json_schema_extra=_ts("AiStepNumbers"))
    #: order 96: pages the AI reader timed out on; null when no reader record
    timed_out_pages: list[int] | None = None
    #: order 127: THE run's unread pages, one definition
    #: (`page_ledger.run_unread_pages`, the same the issue gate asks ticks
    #: for), before any engineer's tick; null when the run stored no page
    #: coverage or no page total (not known, never "none")
    unread_pages: list[int] | None = None
    #: order 96: stamped on the run's job; null when the run has no job row
    code_version: str | None = None
    config_version: str | None = None
    #: order 96: seconds per stage from the stored trace; null when none stored
    stage_seconds: dict[str, float] | None = None
    #: order 96: clause states per standard from the run's coverage ledger;
    #: null when the run recorded none
    clauses_by_standard: list[StandardClauses] | None = None


class RunSummary(BaseModel):
    """`GET /api/reviews/runs/{id}/summary`, the run as the CRS-first Sheet
    shows it. The tiers are `review_tiers`'s, whose rules are the data in
    `reference/review_tiers.json` that the screen's `crs/tiers.ts` reads too.
    Display only."""

    review_run_id: str
    status: str
    boundary: str
    counts: TierCounts
    rows: list[TierRow]
    how_reviewed: HowReviewed
    #: order 139 part 2: set true by a server that sends each row's
    #: `crs_group` (the sheet's grouping); absent or false otherwise
    crs_grouping: bool = False


class RunCountsBatch(BaseModel):
    """`GET /api/reviews/runs/counts`: the tier counts of many runs in one
    call, each the same as that run's `/summary` `counts`. A run that is not
    there, or that the caller may not read, is absent, never zeros."""

    boundary: str
    counts: dict[str, TierCounts]


def reader_timed_out_pages(split: dict | None) -> list[int] | None:
    """The pages the AI reader timed out on, from the reader record of the
    run's requirement split, sorted; None when there is no reader record
    (unknown, not none). tiers.ts `runFactsOf` reads the same field."""
    reader_record = (split or {}).get("reader")
    if not isinstance(reader_record, dict):
        return None
    return sorted(reader_record.get("timed_out") or [])


def _tiers(review_run_id: str, allowed) -> tuple[dict, dict, dict | None, list | None]:
    """The run's tiers (`counts` and `rows`), the one home of the counting
    for `/summary` and `/counts` (CLAUDE.md rule 8). Also returns the stored
    outcome, requirement split and timed-out pages it was built from."""
    outcome = (
        comparison_mod.run_outcome(review_run_id, allowed_document_ids=allowed) or {}
    )
    split = outcome.get("requirement_split") or requirement_split_mod.from_counts(
        outcome.get("unchecked_counts")
    )
    timed_out = reader_timed_out_pages(split)
    tiers = review_tiers.summarise(
        comparison_mod.list_findings(review_run_id, allowed_document_ids=allowed),
        _facts(review_run_id, outcome, timed_out),
    )
    return tiers, outcome, split, timed_out


@router.get(
    "/api/reviews/runs/counts",
    response_model=RunCountsBatch,
    responses=schemas.ERRORS_422,
)
@dashboard_pool.heavy_route
def review_run_counts(
    request: Request,
    ids: list[str] = Query(
        ...,
        min_length=1,
        max_length=RUN_COUNTS_MAX_IDS,
        description="review run ids, repeated: ?ids=a&ids=b",
    ),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Order 117 item 5: the review inbox's tier counts in one call instead
    of one `/summary` per row. Only the counts: no trace, coverage or AI
    numbers are read. A run the caller may not read, or that is not there, is
    left out (rule 5: intersection with what the caller may read). Read only.
    Declared before `/api/reviews/runs/{review_run_id}` so "counts" is not
    read as a run id."""
    reject_unknown_params(request, {"ids"})
    allowed = scope.allowed_document_ids
    counts: dict[str, dict] = {}
    for review_run_id in dict.fromkeys(ids):
        if (
            submittal_review_mod.get_review_run(
                review_run_id, allowed_document_ids=allowed
            )
            is None
        ):
            continue
        counts[review_run_id] = _tiers(review_run_id, allowed)[0]["counts"]
    return {"boundary": BOUNDARY, "counts": counts}


@router.get(
    "/api/reviews/runs/{review_run_id}/summary",
    response_model=RunSummary,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def review_run_summary(
    review_run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The run as the CRS-first screen shows it. A run the caller may not
    read is 404, indistinguishable from one that is not there. Read only."""
    reject_unknown_params(request, set())
    allowed = scope.allowed_document_ids
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=allowed
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no review run with that id"),
        )
    tiers, outcome, split, timed_out = _tiers(review_run_id, allowed)
    # Order 139 part 2: the CRS row each finding lands on, its place in the
    # sheet's order and its action line - computed HERE only, never in
    # `_tiers` (`/counts` asks for up to 200 runs and needs none of it).
    grouping = crs_fields(review_run_id, allowed)
    if grouping is not None:
        tiers = {
            **tiers,
            "rows": [
                {**row, **grouping.get(row["finding_id"], {})} for row in tiers["rows"]
            ],
        }
    steps = (
        ai_numbers_mod.for_run(
            outcome,
            ai_engineering_check_mod.ai_check_status(
                review_run_id, allowed_document_ids=allowed
            ),
            crs_wording_mod.summary_of(review_run_id),
        )
        or {}
    )
    versions = review_jobs.last_run_versions(review_run_id) or {}
    return {
        "review_run_id": review_run_id,
        "status": run.get("status") or "pending",
        "boundary": BOUNDARY,
        **tiers,
        "crs_grouping": grouping is not None,
        "how_reviewed": {
            "requirement_split": split,
            "page_coverage": outcome.get("page_coverage"),
            "completeness": outcome.get("completeness"),
            "reader": steps.get("reader"),
            "timed_out_pages": timed_out,
            # order 127: one definition, the same the issue gate asks ticks for
            "unread_pages": page_ledger_mod.run_unread_pages_of(outcome),
            "code_version": versions.get("code_version"),
            "config_version": versions.get("config_version"),
            "stage_seconds": _stage_seconds(review_trace.stored(review_run_id, scope)),
            "clauses_by_standard": _clauses_by_standard(
                clause_coverage_mod.for_run(review_run_id, allowed_document_ids=allowed)
            ),
        },
    }


@router.get(
    "/api/reviews/runs",
    response_model=ReviewRunList,
    responses=schemas.ERRORS_422,
)
@dashboard_pool.heavy_route
def list_review_runs(
    request: Request,
    document_id: str | None = Query(None, description="only this submittal's runs"),
    limit: int | None = Query(
        None, ge=1, le=RUNS_MAX_PAGE_SIZE, description="page size; omit for every run"
    ),
    offset: int = Query(0, ge=0),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every review run over a submittal the caller may read, newest first, or
    one page of them (order 117 item 5). `total` counts every run under the
    same filter, so a page always states its population.

    The counts are computed here rather than on the screen so that one
    definition of "how many findings, of what" exists. `findings_total` is the
    denominator for `by_status`; a screen showing a status count without it
    would be printing a percentage with no population (CLAUDE.md rule 4).
    The run rows themselves are one cheap query; the cost is the per-run
    summary, so only the asked-for page is summarised.
    """
    reject_unknown_params(request, {"document_id", "limit", "offset"})
    if document_id is not None:
        require_document(document_id, scope)
    runs = submittal_review_mod.list_review_runs(
        allowed_document_ids=scope.allowed_document_ids,
        submittal_document_id=document_id,
    )
    page = runs[offset:] if limit is None else runs[offset : offset + limit]
    from .. import main as main_mod  # main imports this module

    return {
        "runs": [main_mod._run_summary(run, scope) for run in page],
        "total": len(runs),
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/api/reviews/runs/{review_run_id}",
    response_model=schemas.ReviewRunSummary,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def review_run_detail(
    review_run_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Order 109: one run, in the same shape as one row of `GET /api/reviews/runs`
    (`main._run_summary`, one definition). A screen showing one run asks for
    that run, not for every run. A run the caller may not read is 404."""
    reject_unknown_params(request, set())
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no review run with that id"),
        )
    from .. import main as main_mod  # main imports this module

    return main_mod._run_summary(run, scope)


def crs_row_fields(rows: list[dict], findings: list[dict]) -> dict[str, dict]:
    """{finding id: {crs_group, crs_order, crs_action, crs_priority,
    crs_priority_label}} from the CRS rows
    `crs_mapping.build_crs_rows` built: the group key of the row the finding
    lands on, the row's place (0 first) among the sheet's FINDING rows in
    the sheet's own order, and its action line. The rows are the file's, so
    the screen groups and orders exactly as the file does (spec b).

    A finding on NO row that would otherwise be a comment is {crs_note: True}:
    a standard's NEEDS_ENGINEER_REVIEW finding (the file counts it in its
    Review notes: unread page, page reader only, no datasheet field), or a
    finding `crs_mapping.crs_bucket` gives a row kind that the list-level
    rule left off (a datasheet check about a value a breach or blank row
    already raises). Read from the rows the file actually built, never from
    a second copy of the rules that decide it, so it stays true whichever
    rule moves a finding off the rows. Any other finding on no row (met, not
    applicable, rejected) is absent."""
    out: dict[str, dict] = {}
    order = 0
    for row in rows:
        group = row.get("crs_group")
        if not group:
            continue  # a row with no finding (standards check, carried forward)
        ids = row.get("finding_ids") or [row.get("finding_id")]
        for finding_id in ids:
            if finding_id:
                fields = {
                    "crs_group": group,
                    "crs_order": order,
                    "crs_action": row.get("crs_action"),
                }
                # Spec f: the row's rank, from the SAME build, so the screen's
                # rank word is the Priority column's. A row with no rank (a
                # server that sent none) leaves the fields out: never a guess.
                rank = row.get("priority")
                if rank is not None:
                    fields["crs_priority"] = rank
                    fields["crs_priority_label"] = (
                        crs_mapping_mod.priority_word(rank) or None
                    )
                out.setdefault(finding_id, fields)
        order += 1
    for f in findings:
        if (
            f.get("id")
            and f["id"] not in out
            and f.get("approval_status") != "rejected"
            and (
                (
                    not f.get("origin")
                    and f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
                )
                or crs_mapping_mod.crs_bucket(f) is not None
            )
        ):
            out[f["id"]] = {"crs_note": True}
    return out


def crs_fields(review_run_id: str, allowed) -> dict[str, dict] | None:
    """The run's findings through the ONE grouping the CRS file uses, over
    the same findings and context `main._crs_content` reads. None when it
    could not be computed (logged with the run id only): the summary then
    says `crs_grouping: false` and the screen shows one row per finding and
    says so - never a grouping of its own."""
    try:
        findings = comparison_mod.list_findings(
            review_run_id, allowed_document_ids=allowed
        )
        comparison_mod.attach_crs_context(findings)
        return crs_row_fields(
            crs_mapping_mod.build_crs_rows(findings, [], ""), findings
        )
    except Exception:  # the tiers still answer; the screen says grouping is missing
        logging.getLogger(__name__).warning(
            "run summary: CRS grouping for run %s not computed",
            review_run_id,
            exc_info=True,
        )
        return None


def _facts(
    review_run_id: str, outcome: dict, timed_out: list[int] | None
) -> review_tiers.RunFacts:
    """The run facts the screen's `runFactsOf` gathers from the same stored
    run (order 135: both read the reader record for time-outs)."""
    coverage = outcome.get("page_coverage") or {}
    library = (
        connect()
        .execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1",
            (review_run_id,),
        )
        .fetchall()
    )
    return review_tiers.RunFacts(
        pages_not_read=frozenset(coverage.get("pages_not_read_into_fields") or []),
        reader_timed_out_pages=frozenset(timed_out or []),
        missing_standards=tuple(
            m["identifier"]
            for m in outcome.get("missing_references") or []
            if m.get("identifier") and m.get("status") in (None, "MISSING_LOCALLY")
        ),
        library_standard_ids=frozenset(r["standard_document_id"] for r in library),
    )


def _stage_seconds(trace: dict | None) -> dict[str, float] | None:
    """Seconds per step of the stored trace; None when no trace was stored."""
    if trace is None:
        return None
    return {
        s["step"]: s["timing"]["seconds"]
        for s in trace.get("steps") or []
        if isinstance(s.get("timing"), dict) and s["timing"].get("seconds") is not None
    }


def _clauses_by_standard(coverage: dict) -> list[dict] | None:
    """The coverage ledger's states counted per standard, in first-seen order."""
    if not coverage.get("recorded"):
        return None
    out: dict[str | None, dict[str, int]] = {}
    for row in coverage["rows"]:
        counts = out.setdefault(row["standard_document_id"], {})
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return [{"standard_document_id": k, "counts": v} for k, v in out.items()]
