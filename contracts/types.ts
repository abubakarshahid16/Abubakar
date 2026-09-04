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
  needs_ocr_pages: number;   // detected only; OCR is not implemented
  /** pages whose mathematics did not survive extraction; see the page image */
  equation_pages: number;
  error: ApiError | null;
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
  page_start: number | null;
  page_end: number | null;
  chunk_id: string | null;
  rule: string;
  reason: string | null;
  text_length: number;
  text_sample: string;
}

export interface ExclusionsResponse {
  total: number;
  summary: { scope: string; rule: string; count: number; characters_dropped: number }[];
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
  | "model_unavailable";

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
  score: number;
  identifier_hits: string[];
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

export interface DashboardStats {
  documents: number;
  pages: number;
  chunks: number;
  jobs_running: number;
  jobs_failed: number;
  /** null until measured - never show a placeholder number */
  embed_chunks_per_sec: number | null;
  retrieval_p50_ms: number | null;
  retrieval_p95_ms: number | null;
  cpu_percent: number;
  ram_used_mb: number;
  ram_total_mb: number;
  disk_free_gb: number;
  ollama_ready: boolean;
  embedder_ready: boolean;
  ingestion_paused: boolean;
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
