// GENERATED from backend/app/api/run_summary.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

import type { AiStepNumbers, PageCoverage, RequirementSplit, ReviewRunSummary } from "../types";

export type RunSummaryTier = "A" | "B" | "C";
export type RunSummaryTierLabel = "Met" | "Not applicable" | "Another document" | "Comment" | "Needs you";
export type RunSummaryTierReason = "page not read" | "standard not in library" | "AI guess" | "rule not proven" | "safety field" | "condition unsettled" | "value conflict" | "unit unknown" | "no standard linked" | "standard outside this review";
export type RunSummaryCrsPriorityLabel = "Out of limit" | "Missing value" | "Engineer to check" | "Engineer's comment";

/** Counts over every finding of the run; `removed` = rejected by an engineer (in no tier); `total` includes the removed ones. */
export interface RunSummaryTierCounts {
  met: number;
  not_applicable: number;
  another_document: number;
  comment: number;
  needs_you: number;
  removed: number;
  total: number;
}

/** The sheet's counts (order 152.2, `review_counts.sheet_counts`), each in the unit its field names: `comments`, `needs_you`, `met`, `not_applicable` and `another_document` are ROWS of the CRS sheet; `findings_in_comments` is the findings those comment rows hold; `review_notes` the findings the file puts in its Review notes; `removed` the findings an engineer removed; `findings` every finding of the run. The inbox's `/counts` are findings (TierCounts), not rows. */
export interface RunSummarySheetCounts {
  comments: number;
  needs_you: number;
  met: number;
  not_applicable: number;
  another_document: number;
  findings_in_comments: number;
  review_notes: number;
  removed: number;
  findings: number;
}

/** One finding still in a tier, in the server's order (Comment, Needs you, Met; then page, no page last; then clause). The sheet keys rows by id and lays out its own order. */
export interface RunSummaryTierRow {
  finding_id: string;
  /** A met / not applicable, B comment, C needs you (tiers.ts `Tier`) */
  tier: RunSummaryTier;
  label: RunSummaryTierLabel;
  /** only a Tier C row carries a reason (tiers.ts `TierReason`) */
  reason?: RunSummaryTierReason | null;
  compliance_status?: string | null;
  standard_clause?: string | null;
  contractor_page?: number | null;
  equipment_tag?: string | null;
  /** order 96: the cited standard not held that this finding rests on */
  missing_standard_id?: string | null;
  /** order 139 part 2: the CRS row this finding lands on (`crs_mapping.crs_groups`); findings sharing it are ONE row on screen and in the file. Null: not a row of the CRS, or not computed (/counts) */
  crs_group?: string | null;
  /** order 139 part 2: the rank of the CRS row this finding lands on, 1 first (`crs_mapping.PRIORITY_WORDS`), from the rows the file is built from; null for a finding on no row, and from `/counts` */
  crs_priority?: number | null;
  /** order 139 part 2: the rank's word, as the internal copy prints it; null when there is no rank */
  crs_priority_label?: RunSummaryCrsPriorityLabel | null;
  /** order 139 part 2: the row's place in the sheet's order (0 first) among this run's finding rows - the file's order */
  crs_order?: number | null;
  /** order 139 part 2: the row's first line as the file prints it ("Contractor to provide Corrosion allowance."), on a field row asking two or more things (clauses, or requirements of one clause); null on a row whose one sentence is the finding's own */
  crs_action?: string | null;
  /** order 139 part 2: true on a finding that would be a comment but that the CRS file put on NO row - a standard's engineer-to-check finding counted in the file's Review notes (an unread page, a value only the page reader looked for, a requirement with no datasheet field), or a datasheet check about a value a breach or blank row already raises. The screen shows it as a note, never as a comment to decide. Null otherwise */
  crs_note?: boolean | null;
}

export interface RunSummaryStandardClauses {
  /** null: requirements of a standard the caller may not read, counted together */
  standard_document_id?: string | null;
  counts: Record<string, number>;
}

/** The stored fields, as the run detail returns them; null when not stored. */
export interface RunSummaryHowReviewed {
  requirement_split?: RequirementSplit | null;
  page_coverage?: PageCoverage | null;
  completeness?: ReviewRunSummary["completeness"] | null;
  reader?: AiStepNumbers | null;
  /** order 96: pages the AI reader timed out on; null when no reader record */
  timed_out_pages?: number[] | null;
  /** order 127: THE run's unread pages, one definition (`page_ledger.run_unread_pages`, the same the issue gate asks ticks for), before any engineer's tick; null when the run stored no page coverage or no page total (not known, never "none") */
  unread_pages?: number[] | null;
  /** order 96: stamped on the run's job; null when the run has no job row */
  code_version?: string | null;
  config_version?: string | null;
  /** order 273.4: the settings (the values behind `config_version`), the model and the reader the run ran with, read from the running process; null for a run that stored none (never invented) */
  run_settings?: Record<string, unknown> | null;
  /** order 96: seconds per stage from the stored trace; null when none stored */
  stage_seconds?: Record<string, number> | null;
  /** order 96: clause states per standard from the run's coverage ledger; null when the run recorded none */
  clauses_by_standard?: RunSummaryStandardClauses[] | null;
}

/** `GET /api/reviews/runs/{id}/summary`, the run as the CRS-first Sheet shows it. The tiers are `review_tiers`'s, whose rules are the data in `reference/review_tiers.json` that the screen's `crs/tiers.ts` reads too. Display only. */
export interface ReviewRunTierSummary {
  review_run_id: string;
  status: string;
  boundary: string;
  counts: RunSummaryTierCounts;
  rows: RunSummaryTierRow[];
  how_reviewed: RunSummaryHowReviewed;
  /** order 161 C: why each finding held for the engineer was held (`held_reasons.counts`): {reason: findings}, most common first; every held finding has one, so the counts add up to the held findings */
  held_reasons?: Record<string, number>;
  /** order 139 part 2: set true by a server that sends each row's `crs_group` (the sheet's grouping); absent or false otherwise */
  crs_grouping?: boolean;
  /** order 152.2: the sheet's counts in rows, from the same grouping; null when the grouping could not be computed (never zeros) */
  sheet?: RunSummarySheetCounts | null;
}

/** `GET /api/reviews/runs/counts`: the tier counts of many runs in one call, each the same as that run's `/summary` `counts`. A run that is not there, or that the caller may not read, is absent, never zeros. */
export interface ReviewRunCountsBatch {
  boundary: string;
  counts: Record<string, RunSummaryTierCounts>;
}
