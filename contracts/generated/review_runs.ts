// GENERATED from backend/app/schemas.py and backend/app/api/run_summary.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

import type { AiCheckStatus, PageCoverage, RequirementSplit, RequirementsNotApplied, ReviewRunCompleteness, RunApplicability, RunCheckStatus, RunClauseCoverageSummary, StandardsChange, StatusCounts, TableValuesNotCompared } from "../types";

export interface ReviewJobState {
  id: string;
  state: string;
  progress_done?: number | null;
  progress_total?: number | null;
  progress_label?: string | null;
  cancel_requested: boolean;
}

/** #845: one AI step of a run, as the run stored it. Every count in `lines` is printed with what it is out of (CLAUDE.md rule 4). */
export interface AiStepNumbers {
  step: string;
  /** off / ran / incomplete / not run */
  state: string;
  /** "local model" / "cloud model", or null when the record names neither. */
  where?: string | null;
  model?: string | null;
  /** #842: why the local model stood in for the cloud model, or null. */
  local_instead?: string | null;
  lines: string[];
  /** #791: the numbers the lines print, for the pipeline panel's lights. A count the record does not hold is absent, never 0. */
  counts: Record<string, number>;
}

/** #845: the four AI steps of a run. A step with no record is null. */
export interface AiNumbers {
  reader?: AiStepNumbers | null;
  matcher?: AiStepNumbers | null;
  engineering_check?: AiStepNumbers | null;
  wording?: AiStepNumbers | null;
  /** #645: proposed checks for the clause sentences the run could not decide. */
  clause_checks?: AiStepNumbers | null;
}

/** A review run as the runs list shows it. EVERY COUNT CARRIES ITS DENOMINATOR (CLAUDE.md rule 4). `by_status` is a map of status to count and `findings_total` is what they are out of, so no screen has to invent the total by summing and no reader sees a bare number. */
export interface ReviewRunSummary {
  review_run_id: string;
  submittal_document_id: string;
  submittal_filename?: string | null;
  /** Every distinct equipment tag the run's findings name, in order; empty (shown as nothing, never a guess) when the datasheet states none. */
  equipment_tags: string[];
  status: string;
  created_at?: string | null;
  completed_at?: string | null;
  standards_in_scope: number;
  findings_total: number;
  by_status: StatusCounts;
  recommended_code?: string | null;
  /** The recommendation's own words. Never re-worded by a screen. */
  recommended_reason?: string | null;
  /** 2g: the technical sentence behind `recommended_reason` (the nominal field estimate, identifiers), shown under "Details". Null when none. */
  recommended_details?: string | null;
  /** The four review-code labels the client configured (`reference/review_codes.json`), in policy order: approved, approved with comments, revise and resubmit, manual review. Empty on a caller that predates it; the screen then falls back to the default labels. */
  review_codes: string[];
  /** 2e: {previous_run_id, added: [names], removed: [names]} against the previous completed run of the same submittal; null when there is none. */
  standards_change?: StandardsChange | null;
  /** Why a failed run failed, verbatim. None on a run that did not fail. */
  failure_reason?: string | null;
  /** THE ENGINEER'S DECISION, BESIDE THE MACHINE'S AND NEVER INSTEAD OF IT. Section 15: the AI recommends and the engineer decides; both are stored so a reader can see what was recommended and what was signed. */
  engineer_final_code?: string | null;
  override_reason?: string | null;
  /** The user id, because that is what the foreign key holds. */
  decided_by?: string | null;
  /** And that id's name, from the run's own join (null when the user row is gone): a screen shows it, keeping the id for the tooltip. */
  decided_by_name?: string | null;
  decided_at?: string | null;
  completeness?: ReviewRunCompleteness | null;
  page_coverage?: PageCoverage | null;
  unread_pages?: number[] | null;
  /** #598: standards-table values this run did NOT compare because the submittal has no field that answers them, one grouped line per standard with the tables behind it. Empty for a run that predates it. */
  table_values_not_compared: TableValuesNotCompared[];
  /** #453: requirements about a different kind of equipment than this submittal, one grouped line per subject ("N requirements not applied: they are about X, this submittal is Y") with the standards and clauses behind it. Empty for a run that predates it. */
  requirements_not_applied: RequirementsNotApplied[];
  /** #678: every requirement in the run's scope in ONE of three groups (checked / applies but not checked / does not apply), each repeat counted once, with the reasons behind the last two. For a run that predates it only the counts are known and every reason is "no reason recorded". */
  requirement_split?: RequirementSplit | null;
  clause_coverage?: RunClauseCoverageSummary | null;
  /** #453: how the requirements that stayed were decided (general, matching, kept because the equipment is unknown). Null for a run that predates it. */
  applicability?: RunApplicability | null;
  /** P3: the job running this review: its state, named progress (step N of 3) and whether cancellation was requested. Null for a run made before reviews were queued. */
  job?: ReviewJobState | null;
  /** 2026-09-27: the AI engineering check's own outcome for this run - null when it never ran (off, or the Claude lane is off). NEVER silent when it did: `complete` is false and `plain` states the boundary (how many of how many, cut off by what) whenever a reply was truncated, only partially recovered after the one capped retry, or refused outright. */
  ai_check_status?: AiCheckStatus | null;
  /** #633: the web standards check's own outcome (same shape): when it was asked for and could not run, `complete` is false and `plain` says why. */
  web_check_status?: RunCheckStatus | null;
  /** #633: findings written before a failed run stopped. They are partial and the run recommends no code. */
  partial_findings: number;
  /** Order 95 piece 3: when the newest contractor copy of this run's CRS was issued (the inbox's "Signed"). Null when none was. */
  crs_issued_at?: string | null;
  /** #845: the run's AI numbers (reader, matcher, AI check, wording), each with its denominator and where it ran. Null when the run holds no record of any AI step; a step with no record is null inside it. */
  ai_numbers?: AiNumbers | null;
}

export interface ReviewRunList {
  total: number;
  limit?: number | null;
  offset: number;
  runs: ReviewRunSummary[];
}
