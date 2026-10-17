/**
 * Chat: conversations, ask, the answer stream and the market search.
 *
 * Split out of api/client.ts (order 79b). Moved verbatim; screens keep
 * importing from "api/client", which re-exports this module.
 */
import { SseParser } from "./sse";
import type {
  DeletedConversation,
  ApiError,
  AskRequest,
  AskResult,
  CancelledTurn,
  ChatFeedback,
  ChatModels,
  ChatSource,
  ChatStep,
  ChatVerification,
  Conversation,
  ConversationDetail,
  ConversationList,
  FiledComment,
  Message,
  WithdrawnComment,
  MarketFindings,
  MarketPreview,
  MarketQueryPreview,
  MarketSearchRequest,
  MarketSearchResult,
  Progress,
  MarketQueryRequest,
} from "../types/api";

import { BASE, request, failureOf, disconnected, hasArrayField, token } from "./core";
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

/** One event of a streamed answer, as `askStream` hands it to the screen. */
export type StreamEvent =
  | { event: "turn"; data: { turn_id: string } }
  | { event: "step"; data: ChatStep }
  | { event: "delta"; data: { text: string } }
  | { event: "sources"; data: { sources: ChatSource[] } }
  | { event: "verification"; data: ChatVerification }
  | { event: "notice"; data: { text: string } };

export type StreamOutcome =
  | { kind: "done"; result: AskResult }
  | { kind: "failed"; disconnected: boolean; error: ApiError }
  /** The reader aborted the request before the answer finished. */
  | { kind: "aborted" }
  /** The server answered without streaming (an older backend): the caller
   *  asks through `api.ask` instead. Nothing was answered by this request. */
  | { kind: "unsupported" };

function offlineError(e: unknown, fallback: string): ApiError {
  const r = disconnected(e instanceof Error ? e.message : fallback);
  return r.ok ? { code: "internal", message: fallback } : r.error;
}

const STREAM_EVENTS = new Set(["turn", "step", "delta", "sources", "verification", "notice"]);

/**
 * `ask`, streamed: progress steps, the text as it is written, then the same
 * complete answer the non-streaming route returns (the `done` event).
 *
 * A POST read with `fetch`, not an EventSource: the route needs the question
 * in a body and the token in a header, and EventSource can send neither.
 * Aborting `signal` closes the connection, which the server reads as Stop.
 */
export async function askStream(
  conversationId: string,
  body: Partial<AskRequest>,
  { signal, onEvent }: { signal?: AbortSignal; onEvent: (e: StreamEvent) => void },
): Promise<StreamOutcome> {
  let response: Response;
  try {
    const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
    if (token) headers.set("Authorization", `Bearer ${token}`);
    response = await fetch(`${BASE}/conversations/${encodeURIComponent(conversationId)}/ask/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ question: "", tier: "generated", ...body }),
      signal,
    });
  } catch (e) {
    if (signal?.aborted) return { kind: "aborted" };
    return { kind: "failed", disconnected: true, error: offlineError(e, "Network request failed.") };
  }
  if (!response.ok) {
    // 404/405 from a backend that has no stream route at all. A 404 that
    // names a missing CONVERSATION carries a code and is a real failure.
    if (response.status === 405) return { kind: "unsupported" };
    if (response.status === 404) {
      const body = await response.clone().json().catch(() => null);
      const raw = body?.detail ?? body;
      if (!(raw && typeof raw === "object" && "code" in raw)) return { kind: "unsupported" };
    }
    const failed = await failureOf(response);
    if (!failed.ok) return { kind: "failed", disconnected: failed.disconnected, error: failed.error };
  }
  if (!(response.headers.get("Content-Type") ?? "").includes("text/event-stream")) {
    return { kind: "unsupported" };
  }

  const parser = new SseParser();
  const handle = (events: ReturnType<SseParser["push"]>): StreamOutcome | null => {
    for (const e of events) {
      if (e.event === "done") return { kind: "done", result: e.data as AskResult };
      if (e.event === "error") {
        const raw = e.data as ApiError | null;
        return {
          kind: "failed",
          disconnected: false,
          error: raw && typeof raw === "object" && "code" in raw
            ? raw
            : { code: "internal", message: "The answer could not be completed." },
        };
      }
      if (STREAM_EVENTS.has(e.event)) onEvent(e as StreamEvent);
    }
    return null;
  };

  try {
    if (!response.body) {
      const text = await response.text();
      const whole = handle([...parser.push(text), ...parser.push("\n\n")]);
      if (whole) return whole;
    } else {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const outcome = handle(parser.push(decoder.decode(value, { stream: true })));
        if (outcome) {
          void reader.cancel().catch(() => undefined);
          return outcome;
        }
      }
      const tail = handle(parser.push(decoder.decode() + "\n\n"));
      if (tail) return tail;
    }
  } catch (e) {
    if (signal?.aborted) return { kind: "aborted" };
    return { kind: "failed", disconnected: true, error: offlineError(e, "The connection closed.") };
  }
  if (signal?.aborted) return { kind: "aborted" };
  return {
    kind: "failed",
    disconnected: false,
    error: { code: "internal", message: "The answer stopped before it finished. Try again." },
  };
}

export const chatApi = {
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
  /** Which engines can answer a chat question, and which one answers by
   *  default. Says WHY one is unavailable; never carries a key. */
  chatModels: () =>
    request<ChatModels>("/chat/models", undefined, hasArrayField("models")),
  /** Stop an answer being written. The server closes the provider call and
   *  stores the turn as stopped, with what the reader had been shown. */
  /** "Search once": run the one web search a consent turn offered. Sends
   *  no text - the server sends exactly the phrase the consent turn showed
   *  and stored, after re-checking it against the whitelist. */
  webSearch: (conversationId: string, messageId: string) =>
    request<Message>(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/web-search`,
      { method: "POST" },
    ),
  /** "Was this right?" on one answer. The reader's own; stored locally. */
  chatFeedback: (conversationId: string, messageId: string, helpful: boolean) =>
    request<ChatFeedback>(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/feedback`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ helpful }) },
    ),
  /** "Add to comment sheet": file the text the engineer has in front of them. */
  fileComment: (conversationId: string, messageId: string, text: string) =>
    request<FiledComment>(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/comment`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) },
    ),
  /** Undo a filing - the filer, within minutes, while nobody has changed it. */
  withdrawComment: (conversationId: string, messageId: string, findingId: string) =>
    request<WithdrawnComment>(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/comment/${encodeURIComponent(findingId)}`,
      { method: "DELETE" },
    ),
  cancelTurn: (conversationId: string, turnId: string) =>
    request<CancelledTurn>(
      `/conversations/${encodeURIComponent(conversationId)}/ask/${encodeURIComponent(turnId)}/cancel`,
      { method: "POST" },
    ),
};
