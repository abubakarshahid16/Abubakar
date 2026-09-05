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
  DeletedConversation,
  DeletedDocument,
  ApiError,
  AskRequest,
  AskResult,
  ChunkPage,
  Conversation,
  ConversationDetail,
  ConversationList,
  DocumentRecord,
  AuthStatus,
  ExclusionsResponse,
  LoginResult,
  Metrics,
  PagesResponse,
} from "../types/api";

/** The unauthenticated route, and the only one. It answers "is the service up"
 *  and "are the models present" and nothing else.
 *
 *  It used to return document counts, the exact answer-model name and version,
 *  free-text last_error and stalled_reasons, and current_document - a real
 *  document id that the UI joined against the document list to display a
 *  filename. An unauthenticated caller could learn that a specific document
 *  existed and was being processed.
 *
 *  The full worker status lives on /api/metrics, which is scoped. `alive` and
 *  `stalled` remain here because a client has to distinguish "backend down"
 *  from "backend up but stuck", and neither fact is about anybody's
 *  documents. */
export interface HealthWorker {
  alive: boolean;
  stalled: boolean;
  /** work is under way. WHETHER, never WHICH - see the note above. */
  busy: boolean;
}

export interface Health {
  ok: boolean;
  embed_model_present: boolean;
  /** whether an answer model is configured, NOT which one */
  answer_model_present: boolean;
  ingestion: HealthWorker;
}

export type Result<T> =
  | { ok: true; data: T }
  | { ok: false; disconnected: true; error: ApiError }
  | { ok: false; disconnected: false; error: ApiError };

const BASE = "/api";

/** Statuses that mean nothing served the request at all. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** The bearer token, in memory only.
 *
 *  Never localStorage: it outlives the tab, and every XSS then becomes
 *  credential theft rather than a session-length nuisance. The cost is that a
 *  reload logs you out, which the login screen states rather than leaving the
 *  reader to discover.
 */
let token: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export function setToken(next: string | null) {
  token = next;
}

export function isSignedIn() {
  return token !== null;
}

/** Called when the backend says the token is no good. No auto-retry, no
 *  refresh, no redirect loop - the screen changes and the reader decides. */
export function onSignedOut(fn: (() => void) | null) {
  onUnauthenticated = fn;
}

/** What to tell a reader, in words they can act on. */
function humanMessage(status: number): string {
  if (status === 401) {
    // Split from 403 deliberately. The old shared message told a logged-out
    // user to check the backend's settings, which sends them to inspect a
    // server that is working perfectly.
    return "You are not signed in, or your session has expired. Sign in to continue.";
  }
  if (status === 403) {
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

/**
 * A body that parsed as JSON but is not the shape the caller will index into.
 *
 * ONE GUARD, AT THE BOUNDARY. The alternative is an Array.isArray check at
 * every call site, and that is exactly how this defect came back: IngestionView
 * carried a guard and a comment explaining it, while DocumentsView and both
 * list reads in ChatView indexed straight into whatever arrived. Four call
 * sites is four chances to forget, and the fifth screen someone adds will
 * forget too.
 *
 * A malformed body becomes an ordinary ApiError, so the views' existing error
 * state renders it instead of a white screen. The check lives here because
 * this is the only place every response passes through.
 */
export type ShapeCheck = (body: unknown) => boolean;

export const isArrayBody: ShapeCheck = (b) => Array.isArray(b);

export const hasArrayField =
  (field: string): ShapeCheck =>
  (b) =>
    typeof b === "object" &&
    b !== null &&
    Array.isArray((b as Record<string, unknown>)[field]);

export const auth = {
  login: (email: string, password: string) =>
    request<LoginResult>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<AuthStatus>("/auth/me"),
};

async function request<T>(
  path: string,
  init?: RequestInit,
  expect?: ShapeCheck,
): Promise<Result<T>> {
  let response: Response;
  try {
    // The single fetch in the module, which is why the token can be attached
    // in exactly one place - the module's own principle, stated at the top.
    const headers = new Headers(init?.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    response = await fetch(`${BASE}${path}`, { ...init, headers });
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

    // The token is no good - expired, revoked, or the account deactivated.
    // Clear it and tell the app once. No auto-retry and no refresh flow:
    // there is no refresh token by design, and a silent retry against a
    // revoked session is a loop that hides the reason from the reader.
    if (response.status === 401) {
      token = null;
      onUnauthenticated?.();
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

  const body = await response.json();
  if (expect && !expect(body)) {
    // Never a white screen. The reader gets the same card any other API
    // failure produces, and the console keeps the detail for whoever is
    // debugging the server.
    // eslint-disable-next-line no-console
    console.error(`Malformed response from ${path}`, body);
    return {
      ok: false,
      disconnected: false,
      error: {
        code: "internal",
        message:
          "The server sent a response this screen could not read. " +
          "Nothing has been lost - try again, and check the API log.",
      },
    };
  }
  return { ok: true, data: body as T };
}

export const api = {
  health: () => request<Health>("/health"),
  metrics: () => request<Metrics>("/metrics"),
  documents: () =>
    request<DocumentRecord[]>("/documents", undefined, isArrayBody),
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
    request<DeletedDocument>(`/documents/${encodeURIComponent(id)}?confirm=true`, {
      method: "DELETE",
    }),

  // ---------- conversations ----------
  conversations: (limit = 20) =>
    request<ConversationList>(`/conversations?limit=${limit}`, undefined,
      hasArrayField("conversations")),
  conversation: (id: string) =>
    request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`,
      undefined, hasArrayField("messages")),
  newConversation: (documentId?: string | null) =>
    request<Conversation>("/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId ?? null }),
    }),
  deleteConversation: (id: string) =>
    request<DeletedConversation>(`/conversations/${encodeURIComponent(id)}?confirm=true`, {
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
