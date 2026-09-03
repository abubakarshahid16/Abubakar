// Shared API types. Hand-written, source of truth for the UI.
// Backend mirrors these in Pydantic models.

// ---------- documents ----------

export type DocStatus =
  | "queued"
  | "extracting"
  | "chunking"
  | "embedding"
  | "indexing"
  | "partially_searchable"
  | "ready"
  | "failed";

/** A doc is only browsable-as-complete when status === "ready". */
export const isReady = (d: DocumentRecord) => d.status === "ready";

export interface DocumentRecord {
  id: string;
  filename: string;          // sanitised; display only
  sha256: string;
  size_bytes: number;
  page_count: number | null; // null until the manifest is read
  pages_done: number;
  chunk_count: number;
  status: DocStatus;
  needs_ocr_pages: number;   // detected only; OCR is not implemented
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

export interface ApiError {
  code:
    | "not_pdf"
    | "encrypted_pdf"
    | "too_large"
    | "disk_full"
    | "duplicate"
    | "extract_failed"
    | "embed_failed"
    | "model_unavailable"
    | "not_found"
    | "internal";
  message: string;
  detail?: string;
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
