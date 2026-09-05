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
  document: DocumentRecord;
  job_id: string;
  duplicate_of: string | null; // set when sha256 already exists; no job started
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
  | "guidance";

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
}

// ------------------------------------------------------------------- market

/** How a finding was checked. The full vocabulary, because a UI must be able
 *  to render each state - but see `MarketFinding.verification`: this build
 *  can only ever produce the last one. */
export type MarketVerification = "source_read" | "snippet_only" | "source_not_verified";

/** An ILLUSTRATIVE row. There is no provider and this machine is offline.
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
  corpus: CorpusMetrics;
  exclusions: ExclusionSummary[];
  jobs: JobMetrics;
  /** null for a stage that has never run measurably */
  throughput: Record<string, StageThroughput | null>;
  /** null until a question has actually been asked */
  retrieval: RetrievalLatency | null;
  system: SystemMetrics;
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
