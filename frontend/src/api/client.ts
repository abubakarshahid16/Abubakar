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
    let error: ApiError = { code: "internal", message: `HTTP ${response.status}` };
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
  pageImageUrl: (id: string, page: number) =>
    `${BASE}/documents/${encodeURIComponent(id)}/pages/${page}/image`,
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
