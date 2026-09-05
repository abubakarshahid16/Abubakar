/**
 * Chat.
 *
 * Three things this screen is responsible for, beyond showing text:
 *
 *  - A quotation and generated prose are visibly different. Only one of them
 *    is the specification, and the reader must never have to guess which.
 *  - Every answer opens onto its evidence: document, page, clause, the quoted
 *    passage, and the rendered page image.
 *  - When a follow-up is resolved, the terms carried in from earlier questions
 *    are shown on the turn. The reader's question is never silently rewritten.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { AnswerCard, sourcesOf, viewFromMessage, type AnswerView } from "../components/chat/AnswerCard";
import { EvidencePanel } from "../components/chat/EvidencePanel";
import type { Connection } from "../components/Shell";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "../components/states";
import type { ApiError, ConversationSummary, Message } from "../types/api";

type Load =
  | { s: "loading" }
  | { s: "error"; error: ApiError; disconnected: boolean }
  | { s: "ready" };

function relative(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

function UserTurn({ message }: { message: Message }) {
  return (
    <div className="flex flex-col items-end">
      <p className="max-w-[42rem] rounded-lg bg-ink-700 px-3 py-2 text-[15px] text-slateish-100">
        {message.text}
      </p>
      {/* `?? []` because carried_terms was added later: a transcript row
          written before it exists has no such field, and `.length` on
          undefined kills the whole conversation view for one legacy row.
          The response-shape guard at the client boundary cannot catch
          this - the body is well formed, one row inside it is old. */}
      {(message.carried_terms ?? []).length > 0 && (
        <p className="mt-1 max-w-[42rem] text-right text-xs text-slateish-500">
          Read as a follow-up. Also searched for{" "}
          {message.carried_terms.map((t, i) => (
            <span key={t}>
              {i > 0 && ", "}
              <span className="font-mono text-slateish-400">{t}</span>
            </span>
          ))}
          .
        </p>
      )}
    </div>
  );
}

