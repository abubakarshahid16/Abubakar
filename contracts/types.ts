// Shared API types. Hand-written, source of truth for the UI.
// Backend mirrors these in Pydantic models.

// ---------- documents ----------

/** Ingestion order: the keyword index is built BEFORE embedding, so a document
 *  answers questions from `partially_searchable` onward. Embedding then
 *  upgrades it from keyword-only to hybrid in the background. */
export type DocStatus =
  | "queued"
  | "extracting"
  | "chunking"
  | "indexing_keyword"
  | "partially_searchable"   // keyword search works, vectors still arriving
  | "ready"                  // keyword + vector both complete
  | "no_searchable_content"  // finished, but nothing is searchable - NOT ready
  | "failed";

/** A document can answer questions in these states - never block on embedding. */
export const ANSWERABLE: DocStatus[] = ["partially_searchable", "ready"];

/** A doc is only browsable-as-complete when status === "ready". */
export const isReady = (d: DocumentRecord) => d.status === "ready";

export interface DocumentRecord {
  id: string;
  filename: string;          // sanitised; display only
  sha256: string;
  size_bytes: number;
  page_count: number | null; // null until the manifest is read
  pages_done: number;
  /** chunks search can actually see (retrievable only) */
  chunk_count: number;
  /** every chunk row, including ones kept only for inspection */
  chunk_count_total: number;
  /** The disciplines this document is granted to - its CATEGORY, as the
   *  access model defines it (plan line 1010: discipline IS the grant). An
   *  empty list is meaningful and must render as such: the document is held by
   *  no discipline and only an administrator can read it - "general", in the
   *  owner's words. Never a placeholder for an empty list. Required, not
   *  optional, so a missing field is a contract error rather than a silent
   *  "uncategorised". */
  disciplines: string[];
  /** how many retrievable chunks have vectors so far */
  embedded_count: number;
  status: DocStatus;
  /** Pages with no usable extractable text - candidates for recognition.
   *  NOT the same as recognised_pages: some of these are simply blank. */
  needs_ocr_pages: number;
  /** Pages OCR actually read text from. A COUNT, never a badge: a 546-page
   *  document with 12 recognised pages must not be presented as "OCR'd".
   *  State the fraction - "12 of 546 pages read by OCR". */
  recognised_pages: number;
  /** pages whose mathematics did not survive extraction; see the page image */
  equation_pages: number;
  error: ApiError | null;
  /** Pages search cannot see AT ALL - not a quiet count. The Documents screen
   *  said "3 excluded" for chunks and said nothing about a dropped page that
   *  held an entire clause. */
  pages_excluded?: number;
  pages_excluded_characters?: number;
  /** Excluded pages carrying numbered clause headings AND real prose. Should
   *  always be zero; if it is not, real content was almost certainly dropped.
   *  Render as an ALERT, never a count. */
  pages_excluded_with_clause_headings?: number;
  uploaded_at: string;       // ISO 8601
  indexed_at: string | null;
}

export interface UploadAccepted {
  /** ABSENT when the bytes duplicate a document this caller may not read
   *  (#79). `ingest` dedupes by sha256 and returns the EXISTING row, so
   *  returning it would disclose that document's filename, status and page
   *  count to someone with no grant for it - and suppressing `duplicate_of`
   *  alone would move the leak here rather than close it. Render the
   *  `awaiting_grant` message when this is missing; never a placeholder
   *  record. */
  document?: DocumentRecord;
  job_id: string;
  /** Set when sha256 already exists and no job started - and null when the
   *  caller may not read that document. The id is derived from the content
   *  hash, so stating it would confirm the content as well as the existence. */
  duplicate_of: string | null;
  /** The upload was accepted and there is nothing for this caller to see
   *  until an administrator grants it. About the CALLER's request, never
   *  about the corpus: it does not distinguish a duplicate from anything
   *  else, so it is not an existence oracle. */
  awaiting_grant?: boolean;
}

/** DELETE /api/documents/{id}
 *
 *  Typed because it was not. The conversation-delete response was a COPY of
 *  this shape with the field names left alone, so it returned a conversation
 *  TITLE under a key called `filename` - and a client reading it built a wrong
 *  model of what it had deleted. The mistake was invisible because a title
 *  looks exactly as plausible under that key as a filename does.
 *
 *  Both routes were `request<unknown>` on the client, which is why nothing
 *  caught it: there was no shape to drift FROM. */
export interface DeletedDocument {
  deleted: string;
  filename: string;
  rows_removed: Record<string, number>;
  files_removed: number;
}

/** DELETE /api/conversations/{id} - a conversation has a TITLE. */
export interface DeletedConversation {
  deleted: string;
  title: string;
  rows_removed: Record<string, number>;
  /** No files_removed: a conversation deletes no files, and a truthful-looking
   *  0 for something that never applies is how a field stops meaning
   *  anything. */
}

// ---------- engineering review workflow ----------

export type ReviewCategory =
  | "missing_information"
  | "inconsistency"
  | "requirement_deviation"
  | "document_control"
  | "technical_query"
  | "positive_observation";
export type ReviewSeverity = "critical" | "major" | "minor" | "observation";
export type ReviewDisposition = "accepted" | "partially_accepted" | "rejected" | "not_applicable";
export type ReviewStatus = "open" | "in_progress" | "awaiting_response" | "resolved" | "deferred";
export type ApprovalStatus = "pending" | "accepted" | "rejected" | "not_required";

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
}

export interface ReviewFindingEvent {
  id: string;
  finding_id: string;
  event_type: "created" | "updated";
  changes: Record<string, unknown>;
  actor_user_id: string | null;
  created_at: string;
}

