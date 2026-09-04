/**
 * API client.
 *
 * Every call goes through here so two rules hold everywhere:
 *  - a failure is a typed result, never a thrown string rendered raw
 *  - a network failure is distinguishable from an API error, because the UI
 *    must say "the backend is not running" rather than spin or show stale
 *    numbers as if they were live
 */
import type {
  ApiError,
  AskRequest,
  AskResult,
  ChunkPage,
  Conversation,
  ConversationDetail,
  ConversationList,
  DocumentRecord,
  ExclusionsResponse,
  Metrics,
  PagesResponse,
  WorkerStatus,
} from "../types/api";

export interface Health {
  ok: boolean;
  embed_model_present: boolean;
  answer_model: string;
  ingestion: WorkerStatus;
}

export type Result<T> =
  | { ok: true; data: T }
  | { ok: false; disconnected: true; error: ApiError }
  | { ok: false; disconnected: false; error: ApiError };

const BASE = "/api";

/** Statuses that mean nothing served the request at all. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** What to tell a reader, in words they can act on. */
function humanMessage(status: number): string {
  if (status === 401 || status === 403) {
    return "This action was refused. Check whether the backend was started with different settings.";
  }
  if (status === 404) return "That is not something the backend knows about.";
  if (status === 413) return "That file is larger than the backend accepts.";
  if (status === 422) return "The backend rejected the request as malformed.";
  if (status === 429) return "Too many requests at once. Wait a moment and try again.";
  if (status >= 500) {
    return "The backend hit an unexpected error handling this. The details are in its log.";
  }
  return "The backend could not complete this request.";
}

function disconnected(detail: string): Result<never> {
  return {
    ok: false,
    disconnected: true,
    error: {
      code: "internal",
      message: `Cannot reach the backend. ${detail}`,
    },
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (e) {
    // fetch only rejects on a network-level failure - the server is down
    return disconnected(e instanceof Error ? e.message : "Network request failed.");
  }

  if (!response.ok) {
    // A gateway status means nothing served the request - the backend is not
    // reachable, which is the same condition as a network failure and must
    // read as one. Reported as an API error it produced an amber "backend is
    // not running" banner and a red "HTTP 502" card on screen together.
    if (GATEWAY_STATUSES.has(response.status)) {
      return disconnected("Nothing answered on the API port.");
    }

    let error: ApiError = {
      code: "internal",
      // Never a bare status code on a client-facing screen. A reader cannot
      // act on "HTTP 500" and should not have to.
      message: humanMessage(response.status),
    };
    try {
      const body = await response.json();
      // FastAPI wraps HTTPException detail; both shapes are handled
      const raw = body?.detail ?? body;
      if (raw && typeof raw === "object" && "code" in raw) error = raw as ApiError;
    } catch {
      /* keep the fallback */
    }
    return { ok: false, disconnected: false, error };
  }

  return { ok: true, data: (await response.json()) as T };
}

export const api = {
  health: () => request<Health>("/health"),
  metrics: () => request<Metrics>("/metrics"),
  documents: () => request<DocumentRecord[]>("/documents"),
  document: (id: string) => request<DocumentRecord>(`/documents/${encodeURIComponent(id)}`),
  chunks: (id: string, opts: { limit?: number; offset?: number; retrievable?: string } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    if (opts.retrievable) q.set("retrievable", opts.retrievable);
    return request<ChunkPage>(`/documents/${encodeURIComponent(id)}/chunks?${q}`);
  },
  pages: (id: string, opts: { limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    return request<PagesResponse>(`/documents/${encodeURIComponent(id)}/pages?${q}`);
  },
  excluded: (id: string, opts: { limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    return request<ExclusionsResponse>(`/documents/${encodeURIComponent(id)}/excluded?${q}`);
  },
  /** The plain rendered page. */
  pageImageUrl: (id: string, page: number) =>
    `${BASE}/documents/${encodeURIComponent(id)}/pages/${page}/image`,
  /** The rendered page with the answering sentence BOXED on the image.
   *
   *  The box is drawn server-side, in PDF coordinate space where the
   *  rectangles were measured. Overlaying in CSS would mean reproducing the
   *  page-to-image transform here as well, and any drift between the two
   *  draws the box slightly off - on a dense specification table, slightly
   *  off is the wrong row.
   *
   *  When the sentence cannot be located the page comes back with no box and
   *  `X-Answer-Located: 0`. */
  pageImageWithAnswerUrl: (
    id: string,
    page: number,
    chunkId: string,
    question: string,
  ) => {
    const q = new URLSearchParams({ chunk_id: chunkId, q: question });
    return `${BASE}/documents/${encodeURIComponent(id)}/pages/${page}/image?${q}`;
  },
  extract: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/extract`, { method: "POST" }),
  chunk: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/chunk`, { method: "POST" }),
  embed: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/embed`, { method: "POST" }),
  remove: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}?confirm=true`, { method: "DELETE" }),

  // ---------- conversations ----------
  conversations: (limit = 20) => request<ConversationList>(`/conversations?limit=${limit}`),
  conversation: (id: string) =>
    request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),
  newConversation: (documentId?: string | null) =>
    request<Conversation>("/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId ?? null }),
    }),
  deleteConversation: (id: string) =>
    request<unknown>(`/conversations/${encodeURIComponent(id)}?confirm=true`, {
      method: "DELETE",
    }),
  /** Tier 2 is not streamed and takes ~50s on this hardware, so callers must
   *  show elapsed time rather than an indefinite spinner. */
  ask: (id: string, body: Partial<AskRequest>) =>
    request<AskResult>(`/conversations/${encodeURIComponent(id)}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: "", tier: "extract", ...body }),
    }),
};