export function ChatView({
  connection,
  onRetryConnection,
}: {
  connection: Connection;
  onRetryConnection: () => void;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [load, setLoad] = useState<Load>({ s: "loading" });

  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [failure, setFailure] = useState<ApiError | null>(null);

  const [evidence, setEvidence] = useState<{ messageId: string; index: number } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshList = useCallback(async () => {
    const r = await api.conversations();
    if (r.ok) setConversations(r.data.conversations);
  }, []);

  const loadList = useCallback(async () => {
    setLoad({ s: "loading" });
    const r = await api.conversations();
    if (!r.ok) {
      setLoad({ s: "error", error: r.error, disconnected: r.disconnected });
      return;
    }
    setConversations(r.data.conversations);
    setLoad({ s: "ready" });
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const open = useCallback(async (id: string) => {
    setCurrent(id);
    setEvidence(null);
    setFailure(null);
    const r = await api.conversation(id);
    if (r.ok) setMessages(r.data.messages);
    else setFailure(r.error);
  }, []);

  const startNew = useCallback(async () => {
    setFailure(null);
    const r = await api.newConversation();
    if (!r.ok) {
      setFailure(r.error);
      return;
    }
    setCurrent(r.data.id);
    setMessages([]);
    setEvidence(null);
    void refreshList();
  }, [refreshList]);

  const remove = useCallback(
    async (id: string) => {
      const r = await api.deleteConversation(id);
      if (!r.ok) {
        setFailure(r.error);
        return;
      }
      if (current === id) {
        setCurrent(null);
        setMessages([]);
        setEvidence(null);
      }
      void refreshList();
    },
    [current, refreshList],
  );

  // A ticking counter rather than a bare spinner. Tier 2 runs ~50s and is not
  // streamed; leaving the reader watching an indefinite spinner for that long
  // is indistinguishable from a hang.
  useEffect(() => {
    if (!asking && !explainingId) return;
    setElapsed(0);
    const started = Date.now();
    const t = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(t);
  }, [asking, explainingId]);

  useEffect(() => {
    // Guarded: scrollIntoView is absent in some environments, and failing to
    // scroll is not a reason for the whole transcript to stop rendering.
    const el = bottom.current;
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "end" });
  }, [messages.length, asking, explainingId]);

  const send = useCallback(async () => {
    const text = question.trim();
    if (!text || asking) return;
    setFailure(null);

    let id = current;
    if (!id) {
      const created = await api.newConversation();
      if (!created.ok) {
        setFailure(created.error);
        return;
      }
      id = created.data.id;
      setCurrent(id);
      setMessages([]);
    }

    setAsking(true);
    setQuestion("");
    const r = await api.ask(id, { question: text, tier: "extract" });
    setAsking(false);
    if (!r.ok) {
      setFailure(r.error);
      setQuestion(text); // give the question back rather than losing it
      return;
    }
    setMessages((m) => [...m, r.data.user_message, r.data.assistant_message]);
    void refreshList();
  }, [question, asking, current, refreshList]);

  const explain = useCallback(
    async (messageId: string) => {
      if (!current || explainingId) return;
      setFailure(null);
      setExplainingId(messageId);
      const r = await api.ask(current, { tier: "generated", explain_of: messageId });
      setExplainingId(null);
      if (!r.ok) {
        setFailure(r.error);
        return;
      }
      setMessages((m) => [...m, r.data.assistant_message]);
      void refreshList();
    },
    [current, explainingId, refreshList],
  );

  const offline = connection.state === "offline";

  const evidenceMessage = evidence ? messages.find((m) => m.id === evidence.messageId) : undefined;
  const evidenceSources = evidenceMessage ? sourcesOf(viewFromMessage(evidenceMessage)) : [];

  // The question that produced this answer: the last user turn before it. The
  // RESOLVED question is used when a follow-up carried terms forward, because
  // that is what retrieval actually ran and therefore what the span was found
  // against.
  const evidenceQuestion = (() => {
    if (!evidenceMessage) return undefined;
    const index = messages.findIndex((m) => m.id === evidenceMessage.id);
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === "user") {
        return messages[i].resolved_question ?? messages[i].text ?? undefined;
      }
    }
    return undefined;
  })();

  /** An assistant turn already followed by its explanation must not offer
   *  Explain again — pressing it twice would spend another ~50 seconds
   *  reproducing an answer already on screen. */
  const explainedIds = new Set(
    messages.map((m) => m.explains_id).filter((x): x is string => Boolean(x)),
  );

  return (
    <div className="flex h-[calc(100vh-6rem)] min-h-0 flex-col gap-4 lg:flex-row">
      {/* ------------------------------------------------ recent conversations */}
      <aside
        aria-label="Recent conversations"
        className="flex max-h-56 min-h-0 w-full shrink-0 flex-col rounded-lg border border-ink-700 bg-ink-850 lg:max-h-none lg:w-64"
      >
        <div className="flex items-center justify-between gap-2 border-b border-ink-700 px-3 py-2.5">
          <h2 className="text-sm font-semibold text-slateish-200">Conversations</h2>
          <button
            type="button"
            onClick={startNew}
            className="rounded border border-ink-600 px-2 py-1 text-xs text-slateish-300 hover:bg-ink-700"
          >
            New
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {load.s === "loading" && <Spinner label="Loading conversations" />}
          {load.s === "error" &&
            (load.disconnected ? (
              <DisconnectedState onRetry={onRetryConnection} />
            ) : (
              <ErrorState error={load.error} onRetry={loadList} />
            ))}
          {load.s === "ready" && conversations.length === 0 && (
            <p className="px-2 py-3 text-xs text-slateish-500">
              No conversations yet. Ask a question below.
            </p>
          )}
          <ul className="space-y-1">
            {conversations.map((c) => (
              <li key={c.id} className="group relative">
                <button
                  type="button"
                  aria-current={c.id === current ? "true" : undefined}
                  onClick={() => void open(c.id)}
                  className={[
                    "w-full rounded px-2 py-2 pr-7 text-left",
                    c.id === current ? "bg-ink-700" : "hover:bg-ink-800",
                  ].join(" ")}
                >
                  <span className="block truncate text-sm text-slateish-200">{c.title}</span>
                  <span className="mt-0.5 block text-[11px] text-slateish-500">
                    {c.message_count} message{c.message_count === 1 ? "" : "s"} ·{" "}
                    {relative(c.updated_at)}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete conversation ${c.title}`}
                  onClick={() => void remove(c.id)}
                  className="absolute right-1 top-1.5 rounded px-1.5 py-0.5 text-xs text-slateish-500 opacity-0 hover:bg-ink-600 hover:text-danger-500 focus:opacity-100 group-hover:opacity-100"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      {/* ----------------------------------------------------------- transcript */}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col rounded-lg border border-ink-700 bg-ink-900">
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {messages.length === 0 && !asking && (
            <EmptyState
              title="Ask a question about the indexed documents"
              hint="You get the document's own words back, with the page and clause. Ask a follow-up and it will carry the subject forward — and show you what it carried."
            />
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <UserTurn key={m.id} message={m} />
            ) : (
              <div key={m.id} className="max-w-[52rem]">
                <AnswerCard
                  view={viewFromMessage(m) as AnswerView}
                  activeSource={evidence?.messageId === m.id ? evidence.index : null}
                  onSelectSource={(i) => setEvidence({ messageId: m.id, index: i })}
                  explainsEarlier={Boolean(m.explains_id)}
                  onExplain={
                    m.answer_type === "extract" && !explainedIds.has(m.id)
                      ? () => void explain(m.id)
                      : undefined
                  }
                  explaining={explainingId === m.id}
                  explainSeconds={explainingId === m.id ? elapsed : undefined}
                />
              </div>
            ),
          )}

          {asking && (
            <div className="max-w-[52rem] rounded-lg border border-ink-700 bg-ink-850 p-4">
              <Spinner label={`Searching the documents · ${elapsed}s`} />
            </div>
          )}

          {failure && (
            <div className="max-w-[52rem]">
              <ErrorState error={failure} />
            </div>
          )}

          <div ref={bottom} />
        </div>

        {/* ------------------------------------------------------------ composer */}
        <form
          className="border-t border-ink-700 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <div className="flex gap-2">
            <label htmlFor="chat-question" className="sr-only">
              Your question
            </label>
            <input
              id="chat-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={offline}
              placeholder="What is the NDFT for coating system no. 1?"
              className="min-w-0 flex-1 rounded border border-ink-600 bg-ink-850 px-3 py-2 text-slateish-100 placeholder:text-slateish-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={asking || offline || !question.trim()}
              className="rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30 disabled:opacity-40"
            >
              Ask
            </button>
          </div>
          <p className="mt-1.5 text-xs text-slateish-500">
            Answers are quoted from the documents. Nothing you type leaves this
            machine.
          </p>
        </form>
      </section>

      {/* -------------------------------------------------------- evidence panel */}
      {evidence && evidenceSources.length > 0 && (
        <EvidencePanel
          passages={evidenceSources}
          selected={Math.min(evidence.index, evidenceSources.length - 1)}
          onSelect={(i) => setEvidence({ messageId: evidence.messageId, index: i })}
          onClose={() => setEvidence(null)}
          // The question this answer came from, so the answering sentence can
          // be boxed on the rendered page. Taken from the user turn that
          // preceded this assistant turn.
          question={evidenceQuestion}
        />
      )}
    </div>
  );
}
