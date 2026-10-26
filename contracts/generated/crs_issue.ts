// GENERATED from backend/app/schemas.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

export interface CrsUnreadPage {
  page: number;
  reason?: string | null;
}

export interface CrsOpenFinding {
  finding_id: string;
  row_kind?: string | null;
  item: number;
  /** the row's standard, as the sheet prints it */
  standard?: string | null;
}

/** PF5 (#885): what still stands between a run and its contractor copy. `issuable` only when nothing does. Ids, counts, reasons; names: screen only. */
export interface CrsIssueGate {
  review_run_id: string;
  issuable: boolean;
  final_code_recorded: boolean;
  blockers: string[];
  /** order 127: the pages left to tick */
  unread_pages: CrsUnreadPage[];
  open_findings: CrsOpenFinding[];
  /** order 127: ticked; + unread_pages = the run's list */
  checked_pages?: number[];
  /** order 127: null = not known, never 0 */
  pages_total?: number | null;
}

export interface CrsIssueDecision {
  id: string;
  review_run_id: string;
  kind: string;
  subject: string;
  decision: string;
  reason: string;
  decided_by: string;
  decided_at: string;
  /** order 95 piece 6a: the removal reason code; null when none was given */
  reason_code?: string | null;
  click_id?: string | null;
}

/** Order 95 piece 6a: every decision on a run, newest first. */
export interface CrsIssueDecisionList {
  total: number;
  limit?: number | null;
  offset?: number;
  decisions: CrsIssueDecision[];
}
