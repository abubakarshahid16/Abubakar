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
  AnalysisGapsResult,
  AnalysisRecommendationResult,
  AnalysisRequest,
  AnalysisSummaryResult,
  LoginResult,
  MarketFindings,
  MarketPreview,
  MarketQueryPreview,
  MarketSearchRequest,
  MarketSearchResult,
  Progress,
  MarketQueryRequest,
  Metrics,
  ReportList,
  ReportRecord,
  ReportVerification,
  PagesResponse,
  ClassificationVocabulary,
  ClassificationCoverage,
  ClassificationUpdate,
  DocumentClassification,
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

/** The watched folder: a host directory the backend scans on an interval and
 *  ingests from, so a team can drop PDFs in rather than upload through the app.
 *
 *  `folder_name` is the folder's own name, never a path, and is null for a
 *  non-admin caller. A screen must render nothing in its place rather than a
 *  placeholder that implies a value was withheld or, worse, that there is none.
 *
 *  The feature being OFF is a normal state, not an error: `enabled` false with
 *  every other field empty. */
export type WatchOutcome = "ingested" | "duplicate" | "failed";

export interface WatchEvent {
  filename: string;
  outcome: WatchOutcome;
  /** ISO-8601 UTC */
  at: string;
  /** why it failed, when it did. null otherwise. */
  detail: string | null;
}

