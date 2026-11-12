// GENERATED from backend/app/api/agent_review_schemas.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

export type AgentVerdictClass = "Proven by code" | "AI verdict, two readers agree" | "Not checked on this paper" | "AI opinion, engineer to confirm" | "AI opinion, rule not yet approved" | "Query for the engineer" | "Not applicable" | "Not reviewed" | "Not checked: rule book not held" | "AI note, no rule book";
export type AgentVerdictWord = "Pass" | "Fail" | "AI verdict: met" | "AI verdict: not met" | "AI verdict: not stated" | "Needs a drawing or a calculation" | "AI thinks: met" | "AI thinks: not met" | "Query" | "Not applicable" | "Not reviewed" | "Not checked" | "AI note";
export type AgentRuleTier = "Owner" | "Engineer" | "AI approved" | "Not AI approved";
export type AgentPart = "not held" | "checklist" | "paper against itself" | "against project papers" | "engineering comment";
export type AgentTextSource = "quote" | "the model's words";
export type AgentMode = "rule review" | "general review";
export type AgentPaperTextState = "readable" | "partly readable" | "no text" | "not indexed" | "still reading";
export type AgentLeftOutReason = "needs another paper" | "needs a human" | "quote not found" | "not labelled yet" | "another equipment type" | "rule book not held" | "the paper names no equipment" | "the paper names equipment the equipment list does not know" | "the paper's equipment could not be read" | "a part excluded by a value the paper states" | "both labelling readers named other equipment";