export interface ReviewTemplate {
  id: string;
  name: string;
  version: string;
  description: string;
  discipline: string | null;
  deliverable_type: string | null;
  governing_sources: string[];
  categories: string[];
  severity_levels: string[];
  approval_terms: string[];
  required_sections: string[];
  active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewFindingCreate {
  document_id: string;
  baseline_document_id?: string | null;
  template_id?: string | null;
  discipline?: string | null;
  confidence?: "low" | "medium" | null;
  category: ReviewCategory;
  severity: ReviewSeverity;
  requirement: string;
  finding: string;
  required_action: string;
  governing_sources?: string[];
  unresolved_evidence?: string[];
  response_text?: string | null;
  disposition?: ReviewDisposition | null;
  citation_ids?: string[];
  owner_user_id?: string | null;
  due_date?: string | null;
  status?: ReviewStatus;
  approval_status?: ApprovalStatus;
  escalation_level?: number;
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface ReviewFindingUpdate {
  owner_user_id?: string | null;
  due_date?: string | null;
  severity?: ReviewSeverity;
  required_action?: string;
  response_text?: string | null;
  disposition?: ReviewDisposition | null;
  status?: ReviewStatus;
  approval_status?: ApprovalStatus;
  escalation_level?: number;
  approved_by?: string | null;
  approved_at?: string | null;
}

export type DeliverableStatus = "planned" | "in_progress" | "submitted" | "under_review" | "approved" | "rejected" | "superseded";
export interface Deliverable {
  id: string;
  wbs_code: string;
  title: string;
  deliverable_type: string;
  revision: string;
  status: DeliverableStatus;
  document_id: string | null;
  owner_user_id: string | null;
  planned_date: string | null;
  due_date: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}
export type StakeholderRole = "owner" | "reviewer" | "approver" | "informed";
export interface DeliverableStakeholder {
  deliverable_id: string;
  user_id: string;
  role: StakeholderRole;
  email: string;
  display_name: string | null;
}
export interface DeliverableStakeholderAssignment { user_id: string; role: StakeholderRole; }
export interface DeliverableCreate {
  wbs_code: string;
  title: string;
  deliverable_type: string;
  revision?: string;
  status?: DeliverableStatus;
  document_id?: string | null;
  owner_user_id?: string | null;
  planned_date?: string | null;
  due_date?: string | null;
  submitted_at?: string | null;
  approved_at?: string | null;
}
export type DeliverableUpdate = Partial<DeliverableCreate>;

export interface DeliverableAlert {
  deliverable_id: string;
  wbs_code: string;
  title: string;
  due_date: string;
  days_overdue: number;
  escalation_level: number;
  severity: "minor" | "major" | "critical";
}
export interface ManagementSummary {
  deliverables_total: number;
  deliverables_by_status: Record<string, number>;
  review_findings_total: number;
  findings_by_severity: Record<string, number>;
  findings_by_status: Record<string, number>;
  escalated_findings: number;
  overdue_alerts: number;
  alerts: DeliverableAlert[];
}
export interface EscalationRule {
  level: number;
  trigger_days: number;
  recipient_role: string;
  action: string;
  enabled: boolean;
}

// ---------- jobs ----------

export type JobStage = "extract" | "chunk" | "embed" | "index";
export type JobState = "running" | "paused" | "done" | "failed";

export interface JobRecord {
  id: string;
  document_id: string;
  stage: JobStage;
  state: JobState;
  pages_total: number | null;
  pages_done: number;
  last_completed_batch: number | null; // resume point
  retries: number;
  error: ApiError | null;
  started_at: string;
  updated_at: string;
}

// ---------- retrieval ----------

export type ChunkKind = "prose" | "table" | "toc" | "frontmatter" | "index" | "references";

export interface ChunkRecord {
  id: string;
  ordinal: number;
  page_start: number;
  page_end: number;
  section: string | null;
  kind: ChunkKind;
  token_count: number;
  content_hash: string;
  /** false for front matter, contents, index, and text that fails the
   *  content-quality gate. Stored for inspection, excluded from search. */
  retrievable: boolean;
  /** why the quality gate rejected it, when it did */
  quality_flags: string | null;
  text: string;
}

export interface PageRecord {
  page_no: number;
  char_count: number;
  needs_ocr: boolean;
  /** the maths on this page did not survive extraction - show the page image */
  equation_heavy: boolean;
  batch_no: number;
  preview: string;
}

export interface PagesResponse {
  total: number;
  limit: number;
  offset: number;
  pages: PageRecord[];
}

/** GET /api/documents/{id}/excluded - nothing is dropped without a record. */
export interface ExclusionRecord {
  scope: "page" | "chunk";
  /** Non-zero means the dropped text carried numbered clause headings AND
   *  real prose - body text, not furniture. An exclusion carrying this almost
   *  certainly threw real content away, which is what happened to NORSOK
   *  page 11 and its entire Clause 8. Render as an ALERT, never a count. */
  clause_headings?: number;
  page_start: number | null;
  page_end: number | null;
  chunk_id: string | null;
  rule: string;
  reason: string | null;
  text_length: number;
  text_sample: string;
}

/** One rule's tally. Shared by the exclusion viewer and the dashboard. */
export interface ExclusionSummary {
  scope: string;
  rule: string;
  count: number;
  characters_dropped: number;
  /** excluded pages under this rule that carried clause headings */
  clause_heading_pages?: number;
}

export interface ExclusionsResponse {
  total: number;
  summary: ExclusionSummary[];
  limit: number;
  offset: number;
  excluded: ExclusionRecord[];
}

export interface WorkerStatus {
  alive: boolean;
  current_document: string | null;
  /** only proves the loop is spinning - not that work is moving */
  seconds_since_heartbeat: number;
  /** since a document last reached a terminal state - the honest signal */
  seconds_since_progress: number;
  documents_completed: number;
  /** non-terminal work waiting; a backlog must be visible on screen */
  pending_count: number;
  oldest_pending_age_seconds: number | null;
  /** not alive, OR no heartbeat, OR work pending with no progress */
  stalled: boolean;
  stalled_reasons: string[];
  /** response-safe only; tracebacks go to the local log */
  last_error: ApiError | null;
}

export interface ChunkPage {
  total_matching: number;
  limit: number;
  offset: number;
  chunks: ChunkRecord[];
}

export interface Passage {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  section: string | null;
  text: string;              // exact source text, never paraphrased
  score: number;             // post-rerank
  /** char offsets into `text` for the answer span, when Tier 1 can locate one */
  highlight: [number, number] | null;
}

// ---------- answers (two-tier) ----------

/** Tier 1 = quoted source, no LLM. Tier 2 = generated prose. Never conflate.
 *  This is the request-side tier. The RESPONSE says `answer_type`, which is
 *  not the same set: an "extract" request can legitimately come back as
 *  insufficient_evidence, and the UI must render what came back rather than
 *  what it asked for. */
export type AnswerTier = "extract" | "generated";

/** What the server actually produced.
 *  - extract               a verbatim quotation from a document
 *  - generated             prose written by the local model, every claim cited
 *  - insufficient_evidence nothing credible was retrieved; there is no answer
 *  - model_unavailable     Tier 2 was asked for and the model could not be reached
 *  The UI must present a quotation and generated prose differently. */
export type AnswerType =
  | "extract"
  | "generated"
  | "insufficient_evidence"
  | "model_unavailable"
  /** the input was never a document question - a greeting, thanks, chitchat.
 *  Nothing was searched, so there is nothing to show as considered. */
  | "guidance"
  /** a non-sensitive aggregate from application metadata, not document text */
  | "metadata";

export interface AnswerPassage {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  section: string | null;    // the clause, when the document numbers its clauses
  text: string;              // exact source text, never paraphrased
  /** char offsets into `text` for the answering span, when one can be located */
  highlight: [number, number] | null;
  /** offsets of the chunk that actually MATCHED, inside the expanded passage.
   *  Retrieval works on the small chunk; the reader is shown the parent block. */
  match_span: [number, number] | null;
  /** how many chunks were joined to form this passage */
  chunks_joined: number;
  /** A table cannot be reflowed as prose: its column pairing is positional,
   *  so wrapping it destroys the only structure it has. Render one in a
   *  monospace grid that scrolls sideways rather than wrapping it. */
  kind: ChunkKind;
  score: number;
  identifier_hits: string[];
  /** Where these characters came from.
   *
   *  `"extracted"` - out of the PDF's own text layer. This CAN carry the
   *  "Quoted verbatim from the document" label, because it is literally true.
   *
   *  `"recognised"` - OCR read them off a page image. A guess about pixels,
   *  and it must NEVER carry the verbatim label: measured errors include
   *  `Pyblish` for "Publish" and `≦` where the document says `≤`. Render
   *  "Read by OCR from a scanned page" instead, with the page image EXPANDED
   *  rather than collapsed - a label that says "check it against the page"
   *  while the page is hidden is a label that expects to be ignored.
   *
   *  A chunk spanning one recognised page and one extracted page is
   *  `"recognised"`: a reader cannot tell which sentence came from where, so
   *  the label makes the weaker claim. */
  text_source: "extracted" | "recognised";
  /** Lowest OCR confidence across the chunk's recognised pages - the weakest
   *  evidence governs. null for extracted text. This is DATA, not a gate:
   *  nothing is hidden on the strength of it, and no threshold is set until
   *  there is labelled ground truth to set one from. */
  ocr_min_conf: number | null;
  /** Characters in this passage the document's script cannot contain.
   *
   *  PROOF of a substitution, not an opinion about one. Confidence is the
   *  model's opinion of itself: two passages can both sit at 0.95 and one of
   *  them contains 凤. A CJK ideograph in an English specification is
   *  evidence, and the dangerous member of the class is `≦`, which reads as
   *  `≤` to a skimming engineer.
   *
   *  ESCALATES the OCR label rather than replacing it - the reader's action is
   *  unchanged (check the page) but the reason is specific and much stronger.
   *  Never hides the passage. */
  ocr_alphabet_violations: number;
  /** The distinct offending characters, for showing the reader what they are. */
  ocr_alphabet_sample: string | null;
}

/** Where a document stood in relation to the answer.
 *
 *  `credible_not_cited` is the one a reader acts on: a passage from this
 *  document cleared the credibility floor and the answer used others instead,
 *  because an answer takes only its highest-ranked passages. It is not a
 *  retrieval failure and must not be worded as one. */
export type DocumentCoverageStatus =
  | "answered"
  | "supporting"
  | "credible_not_cited"
  | "retrieved_not_credible"
  | "expected_not_shortlisted"
  | "expected_not_retrieved"
  | "searched_no_match";

export interface DocumentCoverage {
  document_id: string;
  filename: string;
  status: DocumentCoverageStatus;
  /** Carries a distinguishing term from the question. PRESENCE, NOT
   *  RELEVANCE - no completeness claim rests on this, and it must not be
   *  rendered as a relevance judgement. */
  expected: boolean;
  distinguishing_terms: string[];
  /** Reached the fused candidate pool. 0 is a real 0. */
  candidates: number;
  shortlisted: number;
  /** Null unless a passage from this document was scored in the final rerank
   *  batch. Never 0.0 as a stand-in - 0.0 sits above the -3.0 floor and would
   *  read as credible. Do not default it in the UI. */
  best_rerank_score: number | null;
  reason: string | null;
}

/** Which documents the question was about, and which the answer used.
 *
 *  Null on the AnswerResult for a refusal, deliberately: an incidence table
 *  under a refusal invites the reader to read it as evidence the corpus could
 *  have answered after all. */
export interface Coverage {
  /** What the completeness verdict rests on.
   *
   *  There is no `term_incidence` basis, by measurement rather than oversight:
   *  it made all twelve documents "expected" on the gold question this feature
   *  exists to measure, because "contain" is an ordinary English verb present
   *  in every one of them. */
  basis: "credible_uncited" | "single_document_scope" | "none";
  /** Documents that produced a credible passage. Null when no completeness
   *  claim is being made - never 0. */
  expected_documents: number | null;
  found_documents: number | null;
  searched_documents: number;
  /** `false` when a credible passage went unused. Otherwise NULL. NEVER true.
   *
   *  A NULL MUST RENDER AS NOTHING AT ALL - no tick, no green, no "complete"
   *  wording. Rendering a null as a checkmark converts "I did not check" into
   *  "I checked and it is fine", which is the single easiest way for this
   *  feature to become a lie. `complete === false` names the gap and the
   *  document; anything else says nothing. */
  complete: boolean | null;
  documents: DocumentCoverage[];
  note: string | null;
}

/** A source that did not fit the model's context window.
 *
 *  A numeric table costs about ONE TOKEN PER CHARACTER against a 1,536-token
 *  window, because the tokenizer splits digits individually - so three table
 *  passages need roughly 3,645 tokens and cannot fit. Before this field the
 *  runtime discarded the overflow inside llama.cpp and reported FEWER tokens
 *  evaluated than the window holds, which is indistinguishable from a small
 *  prompt. The answer was generated from what survived, citing sources it had
 *  never been shown.
 *
 *  THE UI MUST SAY SO, for the same reason it must say so for `truncated`. An
 *  answer built on two of three sources is not wrong, but a reader who thinks
 *  it saw three cannot judge it. */
export interface EvidenceRemoved {
  /** 1-based position in the sources as retrieved. */
  index: number;
  filename: string | null;
  page_start: number | null;
  action: "trimmed" | "dropped";
  characters_kept: number;
  characters_dropped: number;
}

/** What a client may know about itself.
 *
 *  ROLES, NEVER GRANTS. The document ids a user may see are deliberately
 *  absent: the scope is derived server-side on every request, and handing the
 *  client the list gives it something to check its guesses against. */
export interface Me {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
}

/** Whether signing in is required here, and who is signed in.
 *
 *  The frontend calls `/api/auth/me` once at startup and the ANSWER decides
 *  the screen: a 401 means show the login form; `required: false` means
 *  authentication is off and there is nothing to sign in to.
 *
 *  `/api/health` deliberately does not carry this. Health is unauthenticated
 *  and was narrowed on purpose. */
export interface AuthStatus {
  required: boolean;
  user: Me | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResult {
  /** Held in a module-level variable in `client.ts`. NEVER localStorage -
   *  that outlives the tab, and every XSS becomes credential theft rather
   *  than a session-length nuisance. A page reload logs you out, and the UI
   *  says so rather than letting the reader discover it. */
  token: string;
  user: Me;
  expires_in_seconds: number;
}

export interface PasswordResetRequest {
  token: string;
  password: string;
}

export interface PasswordResetResult {
  reset: true;
}

// ---------------------------------------------------------------- progress

export interface ProgressStep {
  stage: string;
  at_seconds: number;
}

/** What the machine is doing, REPORTED BY THE WORK ITSELF - never inferred
 *  from a clock on the client.
 *
 *  There is deliberately no percentage. The length of a generation is unknown
 *  until it ends, so a bar would be an invention; a stage, a count and an
 *  elapsed time are all true. */
export interface Progress {
  stage: "retrieving" | "reranking" | "reading" | "generating" | "done";
  /** e.g. "3 passages" - a count, never a percentage. */
  detail: string | null;
  seconds: number;
  /** Every transition that actually happened, and when. */
  history: ProgressStep[];
}

// ---------------------------------------------------------------- analysis

/** One retrieved passage, as everything downstream cites it.
 *
 *  `evidence_id` is sha256 over the document, page span, section and quoted
 *  text - NOT a chunk id. Chunk ids change when a document is re-chunked, and
 *  a citation that moves when the chunker is retuned is not a citation. */
export interface EvidenceItem {
  evidence_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  section: string | null;
  /** Verbatim. Render in serif on a quote rule, never as prose. */
  exact_span: string;
  text_source: "extracted" | "recognised";
  ocr_min_conf: number | null;
  ocr_alphabet_violations: number;
  /** Null unless scored in the final rerank batch. Never 0.0 as a stand-in -
   *  0.0 sits above the -3.0 floor and reads as credible. */
  relevance_score: number | null;
  /** WHICH SCALE the number is on. A rerank score and an RRF score are not
   *  comparable, so a bare number would invite exactly the comparison this
   *  system forbids. Null when nothing scored it. */
  relevance_score_type: "rerank" | null;
}

export interface DocumentedFinding {
  claim: string;
  citation_ids: string[];
  /** Nothing generated here is `user_stated`: a typed requirement is THE
   *  REQUIREMENT, not evidence, and never enters an evidence ledger. */
  source_kind: "document" | "user_stated";
  text_source: "extracted" | "recognised" | "mixed";
}

/** A sentence removed from the prose, and why. A sentence carrying a number
 *  that appears in no span it cites is DROPPED, never rendered with a warning
 *  beside it - the number would still be on screen, and the reader takes the
 *  number. */
export interface DroppedSentence {
  sentence: string;
  reason: string;
}

export interface AnalysisSummaryResult {
  question: string;
  evidence_ledger: EvidenceItem[];
  /** Null when synthesis did not run or was refused. Null renders as NOTHING -
   *  never an empty prose block. */
  summary: string | null;
  summary_truncated: boolean;
  summary_cited_evidence_ids: string[];
  documented_findings: DocumentedFinding[];
  rejected_citations: number[];
  evidence_removed: EvidenceRemoved[];
  refusal: string | null;
  dropped_sentences: DroppedSentence[];
  not_implemented_sections: string[];
}

export type ClaimLabel = "agreement" | "addition" | "possible_conflict" | "unresolved";

export interface ClaimClusterOut {
  /** Human-readable, e.g. "thickness / um". */
  facet: string;
  /** `possible_conflict`, never `conflict`: documents carry no revision or
   *  approval status, so which supersedes the other cannot be known. */
  label: ClaimLabel;
  rows: Record<string, unknown>[];
  note: string | null;
}

export interface BaselineSelectionOut {
  kind: "document" | "document_section" | "stated_requirement";
  document_id: string | null;
  section: string | null;
  text: string | null;
}

export type GapItemStatus =
  | "met"
  | "possible_gap"
  | "conflict"
  | "insufficient_evidence"
  | "not_applicable";

export interface GapItemOut {
  facet: string;
  status: GapItemStatus;
  baseline_citation_id: string | null;
  baseline_span: string;
  project_citation_ids: string[];
  note: string | null;
}

export interface GapAnalysisOut {
  /** `not_applicable` when the caller named no baseline. The system NEVER
   *  chooses one: picking the oldest document, or the one with "standard" in
   *  its name, would be an engineering judgement it has no basis for. */
  applicability: "applicable" | "not_applicable" | "insufficient_baseline";
  baseline: BaselineSelectionOut | null;
  items: GapItemOut[];
}

export interface AnalysisGapsResult {
  question: string;
  evidence_ledger: EvidenceItem[];
  claim_clusters: ClaimClusterOut[];
  gaps: GapAnalysisOut;
  not_implemented_sections: string[];
}

export interface ConfidenceCheckOut {
  label: string;
  /** true = this check lowered confidence */
  fired: boolean;
}

export interface RecommendationOut {
  text: string;
  citation_ids: string[];
  basis: string;
  /** "high" is structurally unreachable, by the same rule that forbids
   *  `coverage.complete === true`. */
  confidence: "low" | "medium" | null;
  checks: ConfidenceCheckOut[];
}

export interface AnalysisRecommendationResult {
  question: string;
  evidence_ledger: EvidenceItem[];
  /** Null is not an empty recommendation. */
  recommendation: RecommendationOut | null;
  public_market_findings: MarketFinding[];
  not_implemented_sections: string[];
}

export interface AnalysisRequest {
  question: string;
  limit?: number;
  /** The caller's choice of authoritative document. Never chosen by the
   *  system. */
  baseline_document_id?: string | null;
  /** OPTIONAL, AND MAY ONLY NARROW. Absent or empty, every analysis route
   *  behaves exactly as it did before classification existed. Present, the
   *  caller's access scope is INTERSECTED with the matching documents, so a
   *  filter naming a type whose documents they may not read returns nothing
   *  rather than leaking one. `backend/app/main.py::_analysis_scope`. */
  scope?: ClassificationScope | null;
}

// ------------------------------------------------------------------- market

/** How a finding was checked. The full vocabulary, because a UI must be able
 *  to render each state - but see `MarketFinding.verification`: this build
 *  can only ever produce the last one. */
export type MarketVerification = "source_read" | "snippet_only" | "source_not_verified";

/** An ILLUSTRATIVE row: a bundled fixture, never a retrieved result.
 *
 *  `is_sample` is always true and is neither optional nor defaulted. A row
 *  that could omit it could be mistaken for a real finding, and the UI must
 *  never present one as a source. */
export interface MarketFinding {
  claim: string;
  /** Always `sample://` - a scheme that resolves nowhere, chosen so a row
   *  cannot become a real citation by being clicked. */
  url: string;
  publisher: string;
  published_at: string | null;
  retrieved_at: string;
  /** Pinned, not widened to MarketVerification: nothing in this build has
   *  been read, so no row may claim it was. */
  verification: "source_not_verified";
  is_sample: true;
}

export interface EgressState {
  web_search_enabled: boolean;
  allow_public_egress: boolean;
}

export interface MarketFindings {
  /** "SAMPLE DATA - NOT LIVE", in full. Render it; do not summarise it. */
  notice: string;
  egress: EgressState;
  findings: MarketFinding[];
  is_sample: true;
}

export interface MarketQueryRequest {
  query: string;
  country: string | null;
  freshness_days: number | null;
}

/** What WOULD be sent. `sent` is always false and nothing left the machine. */
export interface MarketQueryPreview {
  query: string;
  country: string | null;
  freshness_days: number | null;
  would_be_sent_to: null;
  sent: false;
  reason: string;
}

// ------------------------------- live public-market intelligence (flag off)
//
// THESE LIVE HERE, not in api/client.ts, and the reason is a defect that
// already happened. They were declared inside the frontend client, so there
// was no single source of truth for this contract - and when the backend
// renamed `payload` to `payloads`, `tsc` passed, all 23 panel tests passed,
// and the confirmation dialog rendered `undefined` where the outbound payload
// must appear. The tests mocked the backend using the frontend's own
// interface, so they proved the panel agreed with itself.
//
// The authority is backend/app/schemas.py: MarketPreview, MarketSearchResult,
// MarketRow, MarketPreviewPayload, MarketOutboundPayload. Change one, change
// both, in the same commit.

/** Which kind of source a row came from.
 *
 *  A CLOSED set, and the row's own words - never derived from the url, the
 *  publisher or anything else the UI can see. A reference row that reached a
 *  compliance screen wearing a market-search label is the defect this type
 *  exists to make impossible, so there is no fallback member and no optional
 *  marker: a row without one does not type-check. */
export type MarketProviderLabel =
  | "market search"
  | "published literature"
  | "reference - background only"
  /** The labelled fixtures served while live egress is off. Its OWN label
   *  rather than a borrowed one: samples were once labelled
   *  "reference - background only", which made the panel print "this row is
   *  not a market finding" over rows that are illustrative MARKET rows. Both
   *  sentences were true of a sample and the provenance was still wrong -
   *  no tier produced these, which is the point of them. */
  | "sample - illustrative only";

/** THE OBJECT THAT WOULD LEAVE THIS MACHINE, for one tier.
 *
 *  A CLOSED shape whose closure is load-bearing rather than tidy: everything
 *  in it is sent, so a field added here is a field added to what leaves.
 *  There is deliberately nothing that could carry a passage - no `context`,
 *  no `evidence`, no `surrounding_text`. */
export interface MarketOutboundPayload {
  /** The scrubbed phrase, and the ONLY free text that leaves the machine. */
  phrase: string;
  tier: string;
  provider_label: string;
  country: string | null;
  freshness_days: number | null;
}

export interface MarketPreviewPayload {
  tier: string;
  provider_label: string;
  payload: MarketOutboundPayload;
}

/** What WOULD be sent, per tier. This route performs NO egress and is safe to
 *  call on every keystroke.
 *
 *  `payloads` IS A LIST, one entry per CONFIGURED tier, in attempt order,
 *  BECAUSE THAT IS WHAT ACTUALLY LEAVES. A single payload could not be
 *  honest: a search builds one per tier, so showing one meant the user
 *  approved an object that was never sent while up to three others were.
 *  Render every entry, or the dialog is back to implying that one of them is
 *  the whole request.
 *
 *  `phrase` null means nothing safe survived and NO SEARCH IS POSSIBLE - not
 *  "send the raw text instead". A UI that falls back to the typed string here
 *  has broken the only guarantee that matters. */
export interface MarketPreview {
  phrase: string | null;
  payloads: MarketPreviewPayload[];
  /** Tiers this build could attempt, in order. Empty is a real state. */
  tiers_configured: string[];
  /** Tiers that cannot run here. Reported SEPARATELY from configured and from
   *  `tiers_attempted`, because nothing is ever sent to them - so a UI must
   *  not say one was "tried". */
  tiers_unconfigured: string[];
  /** tier id -> label. Sent so the UI never keeps its own copy of this
   *  mapping, which is how a reader ends up seeing "web" on one line and
   *  "market search" on the next. */
  tier_labels: Record<string, string>;
}

export interface MarketSearchRequest {
  phrase: string;
  country?: string | null;
  freshness_days?: number | null;
}

/** One public finding, or one labelled sample.
 *
 *  `published` is nullable and a null must render as NOTHING - not a dash, not
 *  "N/A", and never today's date, which would date an undated page.
 *  `retrieved` is when this machine fetched it and is always present. */
export interface MarketRow {
  text: string;
  provider_label: MarketProviderLabel;
  publisher: string;
  published: string | null;
  retrieved: string;
  url: string;
  /** The backend's own word for whether the page behind the row was read.
   *  Render as sent when it is not a word this build knows. */
  verification: string;
  /** true for the labelled fixtures served when the feature is off. */
  is_sample: boolean;
}

/** The outcome of a search. FOUR states, and they mean different things.
 *
 *   - `enabled` false with a `phrase`: the feature is off and `rows` are the
 *     labelled samples;
 *   - `enabled` true with `phrase` null: nothing safe survived the scrub, so
 *     no search was attempted. NOT a failure - the same state the preview
 *     reports, so both screens can use one form of words;
 *   - `failure` non-null: tiers were attempted and EVERY ONE failed. `rows` is
 *     empty and samples are never substituted - a fixture served after a
 *     failed live search is the one behaviour that turns this feature into a
 *     liability;
 *   - otherwise `rows` are real, and an empty `rows` is a real answer.
 *
 *  `tiers_attempted` against `tiers_answered` is what makes a dropped tier
 *  visible. Unconfigured tiers are in NEITHER: nothing was sent to them. */
export interface MarketSearchResult {
  enabled: boolean;
  phrase: string | null;
  rows: MarketRow[];
  /** Tiers actually CONTACTED. Never includes an unconfigured tier, so
   *  "tried and did not answer" stays a true sentence. */
  tiers_attempted: string[];
  tiers_answered: string[];
  tiers_unconfigured: string[];
  tier_labels: Record<string, string>;
  /** Set ONLY when every attempted tier failed. */
  failure: string | null;
}

// ------------------------------------------------------------------ reports

export interface ReportDocumentRow {
  document_id: string;
  /** as named when the report was generated */
  filename: string;
  sha256_prefix: string;
  /** Always null: no such column exists on documents. Render as "not
   *  recorded", never invent one. */
  revision: string | null;
  approval_status: string | null;
  passages_cited: number;
  text_source: "extracted" | "recognised" | "mixed" | null;
}

/** A report as a client may see it. `stored_path` is never serialised. */
export interface ReportRecord {
  id: string;
  question: string | null;
  resolved_question: string | null;
  created_at: string;
  page_count: number;
  size_bytes: number;
  /** Hash of the PDF bytes. Proves the stored file is the one issued. NOT a
   *  reproducibility hash: a re-render on another build differs in producer
   *  string and ID array with identical content. */
  report_sha256: string;
  /** null under auth_mode="disabled" - there is no user to attribute it to */
  owner_username: string | null;
  documents: ReportDocumentRow[];
  /** Named on page 1 of the PDF as not included. */
  not_implemented_sections: string[];
}

export interface ReportList {
  reports: ReportRecord[];
  /** Reports hidden because a cited document left the caller's scope. THAT
   *  something is hidden, never WHAT. */
  suppressed_count: number;
}

export interface ReportVerification {
  report_id: string;
  snapshot_intact: boolean;
  file_intact: boolean;
  /** How the cited documents differ NOW from when the report was generated.
   *  Reported, never silently resolved. */
  evidence_drift: string[];
}

export interface GenerateReport {
  message_id: string;
}

export interface AnswerResult {
  question: string;
  answer_type: AnswerType;
  /** null whenever answer_type is insufficient_evidence or model_unavailable */
  answer: string | null;
  /** why there is no answer */
  reason: string | null;
  /** extract only: the quoted passage. `answer` is this passage's text verbatim. */
  passage: AnswerPassage | null;
  /** extract only: the runners-up */
  supporting: AnswerPassage[];
  /** generated / refusals: the sources supplied to the model, or considered */
  passages: AnswerPassage[];
  /** 1-based indices into `passages`, validated server-side */
  cited: number[];
  /** citations the model invented; stripped from `answer` before it was returned */
  rejected_citations: number[];
  /** The generation stopped because it hit the output-token cap, not because
   *  the model finished.
   *
   *  THE UI MUST SAY SO. An answer that simply stops reads as broken whatever
   *  its citations say, and the reader cannot otherwise distinguish "the model
   *  finished", "it ran out of budget" and "it crashed". A half-written
   *  citation marker at the end - `[S2` with no closing bracket - has already
   *  been stripped server-side, because a broken citation is worse than a
   *  missing one and looks like a defect in the citation system rather than a
   *  length limit. */
  truncated: boolean;
  /** guidance only: which kind of non-question this was */
  input_kind: string | null;
  /** Sources trimmed or dropped so the evidence would fit the context
   *  window. Empty in the ordinary case: prose fits comfortably. */
  evidence_removed: EvidenceRemoved[];
  /** Report-only. Null for a refusal, and null for an answer produced without
   *  the cross-encoder (nothing was scored for credibility). */
  coverage: Coverage | null;
  /** guidance only: real questions drawn from the loaded documents */
  examples: string[];
  retrieval_mode: string;
  reranked: boolean;
  candidates_considered: number;
  model: string | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  seconds: number;
  timings: Record<string, number>;
}

// ---------- chat ----------
// Tier 2 takes ~50s on this hardware and is not streamed. The Explain button
// must warn before it is pressed rather than leaving the reader watching a
// spinner with no idea how long it will run.

export interface Conversation {
  id: string;
  title: string;
  document_id: string | null;  // set when the conversation is scoped to one doc
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationSummary extends Conversation {
  first_question: string | null;
}

export interface ConversationList {
  total: number;
  limit: number;
  offset: number;
  conversations: ConversationSummary[];
}

export interface Message {
  id: string;
  conversation_id: string;
  ordinal: number;
  role: "user" | "assistant";
  /** the question as typed, or the answer. null on a refusal. */
  text: string | null;
  /** user rows: what retrieval actually ran, after follow-up resolution */
  resolved_question: string | null;
  /** user rows: terms carried in from earlier questions. Show these - the
   *  reader must never have their question silently rewritten. */
  carried_terms: string[];
  /** assistant rows */
  answer_type: AnswerType | null;
  reason: string | null;
  /** assistant rows: the extract answer this Tier 2 answer explains */
  explains_id: string | null;
  /** assistant rows: passages and citations, so reopening restores the panel */
  payload: Partial<AnswerResult> | null;
  created_at: string;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: Message[];
}

export interface AskRequest {
  /** A client-chosen id for polling `/api/progress/{id}` while this runs.
   *  Optional: without one the backend reports nothing and behaves as before. */
  progress_id?: string | null;
  question: string;
  tier: AnswerTier;
  document_id?: string | null;
  limit?: number;
  /** upgrade this assistant message to Tier 2 instead of asking anew. The
   *  reader pressing Explain is not asking a new question. */
  explain_of?: string | null;
}

export interface AskResult extends AnswerResult {
  conversation: Conversation;
  user_message: Message;
  assistant_message: Message;
  /** what retrieval ran; differs from `question` when a follow-up resolved */
  resolved_question: string;
  carried_terms: string[];
}

// ---------- dashboard ----------
// Every field here is measured. A value that has not been measured is null,
// and the screen is required to say so - never a zero standing in for
// unknown, never a last-known figure presented as current.

export interface CorpusMetrics {
  documents: number;
  by_status: Partial<Record<DocStatus, number>>;
  /** from the PDF manifest */
  pages_declared: number;
  /** actually extracted; differs from declared while processing */
  pages_extracted: number;
  chunks_total: number;
  /** what search can actually see */
  chunks_retrievable: number;
  chunks_excluded: number;
  chunks_indexed_keyword: number;
  chunks_embedded: number;
}

export interface StageThroughput {
  unit: string;
  samples: number;
  median: number;
  best: number;
  items_total: number;
  seconds_total: number;
}

export interface RetrievalLatency {
  unit: string;
  samples: number;
  p50: number | null;
  p95: number | null;
  worst: number;
}

export interface SystemMetrics {
  /** Since the previous call; on a 15s refresh that is a 15s average.
   *  null on the very first reading, which has no prior call to measure
   *  against - psutil returns exactly 0.0 there, and showing that would put
   *  "CPU 0%" on screen as a fact. */
  cpu_percent_since_last_call: number | null;
  /** The span the CPU figure actually covers. NOT the refresh interval - every
   *  caller of /api/metrics resets the window, so two open tabs halve it. null
   *  ONLY on the very first reading, which has no prior call to measure
   *  against; present but with a null percentage when the window was too short
   *  to average. The screen states this rather than the refresh interval,
   *  which it used to claim and which was often wrong. */
  cpu_window_seconds: number | null;
  cpu_logical_cores: number | null;
  cpu_physical_cores: number | null;
  ram_total_bytes: number;
  ram_used_bytes: number;
  /** Stated rather than left to be derived. The tile showed "15 GB / 16 GB"
   *  while the low-memory alert said "0.6 GB free": the same measurement,
   *  rounded, with the reader asked to subtract. */
  ram_free_bytes: number;
  ram_percent: number;
  process_rss_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
  disk_percent: number | null;
  data_dir_bytes: number;
}

export interface ModelStatus {
  embed_model: string;
  embed_model_present: boolean;
  reranker_model: string;
  reranker_present: boolean;
  answer_model: string;
  /** is Ollama running at all - "configured" and "running" are different */
  answer_model_reachable: boolean;
  answer_model_installed?: boolean;
  /** resident, so Tier 2 skips the cold load */
  answer_model_loaded: boolean;
  ollama_error: string | null;
}

export interface DocumentFailure {
  id: string;
  filename: string;
  error_code: string | null;
  error_message: string | null;
  uploaded_at: string;
}

export interface JobMetrics {
  by_state: Record<string, number>;
  running: number;
  failed_documents: number;
  failures: DocumentFailure[];
}

export interface MetricWarning {
  severity: "info" | "warning" | "error";
  code: string;
  document_id: string | null;
  message: string;
}

export interface Metrics {
  at: string;
  refresh_seconds: number;
  /** True when `corpus` and `exclusions` count the WHOLE corpus rather than
   *  only the documents this caller may read. An admin gets corpus-wide
   *  figures; everyone else gets their own. The screen MUST say which it is
   *  showing - a count with no stated boundary reads as total. */
  corpus_wide: boolean;
  corpus: CorpusMetrics;
  exclusions: ExclusionSummary[];
  jobs: JobMetrics;
  /** null for a stage that has never run measurably */
  throughput: Record<string, StageThroughput | null>;
  /** null until a question has actually been asked */
  retrieval: RetrievalLatency | null;
  /** The machine's own CPU, memory and disk. WITHHELD from any caller without
   *  the admin capability (#77) - host specifications are not a document, so
   *  document scoping could never have removed them.
   *
   *  `null`, not merely absent, and that is measured rather than assumed. The
   *  route declares `system: SystemMetrics | None` and sets no
   *  `response_model_exclude_none`, so Pydantic serialises `"system": null`
   *  even where the handler's dict omits the key - see the comment in
   *  backend/tests/test_metrics_host_telemetry.py, which explains why buying
   *  true key-absence was rejected: it would also strip `retrieval`,
   *  `cpu_percent_since_last_call`, `disk_percent` and `ollama_error`, every
   *  one of which the dashboard reads with an explicit null check and renders
   *  as "not measured yet".
   *
   *  This type said `SystemMetrics | undefined` and so could not describe the
   *  response the backend actually sends. Optional AND nullable: absent and
   *  null both mean withheld, and the renderer must treat them alike.
   *
   *  Render the block only when it is present and non-null; NEVER substitute
   *  zeros for a withheld block, which would state measurements that are
   *  false. */
  system?: SystemMetrics | null;
  models: ModelStatus;
  worker: WorkerStatus;
  warnings: MetricWarning[];
}

// ---------- errors ----------

/** `internal` is reserved for genuine unexpected failure. A caller's mistake
 *  never reports as internal. Error bodies never carry a traceback or a path. */
export interface ApiError {
  code:
    // caller's fault
    | "not_found"
    | "invalid_parameter"
    | "unknown_parameter"
    | "confirm_required"
    // authentication. These MUST exist here as well as in errors.py: the
    // union is compiler-enforced only for the codes it lists, so adding them
    // to the backend alone compiles cleanly and fails at runtime.
    | "unauthenticated"
    | "invalid_credentials"
    | "rate_limited"
    // the upload was not acceptable
    | "not_pdf"
    | "encrypted_pdf"
    | "too_large"
    | "duplicate"
    // processing failed for an identifiable reason
    | "extract_failed"
    | "chunk_failed"
    | "embed_failed"
    | "model_unavailable"
    | "disk_full"
    | "no_searchable_content"
    // genuine, unexpected internal failure
    | "internal";
  message: string;
  document_id?: string | null;
  stage?: string | null;
  at?: string | null;
}

// ---------- request/response envelopes ----------

/** UI fetch state, used by every view. */
export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "disconnected" }
  | { state: "ready"; data: T };


/* ============================================================ classification
 *
 * THREE TYPES, ONE DISCIPLINE AXIS, AND A FILTER THAT CAN ONLY NARROW.
 *
 * Mirrors `backend/app/schemas.py` field for field. The market panel taught
 * this file's lesson the expensive way: the backend renamed `payload` to
 * `payloads`, tsc passed, 23 tests passed, and the one dialog the feature
 * exists for rendered `undefined`. So these names are copied from the Python,
 * not invented here, and a rename on either side must break the build.
 *
 * CLASSIFICATION IS NOT ACCESS CONTROL. `DocumentClassification.discipline`
 * says what a document IS ABOUT. The grants in `Document.disciplines` say who
 * MAY READ IT. They are different tables and the second one is the only one
 * that decides anything. See `backend/app/classification.py`.
 */

/** A subject row from the register. Carried because the backend sends it;
 *  the current screens deliberately do not surface subjects. */
export interface SubjectRow {
  id: string;
  name: string;
  kind: "system" | "facility" | "project_wide";
}

export interface ClassificationVocabulary {
  /** Null when no register has been loaded. NOT a version number to display
   *  as "v1" - it is whatever revision string the register carried. */
  register_revision: string | null;
  /** The three document types, in the register's own order. NEVER hardcode
   *  this list in a component: a register with different types must not
   *  render a filter for types that do not exist. */
  types: string[];
  disciplines: string[];
  subjects: SubjectRow[];
  /** Documents this caller can read that have no confirmed classification.
   *  SCOPED - it is a statement about documents. The vocabulary above is not
   *  scoped, because a discipline name is project structure, not evidence
   *  that a document exists. */
  needs_classification: number;
}

export interface DocumentSubject {
  id: string;
  name: string;
  kind: string;
  suggested_by: string;
  confirmed_by: string | null;
}

/** How a classification got there. These names are copied from the Python
 *  (`SOURCE_REGISTER` / `SOURCE_PATTERN` / `SOURCE_NONE`, `classification.py`),
 *  not invented here, so a rename on either side must break the build.
 *  `register` is a title match against the client's own register and is the
 *  only tier that is client-authoritative; `pattern` is a filename/content
 *  guess and must render AS a guess until a person confirms it. `none` means
 *  nothing suggested anything. */
export type ClassificationSource = "register" | "pattern" | "none";

export interface DocumentClassification {
  document_id: string;
  /** NULL IS AN ANSWER, not a missing value: "nothing has classified this
   *  document". It renders as "awaiting a type", never as a guessed type and
   *  never as an empty chip. */
  doc_type: string | null;
  discipline: string | null;
  doc_class: string | null;
  register_id: string | null;
  suggested_by: ClassificationSource;
  confirmed_by: string | null;
  confirmed_at: string | null;
  /** THE ONLY FIELD THAT LICENSES A PLAIN CHIP. False means a human has not
   *  agreed with the machine yet. */
  confirmed: boolean;
  subjects: DocumentSubject[];
}

export interface ClassificationUpdate {
  doc_type?: string | null;
  discipline?: string | null;
  doc_class?: string | null;
  subject_ids?: string[];
}

export interface CoverageByType {
  type: string;
  /** NULL when no register is loaded. Null renders as nothing - never as 0,
   *  which would read as "the register says none exist". */
  in_register: number | null;
  uploaded: number;
  unconfirmed: number;
}

export interface CoverageByDiscipline {
  discipline: string;
  in_register: number | null;
  uploaded: number;
  unconfirmed: number;
}

export interface CoverageBySubject {
  subject: string;
  kind: string;
  uploaded: number;
  disciplines_spanned: number;
}

export interface ClassificationCoverage {
  register_loaded: boolean;
  register_revision: string | null;
  by_type: CoverageByType[];
  by_discipline: CoverageByDiscipline[];
  by_subject: CoverageBySubject[];
  needs_classification: number;
  /** True only for a caller holding the admin capability. When true the
   *  counts cover every document; when false they cover this caller's
   *  grants. A count with no stated boundary reads as total, so the screen
   *  showing these MUST say which it is. */
  corpus_wide: boolean;
}

/** What the caller asks to be narrowed to. EMPTY ARRAYS MEAN "DO NOT FILTER"
 *  on that axis - not "match nothing". */
export interface ClassificationScope {
  types?: string[];
  disciplines?: string[];
  subject_ids?: string[];
}

/** What the backend actually applied, echoed back. The screen renders the
 *  count from HERE and never from its own arithmetic: the frontend does not
 *  know the intersection with the caller's grants, and a locally computed
 *  "62 of 96" was wrong in exactly the direction that hides a missing
 *  document. */
export interface AppliedScope {
  applied: boolean;
  types: string[];
  disciplines: string[];
  subject_ids: string[];
  documents_in_scope: number;
}