export interface WatchStatus {
  enabled: boolean;
  /** The watched folder's OWN NAME - its last path segment, never a path.
   *
   *  `D:\\project\\data\\watch-inbox` and `\\\\fileserver\\engineering\\inbox` arrive
   *  here as "watch-inbox" and "inbox". The route used to publish the full
   *  host path; under AUTH_MODE=disabled every caller reads as unrestricted,
   *  so the admin gate alone did not hold and the value itself was narrowed.
   *
   *  Still null for a non-admin caller, and null when the configured value has
   *  no final segment. A screen renders nothing in its place - and must not
   *  word it as though a location were being shown. */
  folder_name: string | null;
  /** ISO-8601 UTC, or null when no scan has run. */
  last_scan_at: string | null;
  interval_seconds: number | null;
  /** Did the MOST RECENT scan find the folder readable?
   *
   *  null means no scan has completed yet - never false, which would assert a
   *  failure nobody has observed. Back to null when the feature is turned off.
   *  A screen must render NOTHING for null: "unknown" is a claim of its own. */
  reachable: boolean | null;
  /** A short sentence about the most recent SCAN-LEVEL failure - the folder is
   *  missing, or unreadable. null when the last scan was fine.
   *
   *  A single corrupt PDF is a per-file `failed` event in `recent` and does not
   *  set this. Built from the exception class, never from OS error text, so it
   *  carries no host path and is safe to show a non-admin caller. */
  last_error: string | null;
  /** the newest ten, newest first */
  recent: WatchEvent[];
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

export const analysis = {
  summary: (body: AnalysisRequest) =>
    request<AnalysisSummaryResult>("/analysis/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  recommendations: (body: AnalysisRequest) =>
    request<AnalysisRecommendationResult>("/analysis/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  gaps: (body: AnalysisRequest) =>
    request<AnalysisGapsResult>("/analysis/gaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

// The market preview/search contract now lives in contracts/types.ts, which
// this file's own header calls the single source of truth. It was declared
// HERE, and that is exactly how the drift happened: the backend renamed
// `payload` to `payloads`, `tsc` passed, all 23 panel tests passed, and the
// confirmation dialog rendered `undefined` in the one place the whole panel
// exists to fill. Re-exported so existing imports keep working.
export type {
  ClassificationVocabulary,
  ClassificationCoverage,
  ClassificationScope,
  ClassificationSource,
  ClassificationUpdate,
  DocumentClassification,
  AppliedScope,
  CoverageByType,
  SubjectRow,
} from "../types/api";

export type {
  MarketProviderLabel,
  MarketOutboundPayload,
  MarketPreviewPayload,
  MarketPreview,
  MarketRow,
  MarketSearchRequest,
  MarketSearchResult,
} from "../types/api";

export const market = {
  findings: () => request<MarketFindings>("/market/findings"),
  /** Builds the object that WOULD be sent. Nothing is sent. */
  previewQuery: (body: MarketQueryRequest) =>
    request<MarketQueryPreview>("/market/preview-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  /** The exact outbound payloads, one per tier, and the scrubbed phrase. NO
   *  egress, so this is safe to call on every preview.
   *
   *  THE SCOPE FIELDS ARE PASSED, and they have to be. `country` and
   *  `freshness_days` appear in every payload a search sends, so a preview
   *  called without them returns payloads that differ from what would leave -
   *  which is how the panel ended up disclosing them on a separate line
   *  attributed to itself. Sent here, the backend's own payloads carry them
   *  and the dialog needs no footnote. */
  preview: (phrase: string, scope?: { country?: string | null; freshness_days?: number | null }) => {
    const params = new URLSearchParams({ phrase });
    if (scope?.country != null) params.set("country", scope.country);
    if (scope?.freshness_days != null) {
      params.set("freshness_days", String(scope.freshness_days));
    }
    return request<MarketPreview>(`/market/preview?${params.toString()}`);
  },
  /** THE ONLY CALL IN THIS MODULE THAT CAN LEAVE THE MACHINE. It must be
   *  reachable from an explicit click and from nothing else - no debounce, no
   *  submit-on-enter, no blur handler.
   *
   *  Guarded on `rows` like the other list-bearing reads: a body without it
   *  becomes an ordinary ApiError, so the panel renders its own failure state
   *  rather than crashing at the map or, worse, rendering nothing and leaving
   *  stale rows on screen. */
  search: (body: MarketSearchRequest) =>
    request<MarketSearchResult>(
      "/market/search",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      hasArrayField("rows"),
    ),
};

/* ------------------------------------------------------------ classification
 *
 * Four calls. Two reads that every screen shares, one read per document, and
 * the one write - which the backend gates on the ADMIN capability and answers
 * 404, not 403, to anyone else. A wrong type misroutes searches for everyone,
 * not just for the person who set it, so it needs a role that answers for
 * everyone. `backend/app/main.py::put_document_classification`.
 */
export const classification = {
  /** The filter vocabulary. `types` comes from the register, so a component
   *  MUST render this list rather than a hardcoded three. */
  vocabulary: () =>
    request<ClassificationVocabulary>("/classification/vocabulary"),
  /** Counts per axis, scoped. This is how a screen gets per-type counts
   *  WITHOUT asking each document its type: one request, no N+1. */
  coverage: () => request<ClassificationCoverage>("/classification/coverage"),
  /** One document's classification. In scope but never classified is a 200
   *  with every field null - not a 404. Null means "awaiting a type". */
  ofDocument: (id: string) =>
    request<DocumentClassification>(
      `/documents/${encodeURIComponent(id)}/classification`,
    ),
  /** CONFIRM or CHANGE. Admin only; a non-admin gets a 404 that says nothing
   *  about whether the document exists. Callers must therefore treat 404
   *  here as "you may not do this", not as "gone". */
  confirm: (id: string, body: ClassificationUpdate) =>
    request<DocumentClassification>(
      `/documents/${encodeURIComponent(id)}/classification`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
};

export const reports = {
  list: () => request<ReportList>("/reports"),
  generate: (message_id: string) =>
    request<ReportRecord>("/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id }),
    }),
  verify: (id: string) =>
    request<ReportVerification>(`/reports/${encodeURIComponent(id)}/verify`),
  /** Fetch the report PDF as bytes, with the bearer token on the request.
   *
   *  This replaces a `window.open(downloadUrl(id))` navigation. A navigation
   *  carries no Authorization header, and the token is in memory only (see
   *  the note on `token`), so under auth_mode=demo_required the download
   *  resolved to an empty scope and the backend answered 404 - telling the
   *  reader that a report listed on that same screen did not exist. The old
   *  comment here conceded the path only worked while auth was disabled.
   *
   *  The token stays in the Authorization header and is NEVER placed in the
   *  URL. A URL reaches browser history, proxy and server access logs and
   *  Referer headers; RAG-INTELLIGENCE-POC-EXECUTION.md rule 6 (line 43)
 *  forbids secrets in logs.
   *
   *  Returns bytes, never a file: writing the file is the caller's job, and
   *  a failure returns no bytes at all so no empty or truncated PDF can be
   *  handed to the reader. */
  download: (id: string): Promise<DownloadResult> =>
    downloadReport(`/reports/${encodeURIComponent(id)}/download`, `rag-intelligence-report-${id}.pdf`),
};

/** The outcome of a binary download.
 *
 *  Failure is a KIND, not a server-authored sentence. The backend answers 404
 *  with `{"code":"not_found","message":"no report with that id"}` for a report
 *  that is merely out of the caller's scope; rendering that message asserts a
 *  falsehood about the reader's own artefact. The UI branches on the kind and
 *  writes its own words, and `unavailable` deliberately covers "removed" and
 *  "not in your scope" together so the screen cannot leak which one it is. */
export type DownloadFailure =
  | { kind: "network"; detail: string }
  | { kind: "unauthenticated" }
  | { kind: "forbidden" }
  | { kind: "unavailable" }
  | { kind: "server"; message: string };

export type DownloadResult =
  | {
      ok: true;
      blob: Blob;
      /** The name to save under. */
      filename: string;
      /** true when the name came from Content-Disposition, false when the
       *  server sent no usable one and the caller's fallback is in use. */
      filenameFromServer: boolean;
    }
  | { ok: false; failure: DownloadFailure };

/** Pull a filename out of a Content-Disposition header.
 *
 *  Handles `filename*=UTF-8''...` (RFC 5987, preferred when present), quoted
 *  `filename="..."` and bare `filename=...`. Exported for its own test.
 *
 *  The result is reduced to a bare name: a server-supplied string reaches an
 *  anchor's `download` attribute, and path separators there are a directory
 *  the reader did not choose. */
export function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const extended = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  const quoted = /filename\s*=\s*"([^"]*)"/.exec(header);
  const bare = /filename\s*=\s*([^;"]+)/.exec(header);

  let raw: string | null = null;
  if (extended) {
    try {
      raw = decodeURIComponent(extended[1]);
    } catch {
      raw = null; // a malformed percent-escape is no filename at all
    }
  }
  if (raw === null && quoted) raw = quoted[1];
  if (raw === null && bare) raw = bare[1];
  if (raw === null) return null;

  // Basename only, and no control characters.
  const base = raw.trim().split(/[\\/]/).pop() ?? "";
  // Control characters and path punctuation cannot survive into a
  // `download` attribute; anything outside letters, digits and a small
  // safe set becomes an underscore.
  const clean = base.trim().replace(/[^\p{L}\p{N}. _()+@-]/gu, "_").trim();
  if (clean === "" || clean === "." || clean === "..") return null;
  return clean;
}

async function downloadReport(path: string, fallback: string): Promise<DownloadResult> {
  let response: Response;
  try {
    const headers = new Headers();
    // The one place a token is attached on this path - the header, never the
    // URL. `${BASE}${path}` below is built from the id alone.
    if (token) headers.set("Authorization", `Bearer ${token}`);
    response = await fetch(`${BASE}${path}`, { headers });
  } catch (e) {
    return {
      ok: false,
      failure: {
        kind: "network",
        detail: e instanceof Error ? e.message : "Network request failed.",
      },
    };
  }

  if (!response.ok) {
    // A gateway status means nothing served the request - the same condition
    // as a network failure, and it must read as one. Kept in step with the
    // JSON path above deliberately.
    if (GATEWAY_STATUSES.has(response.status)) {
      return { ok: false, failure: { kind: "network", detail: "Nothing answered on the API port." } };
    }
    if (response.status === 401) {
      // Same side effects as the JSON path: drop the dead token and tell the
      // app once. No retry - there is no refresh token by design.
      token = null;
      onUnauthenticated?.();
      return { ok: false, failure: { kind: "unauthenticated" } };
    }
    if (response.status === 403) return { ok: false, failure: { kind: "forbidden" } };
    if (response.status === 404) {
      // The body's message is discarded on purpose. See DownloadFailure.
      return { ok: false, failure: { kind: "unavailable" } };
    }
    return { ok: false, failure: { kind: "server", message: humanMessage(response.status) } };
  }

  // Reading the body is its own failure point: the status line arrives before
  // the bytes do, so a connection dropped mid-PDF throws HERE, on a response
  // that already said 200. Unguarded that becomes a rejected promise and the
  // reader gets a dead button; guarded it is the same "nothing was saved"
  // message as any other network failure. A partial read is never returned.
  let blob: Blob;
  try {
    blob = await response.blob();
  } catch (e) {
    return {
      ok: false,
      failure: {
        kind: "network",
        detail: e instanceof Error ? e.message : "The response body could not be read.",
      },
    };
  }

  const served = filenameFromContentDisposition(response.headers.get("Content-Disposition"));
  return {
    ok: true,
    blob,
    filename: served ?? fallback,
    filenameFromServer: served !== null,
  };
}

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
  /** Whether the watched folder is running, and what it last picked up.
   *  Guarded like the other list-bearing reads: a body without `recent`
   *  becomes an ordinary ApiError instead of a crash at the map. */
  watchStatus: () => request<WatchStatus>("/watch/status", undefined, hasArrayField("recent")),
  documents: () =>
    request<DocumentRecord[]>("/documents", undefined, isArrayBody),
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
  /** What the machine is doing. 404 once the entry has expired, which is not
   *  an error - it means the work finished and was collected. */
  progress: (progressId: string) =>
    request<Progress>(`/progress/${encodeURIComponent(progressId)}`),
  ask: (id: string, body: Partial<AskRequest>) =>
    request<AskResult>(`/conversations/${encodeURIComponent(id)}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: "", tier: "extract", ...body }),
    }),
};
