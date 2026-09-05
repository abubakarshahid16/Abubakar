/**
 * Contracts for the enterprise features: analysis, gaps, recommendation, market,
 * reports, login. Hand-written like contracts/types.ts, and for the same reason
 * - there is no codegen. When the backend lands each Pydantic model, MERGE the
 * matching interface into contracts/types.ts and delete it here; a field that
 * exists in one place and not the other is silently invisible to the UI.
 *
 * Shapes follow NABAA-SUNDAY-POC-EXECUTION.md section 7.2 and the design docs
 * in docs/design-*.md. Where the two disagree, the design docs win, because they
 * were written against the code: e.g. confidence is never "high", complete is
 * never true, and counts are null when unmeasured rather than 0.
 */

// ------------------------------------------------------------------ analysis

export type AnalysisStatus =
  | "answered"
  | "partial"
  | "gap"
  | "conflict"
  | "insufficient_evidence"
  | "analysis_incomplete"
  | "cancelled";

export type AnalysisRunStatus =
  | "queued"
  | "retrieving"
  | "reranking"
  | "extracting_evidence"
  | "synthesising"
  | "validating"
  | "complete"
  | "cancelled"
  | "failed";

export type PerDocumentStatus =
  | "relevant"
  | "no_sufficient_evidence"
  | "failed"
  | "not_searchable"
  | "pending"
  | "searching"
  | "cancelled";

export interface AnalysisDocumentRow {
  document_id: string;
  filename: string;
  status: PerDocumentStatus;
  /** NULL for failed / not_searchable / pending - "did not search" is not 0.
   *  0 is a real 0: searched, found nothing. */
  validated_evidence_count: number | null;
  error_code: string | null;
}

/** Section 7.2 coverage block. `complete` is `false` or `null`, NEVER `true` -
 *  see docs/design-multi-document-coverage.md. A null must render as nothing. */
export interface AnalysisCoverage {
  authorized_documents_selected: number;
  documents_attempted: number | null;
  documents_search_completed: number | null;
  relevant_documents: number | null;
  no_sufficient_evidence_documents: number | null;
  failed_documents: number | null;
  not_searchable_documents: number | null;
  complete: false | null;
}

export interface EvidenceItem {
  /** sha256(document_id|page_start|page_end|section|exact_span)[:16] - stable
   *  across re-chunking. NOT a chunk id. */
  evidence_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  section: string | null;
  /** Verbatim. Rendered in serif on a quote rule, never as prose. */
  exact_span: string;
  text_source: "extracted" | "recognised";
  ocr_min_conf: number | null;
  ocr_alphabet_violations: number;
  /** Null unless scored in the single rerank batch. Never 0.0 as a stand-in. */
  relevance_score: number | null;
  relevance_score_type: "rerank" | null;
}

export interface DocumentedFinding {
  claim: string;
  citation_ids: string[];
  source_kind: "document" | "user_stated";
  text_source: "extracted" | "recognised" | "mixed";
}

export type ClaimLabel = "agreement" | "addition" | "possible_conflict" | "unresolved";

export interface ClaimRow {
  evidence_id: string;
  filename: string;
  page_start: number;
  section: string | null;
  exact_span: string;
  raw_value: string | null;
  raw_unit: string | null;
  /** Null when the unit is not in the normaliser's table. Never a guess. */
  normalized_value: number | null;
  normalized_unit: string | null;
}

export interface ClaimCluster {
  facet: string;
  label: ClaimLabel;
  rows: ClaimRow[];
}

// ----------------------------------------------------------------------- gaps

export type GapApplicability = "applicable" | "not_applicable" | "insufficient_baseline";
export type GapItemStatus = "met" | "possible_gap" | "conflict" | "insufficient_evidence" | "not_applicable";

export interface BaselineSelection {
  kind: "document" | "document_section" | "stated_requirement";
  document_id: string | null;
  section: string | null;
  /** A typed requirement is THE REQUIREMENT, not evidence. Carries no citation. */
  text: string | null;
}

export interface GapItem {
  facet: string;
  status: GapItemStatus;
  baseline_citation_id: string | null;
  baseline_span: string;
  project_citation_ids: string[];
  note: string | null;
}

export interface GapAnalysis {
  applicability: GapApplicability;
  baseline: BaselineSelection | null;
  items: GapItem[];
}

// ------------------------------------------------------------- recommendation

/** "high" is structurally unreachable, by the same rule that forbids
 *  coverage.complete === true. Documented rather than left as a dead enum. */
export type Confidence = "low" | "medium";

export interface ConfidenceCheck {
  label: string;
  /** true = this check would lower confidence and it fired */
  fired: boolean;
}

export interface Recommendation {
  text: string;
  citation_ids: string[];
  basis: "documents_only" | "documents_and_public_market";
  /** Null when no recommendation was generated, never "low" as a default. */
  confidence: Confidence | null;
  /** The checklist the confidence word was computed from. Displayable. */
  checks: ConfidenceCheck[];
  requires_engineer_approval: true;
}

// --------------------------------------------------------------------- market

export type MarketVerification = "source_read" | "snippet_only" | "source_not_verified";

export interface MarketFinding {
  claim: string;
  url: string;
  publisher: string;
  published_at: string | null;
  retrieved_at: string;
  verification: MarketVerification;
  /** Always true in this build. The machine is offline; every row is sample. */
  is_sample: boolean;
}

export interface EgressState {
  web_search_enabled: boolean;
  allow_public_egress: boolean;
}

/** The ONLY object that may ever leave the machine. Built from user-approved
 *  public fields, never from retrieved document text. */
export interface PublicMarketQuery {
  query: string;
  country: string | null;
  freshness_days: number | null;
}

// --------------------------------------------------------------------- result

export interface AnalysisResult {
  analysis_id: string;
  question: string;
  run_status: AnalysisRunStatus;
  status: AnalysisStatus;
  coverage: AnalysisCoverage;
  documents: AnalysisDocumentRow[];
  evidence_ledger: EvidenceItem[];
  documented_findings: DocumentedFinding[];
  /** Generated prose. Null when synthesis did not run or was refused. */
  summary: string | null;
  summary_truncated: boolean;
  summary_cited_evidence_ids: string[];
  claim_clusters: ClaimCluster[];
  gaps: GapAnalysis;
  public_market_findings: MarketFinding[];
  recommendation: Recommendation | null;
  assumptions: string[];
  limitations: string[];
  /** Sections the plan requires that this build does not produce. Rendered as
   *  named omissions, never as empty sections or zeros. */
  not_implemented_sections: string[];
  batches_done: number | null;
  batches_total: number | null;
  seconds: number | null;
}

// -------------------------------------------------------------------- reports

// ReportDocumentRow, ReportRecord, ReportList and ReportVerification moved to
// contracts/types.ts when stage 2 landed. Shipped API shapes live in the
// contract only.

// ---------------------------------------------------------------------- login

// LoginRequest, Me, LoginResult and AuthStatus moved to contracts/types.ts
// when stage 1 landed. They are shipped API shapes now, and the contract is
// the single source of truth; a second copy here would be free to drift, and
// this one already had - it said `user_id` and `expires_at` where the API
// says `id` and `expires_in_seconds`.

export type AuthMode = "disabled" | "demo_required";
