/**
 * Shared base of the API client: the token, request(), typed failures, shape checks, downloads.
 *
 * Split out of api/client.ts (order 79b). Moved verbatim; screens keep
 * importing from "api/client", which re-exports this module.
 */
import type {
  ApiError,
} from "../types/api";

export type Result<T> =
  | { ok: true; data: T; response?: Response }
  | { ok: false; disconnected: true; error: ApiError }
  | { ok: false; disconnected: false; error: ApiError };

export const BASE = "/api";

/** Statuses that mean nothing served the request at all. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** The bearer token, in memory only.
 *
 *  Never localStorage: it outlives the tab, and every XSS then becomes
 *  credential theft rather than a session-length nuisance. The cost is that a
 *  reload logs you out, which the login screen states rather than leaving the
 *  reader to discover.
 */
export let token: string | null = null;
let onUnauthenticated: (() => void) | null = null;

/** Bumped whenever the token changes, so a GET shared by `request()` is never
 *  handed to a caller signed in as someone else. The key carries this number,
 *  never the token: the token's one destination is the Authorization header. */
let tokenGeneration = 0;

export function setToken(next: string | null) {
  token = next;
  tokenGeneration += 1;
}

export function isSignedIn() {
  return token !== null;
}

/** Attach the bearer header to a transport this module does not own.
 *
 *  THE UPLOAD IS THE ONE REQUEST `request()` CANNOT MAKE. It needs
 *  XMLHttpRequest for upload progress, which `fetch` cannot report, so the
 *  upload path has always built its own request - and under
 *  `AUTH_MODE=demo_required` it sent no Authorization header at all, which
 *  `POST /api/documents` answers with a 401 (`_require_identity_to_write`).
 *
 *  The token is handed to a SETTER rather than returned, so it still has
 *  exactly one destination: an Authorization header. A `getToken()` would be a
 *  value any caller could log, put in a URL or store, and the whole reason it
 *  lives in memory only is that it must not be any of those.
 */
export function authorize(setHeader: (name: string, value: string) => void) {
  if (token) setHeader("Authorization", `Bearer ${token}`);
}

/** Called when the backend says the token is no good. No auto-retry, no
 *  refresh, no redirect loop - the screen changes and the reader decides. */
export function onSignedOut(fn: (() => void) | null) {
  onUnauthenticated = fn;
}

/** THE ONE HOME FOR "the backend said the token is no good": drop the dead
 *  token and tell the app once. Every transport calls this on its own 401 -
 *  the JSON path, the answer stream, the report download, the page image and
 *  the upload (audit 2026-09-30: the image/PDF fetch and the upload did not,
 *  so a reader with an expired session saw "could not render" or "Upload
 *  failed" and stayed on a screen that could no longer do anything).
 *  No auto-retry and no refresh flow: there is no refresh token by design. */
export function signOutOn401(status: number): void {
  if (status === 401) {
    token = null;
    tokenGeneration += 1;
    onUnauthenticated?.();
  }
}

/** For the one transport this module does not own (the XHR upload): report
 *  the status it got, so a 401 there signs out exactly as one here does. */
export function reportResponseStatus(status: number): void {
  signOutOn401(status);
}

