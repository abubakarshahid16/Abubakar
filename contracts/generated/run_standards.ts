// GENERATED from backend/app/schemas.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

/** One standard on a run's list, with the reason it is there. THE REASON IS VERBATIM. `applicability.select` writes a sentence saying what put the standard on the list - a citation in the submittal, or dense retrieval that "is NOT a citation and not evidence of applicability on its own" - and the screen shows that sentence rather than a word of its own. */
export interface ReviewRunStandard {
  standard_document_id: string;
  filename?: string | null;
  selection_method?: string | null;
  selection_reason?: string | null;
  confidence?: number | null;
  included?: boolean;
  exclusion_reason?: string | null;
  /** B5: the evidence behind the selection - where the submittal cites the standard, or the scope clause that decided it. None when there is none. */
  evidence_page?: number | null;
  evidence_quote?: string | null;
  /** applicability_v2's decision on a stored scope record, or None. */
  scope_decision?: string | null;
}

export interface ReviewRunMissingReference {
  identifier: string;
  status: string;
}

/** #620: the run's own words for the held Company standards it skipped. */
export interface ReviewRunHeldForConfirmation {
  count: number;
  standard_document_ids?: string[];
  confirm_from?: string | null;
  sentence: string;
}

export interface ReviewRunStandardList {
  total: number;
  limit?: number | null;
  offset?: number;
  standards: ReviewRunStandard[];
  /** B5: standards the submittal CITES that the library does not hold, each `MISSING_LOCALLY`, as stored on the run. Empty when none, or when the run predates this field. Never paged: all of them on every page. */
  missing_references?: ReviewRunMissingReference[];
  /** #620: Company standards left out, waiting for an administrator; null when none. */
  held_for_confirmation?: ReviewRunHeldForConfirmation | null;
  held_for_engineer?: ReviewRunHeldForConfirmation | null;
}
