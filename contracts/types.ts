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

/** Tier 1 = quoted source, no LLM. Tier 2 = generated prose. Never conflate. */
export type AnswerTier = "passage" | "generated";

export interface PassageAnswer {
  tier: "passage";
  passage: Passage;
  latency_ms: number;
}

export interface GeneratedAnswer {
  tier: "generated";
  text: string;
  /** 1-based indices into `sources`; validated server-side before returning */
  cited: number[];
  sources: Passage[];
  model: string;
  latency_ms: number;
}

export interface InsufficientEvidence {
  tier: "insufficient";
  reason: "no_matches" | "low_confidence" | "conflicting_sources";
  /** what was retrieved, so the user can judge for themselves */
  considered: Passage[];
  latency_ms: number;
}

export type AnswerResult = PassageAnswer | GeneratedAnswer | InsufficientEvidence;

// ---------- streaming (Tier 2) ----------
// Sources arrive first and render immediately; text streams after.

export type AnswerEvent =
  | { type: "sources"; sources: Passage[] }
  | { type: "token"; text: string }
  | { type: "done"; cited: number[]; model: string; latency_ms: number }
  | { type: "insufficient"; reason: InsufficientEvidence["reason"] }
  | { type: "error"; error: ApiError };

// ---------- chat ----------

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  text: string;
  /** present on assistant messages only */
  answer: AnswerResult | null;
  created_at: string;
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

export interface AskRequest {
  question: string;
  conversation_id: string | null;
  /** "passage" is the default; "generated" is the explicit Explain action */
  tier: AnswerTier;
}

/** UI fetch state, used by every view. */
export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "disconnected" }
  | { state: "ready"; data: T };
