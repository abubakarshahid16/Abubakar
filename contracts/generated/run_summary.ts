// GENERATED from backend/app/api/run_summary.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

import type { AiStepNumbers, PageCoverage, RequirementSplit, ReviewRunSummary } from "../types";

export type RunSummaryTier = "A" | "B" | "C";
export type RunSummaryTierLabel = "Met" | "Not applicable" | "Another document" | "Comment" | "Needs you";
export type RunSummaryTierReason = "page not read" | "standard not in library" | "AI guess" | "rule not proven" | "safety field" | "condition unsettled" | "value conflict" | "unit unknown";
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
  /** order 139 part 2: the row's rank, 1 first (`crs_mapping.PRIORITY_WORDS`) */
  crs_priority?: number | null;
  /** order 139 part 2: the rank's word, as the internal copy prints it */
  crs_priority_label?: RunSummaryCrsPriorityLabel | null;
  /** order 139 part 2: the row's place in the sheet's order (0 first) among this run's finding rows - the file's order */
  crs_order?: number | null;
  /** order 139 part 2: the row's first line as the file prints it ("Contractor to provide Corrosion allowance."), on a row listing two or more clauses; null on a row of one clause, whose words are the finding's own */
  crs_action?: string | null;
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
  /** order 139 part 2: set true by a server that sends each row's `crs_group` (the sheet's grouping); absent or false otherwise */
  crs_grouping?: boolean;
}

/** `GET /api/reviews/runs/counts`: the tier counts of many runs in one call, each the same as that run's `/summary` `counts`. A run that is not there, or that the caller may not read, is absent, never zeros. */
export interface ReviewRunCountsBatch {
  boundary: string;
  counts: Record<string, RunSummaryTierCounts>;
}
