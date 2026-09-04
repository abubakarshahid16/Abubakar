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
  /** guidance only: which kind of non-question this was */
  input_kind: string | null;
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
