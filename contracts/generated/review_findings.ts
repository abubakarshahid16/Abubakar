// GENERATED from backend/app/schemas.py by scripts/gen_contract_types.py.
// Do not edit: change the backend model and run the script (order 119.1).

export type ReviewCategory = "missing_information" | "inconsistency" | "requirement_deviation" | "document_control" | "technical_query" | "positive_observation";
export type ReviewSeverity = "critical" | "major" | "minor" | "observation";
export type ReviewDisposition = "accepted" | "partially_accepted" | "rejected" | "not_applicable";
export type ReviewStatus = "open" | "in_progress" | "awaiting_response" | "resolved" | "deferred";
export type ApprovalStatus = "pending" | "accepted" | "rejected" | "not_required";
export type ComplianceStatus = "COMPLIANT" | "NON_COMPLIANT" | "MISSING_INFORMATION" | "CONDITIONAL" | "NOT_APPLICABLE" | "NEEDS_ENGINEER_REVIEW" | "NOT_IN_DOCUMENT_SCOPE";

/** R21: one requirement's scope decision from the run's ledger - whether it applies to this submittal and why, in plain words, and who decided. */
export interface ReviewScopeDecision {
  state: string;
  reason_code: string;
  reason: string;
  decided_by: string;
}

export interface ReviewFinding {
  id: string;
  document_id: string;
  baseline_document_id: string | null;
  template_id: string | null;
  discipline: string | null;
  confidence: "low" | "medium" | null;
  category: ReviewCategory;
  severity: ReviewSeverity;
  requirement: string;
  finding: string;
  required_action: string;
  governing_sources: string[];
  unresolved_evidence: string[];
  response_text: string | null;
  disposition: ReviewDisposition | null;
  citation_ids: string[];
  owner_user_id: string | null;
  due_date: string | null;
  status: ReviewStatus;
  approval_status: ApprovalStatus;
  approved_by: string | null;
  approved_at: string | null;
  escalation_level: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  review_run_id?: string | null;
  compliance_status?: ComplianceStatus | null;
  /** WHICH REQUIREMENT AND WHICH SUBMITTED VALUE. A finding says a contractor's number does or does not meet a clause; if the pairing was wrong the finding is wrong, so the reader gets the pairing. */
  requirement_id?: string | null;
  fact_id?: string | null;
  /** The field name found inside the requirement's subject, and the rule that found it. `containment` is the only method today; it is recorded so a second one cannot be added without the finding saying which ran. */
  matched_phrase?: string | null;
  match_method?: string | null;
  /** Why the engine decided what it did, kept SEPARATE from `finding` so a reader can see the reasoning without it being presented as the contractor-facing text. */
  ai_rationale?: string | null;
  /** WHICH EQUIPMENT THE FINDING IS ABOUT, verbatim from the datasheet's own tag row. None where the sheet does not say - a datasheet covering four valves has pages that name none, and a null is the true answer. */
  equipment_tag?: string | null;
  /** THE CITATIONS, WHICH ARE THE FINDING'S EVIDENCE. §12 refuses a finding unless both resolve, so a response that withheld them left the screen showing a verdict with no way to check it - the Review page rendered an empty Standard / clause column until these were added. */
  standard_document_id?: string | null;
  standard_clause?: string | null;
  standard_page?: number | null;
  requirement_source_text?: string | null;
  /** True when the standard this finding was decided against is one the caller may not read: the fields above and `requirement` are withheld. */
  standard_withheld?: boolean;
  /** R21: the requirement's scope decision (None when the run recorded none, or when the standard is withheld from this caller). */
  scope_decision?: ReviewScopeDecision | null;
  /** rule_trust (#947, switch `rule_auto_use_enabled`): who stands behind the rule this finding was decided with - ENGINEER_CONFIRMED, AUTO_PROVEN or UNPROVEN - its tier (SAFETY / STANDARD), whether a COMPLIANT safety-tier result is shown for an engineer's tick, and what the rule said before an UNPROVEN verdict was held for the engineer. None on every finding decided with the switch off: nothing was labelled. */
  trust_label?: string | null;
  tier?: string | null;
  show_for_engineer_tick?: boolean | null;
  rule_said?: string | null;
  contractor_page?: number | null;
  contractor_section?: string | null;
  contractor_evidence_text?: string | null;
  /** WHO STOOD BEHIND THE PAIRING. A model-paired finding is a guess until an engineer says otherwise, and a confirmed finding is never deleted by a re-run. Both are visible here so a reader can tell a confirmed pairing from an unexamined one. */
  confirmed_by?: string | null;
  confirmed_at?: string | null;
  /** Where the finding came from when not the comparison: "chat" (an engineer's comment filed from Chat) or "ai_engineering_check" (a kind C draft - never a verdict, never counted in the review code). NULL for every comparison finding. */
  origin?: string | null;
  /** Owner order section 3: the engineer's own wording, when edited. The CRS prints it in place of the review's text. Null renders as nothing. */
  engineer_comment?: string | null;
}
