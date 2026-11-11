// GENERATED from backend/app/api/agent_review_schemas.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

export type AgentVerdictClass = "Proven by code" | "AI opinion, engineer to confirm" | "AI opinion, rule not yet approved" | "Query for the engineer" | "Not applicable" | "Not reviewed" | "Not checked: rule book not held" | "AI note, no rule book";
export type AgentVerdictWord = "Pass" | "Fail" | "AI thinks: met" | "AI thinks: not met" | "Query" | "Not applicable" | "Not reviewed" | "Not checked" | "AI note";
export type AgentRuleTier = "Owner" | "Engineer" | "AI approved" | "Not AI approved";
export type AgentPart = "not held" | "checklist" | "paper against itself" | "against project papers" | "engineering comment";
export type AgentTextSource = "quote" | "the model's words";
export type AgentMode = "rule review" | "general review";
export type AgentLeftOutReason = "needs another paper" | "needs a human" | "quote not found" | "not labelled yet" | "another equipment type" | "rule book not held" | "the paper names no equipment" | "the paper names equipment the equipment list does not know" | "the paper's equipment could not be read";

/** POST /api/reviews/agent-run body. */
export interface AgentRunRequest {
  submittal_document_id: string;
  /** General review only (a procedure or a contract): the project papers part 4 is checked against. Optional. Never chosen silently: each must be readable by the caller and is checked again when the job runs. Empty: part 4 says so on one line. */
  project_document_ids: string[];
}

/** A project paper a general review was checked against. */
export interface AgentProjectPaper {
  document_id: string;
  name: string;
}

/** GET /api/reviews/agent-status: whether the feature is on and whether the Claude lane is open. Both false means the screen shows no start button. */
export interface AgentStatus {
  enabled: boolean;
  claude_lane_open: boolean;
}

/** GET /api/reviews/runs/{id}/agent/summary. Counts are per class, over the lines of this run only; there is no percentage. */
export interface AgentRunSummary {
  paper_kind: string;
  paper_kind_source: string;
  /** null when the paper has no equipment type (shown as nothing). */
  equipment_type?: string | null;
  counts_by_class: Record<string, number>;
  /** null until spend is known; never 0 for unknown. */
  usd?: number | null;
  models: string[];
  /** null when the run was not stopped early. */
  stop_reason?: string | null;
  missing_books: string[];
  /** how the paper's equipment was read (the state word), null when not known. */
  equipment_state?: string | null;
  /** the sentences about the paper's equipment and the rules left out for it (counts only, no document text). */
  equipment_notes: string[];
  /** lines the AI gave no answer for (class "Not reviewed"); also inside counts_by_class. */
  not_reviewed: number;
  /** "general review" for a procedure or a contract (no rule book, no Pass or Fail); "rule review" otherwise. */
  mode: AgentMode;
  /** the project papers a general review was checked against (empty for a rule review, or when none was named). */
  project_papers_used: AgentProjectPaper[];
}

/** One CRS line of the AI reviewer. */
export interface AgentLine {
  item_id: string;
  verdict_class: AgentVerdictClass;
  word: AgentVerdictWord;
  /** null when the line has no single page. */
  page?: number | null;
  clause: string;
  rule_book: string;
  reason: string;
  /** null for a checklist item, which has no rule tier. */
  rule_tier: AgentRuleTier | null;
  /** general review only: which part the line belongs to; null on a rule review line. */
  part?: AgentPart | null;
  /** general review only: whether the text is a quote or the model's words; null otherwise. */
  text_source?: AgentTextSource | null;
}

/** GET /api/reviews/runs/{id}/agent/lines: one page of lines. */
export interface AgentLineList {
  lines: AgentLine[];
  /** cursor for the next page; null on the last page. */
  next?: string | null;
}

/** One check a line passed through before it was shown. */
export interface AgentGateStep {
  step: string;
  outcome: string;
  reason: string;
}

/** GET /api/reviews/runs/{id}/agent/lines/{item_id}/trace. */
export interface AgentTrace {
  item_id: string;
  page?: number | null;
  paper_quote: string;
  rule_quote: string;
  rule_book: string;
  clause: string;
  model: string;
  reason: string;
  gate: AgentGateStep[];
  /** general review: the second quote (a second place in the paper, or a project paper); null otherwise. */
  other_quote?: string | null;
  /** general review: the part of the review the line belongs to. */
  part?: "not held" | "checklist" | "paper against itself" | "against project papers" | "engineering comment" | null;
}

/** A rule that was asked of this paper. */
export interface AgentAskedRule {
  rule_book: string;
  clause: string;
  quote: string;
  paper_kind: string;
  /** null when the rule has no datasheet field. */
  field?: string | null;
  /** null when the rule has no equipment type. */
  equipment?: string | null;
  tier: "Owner" | "Engineer" | "AI approved" | "Not AI approved";
  /** "scan" for a rule re-read from a scanned page; "text" otherwise. */
  read_from: "text" | "scan";
}

/** A rule that was not asked, with its one reason. */
export interface AgentLeftOutRule {
  rule_book: string;
  clause: string;
  reason: AgentLeftOutReason;
}

/** A rule book the paper cites that we do not hold. Listed, never counted against the system. */
export interface AgentMissingBook {
  name: string;
  why: string;
}

/** How much of one rule book the stored rules cover (free coverage check). The screen computes the percentage from the two integers, so the denominator is always shown; a book with no row in the coverage file has every number null. */
export interface AgentBookCoverage {
  rule_book: string;
  requirement_sentences?: number | null;
  covered_sentences?: number | null;
  unreadable_pages?: number | null;
  weak_pages?: number | null;
  below_half?: boolean | null;
}

/** GET /api/reviews/runs/{id}/rules-used (view only). */
export interface AgentRulesUsed {
  paper_kind: string;
  equipment_type?: string | null;
  asked: AgentAskedRule[];
  left_out: AgentLeftOutRule[];
  /** left-out rules counted per reason. */
  left_out_counts: Record<string, number>;
  missing_books: AgentMissingBook[];
  /** how the paper's equipment was read, and the sentences about it (same as the summary). */
  equipment_state?: string | null;
  equipment_notes: string[];
  /** coverage of each rule book that was asked or left out; empty when no coverage file is placed. */
  books: AgentBookCoverage[];
  /** null unless a person changed the rule set (then their name). */
  rule_set_changed_by?: string | null;
}