/** POST /api/reviews/agent-run body. */
export interface AgentRunRequest {
  submittal_document_id: string;
  /** General review only (a procedure or a contract): the project papers part 4 is checked against. Optional. Never chosen silently: each must be readable by the caller and is checked again when the job runs. Empty: part 4 says so on one line. */
  project_document_ids: string[];
  /** Ask for fresh first-reader answers: this run ignores every stored answer and replaces it (only when the server keeps stored answers, `AGENT_REVIEW_REUSE_ANSWERS_ENABLED`; otherwise nothing is stored and the option changes nothing). */
  fresh: boolean;
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

/** What the optional second-reader step did in one run (owner order 13): counts only. `off` is the code that switched the step off for the rest of the run (a cap refusal, a failed call, an unknown first-reader model), null when it ran to the end. */
export interface AgentTwoReaderStep {
  candidates: number;
  asked: number;
  calls: number;
  /** lines that earned the class "AI verdict, two readers agree". */
  agreed: number;
  /** lines where the two readers reached opposite verdicts (a Query for the engineer). */
  disagreed: number;
  /** lines asked where the second reader could not tell, or a quote or a guard did not hold (the line stays as it was). */
  unconfirmed: number;
  /** absence step only: lines not asked because the first reader was not given every page of the paper. */
  skipped: number;
  off?: string | null;
}

/** Decisions of one run (owner, 12 Nov 2026): lines the code proved (class "Proven by code") plus two-reader verdicts (class "AI verdict, two readers agree" with the word met, not met or not stated). "AI thinks" and Queries are not decisions. `not_stated`: how many of the two-reader figure are "not stated on the paper" (two readers each read every page and found no value). */
export interface AgentDecisions {
  code: number;
  two_reader: number;
  not_stated: number;
  total: number;
}

export interface AgentPaperText {
  state: AgentPaperTextState;
  /** null when the library holds no page count for the paper. */
  pages_total?: number | null;
  /** page numbers with no stored text (every page when state is "no text"). */
  pages_not_read: number[];
  /** the one plain sentence for a state other than "readable"; null when readable. */
  sentence?: string | null;
}

/** The optional second reading of pages ended early in this run (a cap or an error inside it, never the review). */
export interface AgentPageRereadStop {
  /** plain words for the reason, no document text. */
  why: string;
  /** silent lines that were not re-read because it had ended (the lines carrying the marker; counts equal lines). */
  not_reread: number;
}

/** Lines whose class changed since the previous finished run of the same paper (compared before the optional steps). Counts only; the ids are in the run's trace. `decisions`: how many of those lines are, or were, a proven Pass or Fail or an AI opinion met or not met. */
export interface AgentChangedSincePrevious {
  previous_run_id: string;
  lines_compared: number;
  changed: number;
  decisions: number;
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
  /** null when the second reading of pages is off or ran fully (shown as nothing, never 0). */
  page_reread_stopped?: AgentPageRereadStop | null;
  /** answers taken from an earlier run instead of asking (USD 0 each); null when the server does not keep stored answers. */
  answers_reused?: number | null;
  /** null when there is no earlier finished run of this paper, or this run did not finish whole. */
  changed_since_previous?: AgentChangedSincePrevious | null;
  /** lines the AI gave no answer for (class "Not reviewed"); also inside counts_by_class. */
  not_reviewed: number;
  /** "general review" for a procedure or a contract (no rule book, no Pass or Fail); "rule review" otherwise. */
  mode: AgentMode;
  /** the project papers a general review was checked against (empty for a rule review, or when none was named). */
  project_papers_used: AgentProjectPaper[];
  /** the second-reader step of this run (counts and one code, no text); null when the step was off or the run was stored before it. */
  two_reader_step?: AgentTwoReaderStep | null;
  /** the same for the absence word ("AI verdict: not stated"); null when that step was off or the run was stored before it. */
  two_reader_absence_step?: AgentTwoReaderStep | null;
  /** the same for the other-paper class ("Not checked on this paper"); null when that step was off. */
  two_reader_other_step?: AgentTwoReaderStep | null;
  /** the one count of decisions: code Pass/Fail plus two-reader verdicts (class "AI verdict, two readers agree", word met or not met). */
  decisions?: AgentDecisions | null;
  /** the paper's stored-text state; null on a run stored before it was kept (shown as nothing). */
  paper_text?: AgentPaperText | null;
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

/** AI-approved rules of the paper's kind that sit in rule books the run did NOT select (counts only). */
export interface AgentOtherBooks {
  books: number;
  ai_approved_rules: number;
  /** whose books these counts cover, in words. */
  boundary: string;
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

/** One rule book that was a candidate for this review, or was only considered, with what happened to its rules. */
export interface AgentBookRow {
  rule_book: string;
  /** true when the book's rules were candidates; false when the book was only considered and not included. */
  in_review: boolean;
  /** the fixed words for what decided it (never text from the paper): named in the paper, governs this equipment type, ... */
  method: string;
  /** how many rules the library stores for this book (all of them, whatever their label); null when not counted. */
  stored_rules?: number | null;
  /** rules of this book asked in this review. */
  asked: number;
  /** rules of this book that were candidates and not asked, counted per reason. */
  left_out: Record<string, number>;
}

/** Which held rule books were candidates for this review and which were not (view only). */
export interface AgentBookTable {
  books: AgentBookRow[];
  /** whose books these rows cover, in words (rule 4: every count states its boundary). */
  boundary: string;
  /** rule books of this review the reader may not read: counted, never named (rule 5). */
  hidden_books: number;
  /** a sentence when no book selection was stored for this run (rules came from per-rule decisions); null otherwise. */
  note?: string | null;
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
  /** where the candidate rules came from; null on a run stored before this was kept (shown as nothing). */
  candidates_from?: "per-rule scope decisions" | "the rules of the selected books" | "the rules of the selected books and per-rule scope decisions" | null;
  /** rules that were the same rule as another candidate (not asked twice, not in either list); null when not kept. */
  same_rule_repeats?: number | null;
  /** AI-approved rules of this paper kind in rule books the run did not select; null when not kept. */
  other_books?: AgentOtherBooks | null;
  /** the book-by-book table: which held rule books were candidates and which were not, and why; null on a run stored before it was kept. */
  book_table?: AgentBookTable | null;
  /** why the run stopped early, or why no rule was asked (the same words as the summary); null when it ran to its end. */
  stop_reason?: string | null;
  /** the paper's stored-text state; null on a run stored before it was kept. */
  paper_text?: AgentPaperText | null;
}