/** What to tell a reader, in words they can act on. */
export function humanMessage(status: number): string {
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

export function disconnected(detail: string): Result<never> {
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

export const hasNumberField =
  (field: string): ShapeCheck =>
  (b) =>
    typeof b === "object" &&
    b !== null &&
    typeof (b as Record<string, unknown>)[field] === "number";

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

/** Fetches a page-image route WITH the bearer header and returns an object
 *  URL for an `<img>`. A bare `<img src>` cannot carry Authorization, so under
 *  any auth mode that requires a token it is a guaranteed 401 and a broken
 *  image - which is exactly what shipped once AUTH_MODE left `disabled`. The
 *  token stays in the header; the URL is built from ids alone and is never
 *  given the token as a query parameter. The caller owns the returned URL and
 *  must revoke it. Null on any failure, so the caller renders "could not
 *  render" rather than the browser's broken-image glyph. */
/** #967: one value to underline on the Sheet's page, by its finding. */
export interface SheetMark {
  findingId: string;
  state: "open" | "tick" | "answered";
}

/** #967: one value to underline on the Sheet's page, by its finding. */
export interface SheetMark {
  findingId: string;
  state: "open" | "tick" | "answered";
}

export interface ImageObjectResult {
  url: string | null;
  /** null means the endpoint did not provide answer-location metadata. */
  answerLocated: boolean | null;
  /** #967: how many of the asked marks the server placed, out of how many;
   *  null when the endpoint is not the Sheet's page image. */
  marksLocated: number | null;
  marksTotal: number | null;
}

export function count(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

export async function fetchImageObjectUrl(url: string): Promise<ImageObjectResult> {
  try {
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(url, { headers });
    if (!response.ok) {
      signOutOn401(response.status);
      return { url: null, answerLocated: null, marksLocated: null, marksTotal: null };
    }
    const located = response.headers.get("X-Answer-Located");
    return {
      url: URL.createObjectURL(await response.blob()),
      answerLocated: located === "0" ? false : located === "1" ? true : null,
      marksLocated: count(response.headers.get("X-Marks-Located")),
      marksTotal: count(response.headers.get("X-Marks-Total")),
    };
  } catch {
    return { url: null, answerLocated: null, marksLocated: null, marksTotal: null };
  }
}

export async function downloadReport(path: string, fallback: string): Promise<DownloadResult> {
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
      signOutOn401(response.status);
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

/** A response that is not ok, as the Result every screen already renders.
 *  Shared by `request()` and the answer stream, so a 401 on either clears
 *  the token and tells the app exactly once, the same way. */
export async function failureOf(response: Response): Promise<Result<never>> {
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
  signOutOn401(response.status);

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

/** What one fetch-and-parse produced: a failure every caller renders the same
 *  way, or the parsed body with the response it came on. */
type Fetched =
  | { ok: false; result: Result<never> }
  | { ok: true; body: unknown; response: Response };

/** GETs just asked for, by path and the identity they were asked under (order
 *  117 item 6). Screens that ask for the same thing in the same moment - sibling
 *  components mounting in one commit, StrictMode's double effect - share one
 *  request instead of making the server answer twice.
 *
 *  ONLY THE SAME MOMENT. An entry lives until the current task ends (a
 *  microtask), not until the request settles: a GET that hangs would otherwise
 *  hold every later identical GET hostage, and a reader pressing "try again"
 *  must get a fresh request. Nothing is kept: this is not a cache. */
const inFlight = new Map<string, Promise<Fetched>>();

/** Only a plain GET is shared. A body, another method, or a caller's own abort
 *  signal makes the request that caller's alone: aborting one screen's request
 *  must never cancel another screen's. */
function sharedKey(path: string, init?: RequestInit): string | null {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET" || init?.body != null || init?.signal) return null;
  if (init?.headers && [...new Headers(init.headers).keys()].length > 0) return null;
  return `${tokenGeneration}\u0000${path}`;
}

async function fetchAndParse(path: string, init?: RequestInit): Promise<Fetched> {
  let response: Response;
  try {
    // The single fetch in the module, which is why the token can be attached
    // in exactly one place - the module's own principle, stated at the top.
    const headers = new Headers(init?.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (e) {
    // fetch only rejects on a network-level failure - the server is down
    return {
      ok: false,
      result: disconnected(e instanceof Error ? e.message : "Network request failed."),
    };
  }

  if (!response.ok) return { ok: false, result: await failureOf(response) };

  // A 200 whose body is not JSON (a proxy's HTML page, a truncated body) must
  // become the same typed failure every caller already handles - never a
  // rejected promise, which strands whatever flag the caller set before it.
  try {
    return { ok: true, body: response.status === 204 ? null : await response.json(), response };
  } catch {
    return {
      ok: false,
      result: {
        ok: false,
        disconnected: false,
        error: {
          code: "internal",
          message:
            "The server's reply could not be read. If you changed something, it may " +
            "or may not have been saved - reload to check before trying again.",
        },
      },
    };
  }
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  expect?: ShapeCheck,
): Promise<Result<T>> {
  const key = sharedKey(path, init);
  let pending = key === null ? undefined : inFlight.get(key);
  if (pending === undefined) {
    pending = fetchAndParse(path, init);
    if (key !== null) {
      const mine = pending;
      inFlight.set(key, mine);
      queueMicrotask(() => {
        if (inFlight.get(key) === mine) inFlight.delete(key);
      });
    }
  }
  const fetched = await pending;
  if (!fetched.ok) return fetched.result;
  const { body, response } = fetched;
  // Each caller's own shape check, even on a shared request: two screens may
  // read different fields of the same body.
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
  return { ok: true, data: body as T, response };
}
