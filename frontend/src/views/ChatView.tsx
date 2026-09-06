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

import { api, reports as reportsApi } from "../api/client";
import {
  AnswerCard,
  sourcesOf,
  viewFromMessage,
  type AnswerView,
  type UpgradeFailure,
} from "../components/chat/AnswerCard";
import { EvidencePanel } from "../components/chat/EvidencePanel";
import { LocalWork } from "../components/chat/LocalWork";
import type { Connection } from "../components/Shell";
import type { Progress } from "../types/api";
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

/** Append only the turns the transcript does not already have.
 *
 * `chat.ask` commits the USER turn to the database BEFORE generating the
 * answer, so any reload during those 20-50 seconds already contains it. A
 * blind append then renders the question twice with a single answer beneath
 * it. Keyed by id rather than by position, because the transcript may have
 * been replaced wholesale rather than merely grown.
 */
function appendUnseen(existing: Message[], incoming: Message[]): Message[] {
  const seen = new Set(existing.map((m) => m.id));
  const fresh = incoming.filter((m) => !seen.has(m.id));
  return fresh.length > 0 ? [...existing, ...fresh] : existing;
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
  // WHICH conversation the pending question belongs to, not merely that one is
  // pending: the spinner must not appear under a transcript the reader moved
  // to while the answer was still running.
  const [askingIn, setAskingIn] = useState<string | null>(null);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // The id THIS client chose for the request in flight, and what the backend
  // says it is doing. `progress` stays null until the first poll returns: the
  // stage is never guessed from the clock in the meantime.
  const [progressId, setProgressId] = useState<string | null>(null);
  // Which message is being turned into a report, and what the last attempt
  // said. Keyed by message id so a notice appears on the card it belongs to.
  const [savingReport, setSavingReport] = useState<string | null>(null);
  const [reportNotice, setReportNotice] = useState<Record<string, string>>({});
  const [progress, setProgress] = useState<Progress | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);

  const [evidence, setEvidence] = useState<{ messageId: string; index: number } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const asking = askingIn !== null;

  // ------------------------------------------------------ request ownership
  //
  // Every polling loop in this codebase already carries a cancelled flag;
  // send(), open() and explain() did not. A Tier 2 answer takes 20-50 seconds
  // and is not streamed, so the window in which the reader gets impatient and
  // clicks something else is wide - and each of the three applied its result
  // to whatever transcript was on screen when it resolved.
  //
  // `owned` is the conversation the screen currently belongs to, held in a ref
  // so it can be read synchronously after an await. A response whose ticket no
  // longer matches is DROPPED, not deferred and not reordered: the reader has
  // moved on, and a late answer under the wrong question is worse than no
  // answer at all. The server has persisted it either way, so it is still
  // there when the conversation is reopened.
  const owned = useRef<string | null>(null);

  // `askingIn` cannot guard the submit on its own: in a fresh chat there is an
  // await (creating the conversation) BEFORE it is set, and the Ask button is
  // still enabled across it. A double-click there created two conversations
  // and spent two Tier 1 answers. A ref is set synchronously, so the second
  // click sees it.
  const sending = useRef(false);

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
    owned.current = id;
    setCurrent(id);
    setEvidence(null);
    setFailure(null);
    const r = await api.conversation(id);
    // Two quick clicks between conversations: without this, the SLOWER
    // response wins and paints its transcript under the other name.
    if (owned.current !== id) return;
    if (r.ok) setMessages(r.data.messages);
    else setFailure(r.error);
  }, []);

  const startNew = useCallback(async () => {
    setFailure(null);
    // Nothing on screen is owned while the new conversation is being created,
    // so an in-flight response for the previous one cannot land in it.
    owned.current = null;
    const r = await api.newConversation();
    if (!r.ok) {
      setFailure(r.error);
      return;
    }
    owned.current = r.data.id;
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
        owned.current = null;
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

  // Poll for the stage the backend has actually reached. The elapsed counter
  // above is the client's own and keeps counting through a missed poll; this
  // only ever adds what the work REPORTED.
  useEffect(() => {
    if (!progressId) {
      setProgress(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      const r = await api.progress(progressId);
      // A 404 means the entry has expired or does not exist yet. Neither is an
      // error and neither is a stage, so nothing is shown for it.
      if (!cancelled && r.ok) setProgress(r.data);
    };
    void tick();
    const t = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [progressId]);

  useEffect(() => {
    // Guarded: scrollIntoView is absent in some environments, and failing to
    // scroll is not a reason for the whole transcript to stop rendering.
    const el = bottom.current;
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "end" });
  }, [messages.length, asking, explainingId]);

  const send = useCallback(async () => {
    const text = question.trim();
    if (!text || asking || sending.current) return;
    sending.current = true;
    setFailure(null);

    let id = current;
    if (!id) {
      const created = await api.newConversation();
      if (!created.ok) {
        sending.current = false;
        setFailure(created.error);
        return;
      }
      id = created.data.id;
      owned.current = id;
      setCurrent(id);
      setMessages([]);
    }

    setAskingIn(id);
    setQuestion("");
    const ticket = crypto.randomUUID();
    setProgressId(ticket);
    const r = await api.ask(id, { question: text, tier: "extract",
                                  progress_id: ticket });
    setProgressId(null);
    sending.current = false;
    setAskingIn((pending) => (pending === id ? null : pending));

    // Dropped: the reader is reading a different conversation now. Both turns
    // are persisted server-side and appear when this one is reopened.
    if (owned.current !== id) return;

    if (!r.ok) {
      setFailure(r.error);
      setQuestion(text); // give the question back rather than losing it
      return;
    }
    setMessages((m) => appendUnseen(m, [r.data.user_message, r.data.assistant_message]));
    void refreshList();
  }, [question, asking, current, refreshList]);

  const explain = useCallback(
    async (messageId: string) => {
      if (!current || explainingId) return;
      const conversationId = current;
      // The turn the explanation was going to be appended beneath. The server
      // appends it at the end of the conversation, so it reads as "an
      // explanation of the quoted answer above" only if nothing else has
      // arrived in the meantime.
      const tailAtRequest = messages.length > 0 ? messages[messages.length - 1].id : null;

      setFailure(null);
      setExplainingId(messageId);
      const ticket = crypto.randomUUID();
      setProgressId(ticket);
      const r = await api.ask(conversationId, { tier: "generated",
                                                explain_of: messageId,
                                                progress_id: ticket });
      setProgressId(null);
      setExplainingId((pending) => (pending === messageId ? null : pending));

      if (owned.current !== conversationId) return;
      if (!r.ok) {
        setFailure(r.error);
        return;
      }
      // The tail is read INSIDE the updater, so it is the live transcript
      // rather than a copy captured before the await.
      setMessages((m) => {
        const tail = m.length > 0 ? m[m.length - 1].id : null;
        if (tail !== tailAtRequest) return m; // the reader asked something else
        return appendUnseen(m, [r.data.assistant_message]);
      });
      void refreshList();
    },
    [current, explainingId, messages, refreshList],
  );

  const saveReport = useCallback(
    async (messageId: string) => {
      setSavingReport(messageId);
      setReportNotice((n) => ({ ...n, [messageId]: "" }));
      const r = await reportsApi.generate(messageId);
      setSavingReport(null);
      if (r.ok) {
        setReportNotice((n) => ({
          ...n,
          [messageId]:
            `Saved as ${r.data.id} — ${r.data.page_count} page` +
            `${r.data.page_count === 1 ? "" : "s"}. Open it on the Reports screen.`,
        }));
        return;
      }
      // The route refuses a message that cites nothing (NotReportable, 422).
      // Saying so is the point: a button that silently does nothing is the
      // defect this replaces.
      setReportNotice((n) => ({ ...n, [messageId]: r.error.message }));
    },
    [],
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

  /** The question that produced this answer, in the READER'S OWN WORDS: the
   *  last user turn before it. `resolved_question` is deliberately the
   *  fallback rather than the preference here — the evidence panel wants what
   *  retrieval ran, but whether a question ASKS for a comparison is a fact
   *  about what the reader typed, not about what the resolver made of it. */
  const questionFor = (messageId: string): string | null => {
    const index = messages.findIndex((m) => m.id === messageId);
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === "user") {
        return messages[i].text ?? messages[i].resolved_question ?? null;
      }
    }
    return null;
  };

  /** A Tier 2 upgrade that produced nothing showable.
   *
   *  `chat.ask(explain_of=…)` persists the attempt as its own assistant turn,
   *  whatever the outcome. When `synthesis`/`answer` refuses the generated
   *  prose — the model cited no supplied source — that turn comes back as
   *  `insufficient_evidence`, and the transcript rendered it as a PEER of the
   *  extract it was an upgrade of. The screen then asserted "here is your
   *  answer, quoted from page 17" and "The documents do not answer this"
   *  simultaneously, about the same question. The refusal is correct; its
   *  SCOPE was not. */
  const isFailedUpgrade = (m: Message) =>
    Boolean(m.explains_id) &&
    (m.answer_type === "insufficient_evidence" || m.answer_type === "model_unavailable");

  const present = new Set(messages.map((m) => m.id));
  /** The latest failed upgrade per answer it was an upgrade OF. */
  const failedUpgrades = new Map<string, Message>();
  /** Every failed upgrade being reported on another card, so it is not also
   *  drawn as one. Only suppressed when the card it attaches to is actually
   *  on screen — a failure with nowhere to go is still shown, because a
   *  vanished attempt is the other half of this defect. */
  const attachedElsewhere = new Set<string>();
  for (const m of messages) {
    if (!isFailedUpgrade(m) || !present.has(m.explains_id!)) continue;
    failedUpgrades.set(m.explains_id!, m);
    attachedElsewhere.add(m.id);
  }

  /** An assistant turn already followed by its explanation must not offer
   *  Explain again — pressing it twice would spend another ~50 seconds
   *  reproducing an answer already on screen. A REFUSED upgrade put nothing
   *  on screen, so it is not one of those: the button stays, now labelled as
   *  a retry, with the failure reported beneath it. */
  const explainedIds = new Set(
    messages
      .filter((m) => m.answer_type === "generated")
      .map((m) => m.explains_id)
      .filter((x): x is string => Boolean(x)),
  );

  /** The failed upgrade to report on the card for `messageId`, if any.
   *
   *  Its passages stay addressed by ITS OWN message id, so opening one puts
   *  the failed attempt's evidence in the panel rather than silently
   *  substituting the extract's — the two sets are not the same. */
  const upgradeFailureFor = (messageId: string): UpgradeFailure | null => {
    const f = failedUpgrades.get(messageId);
    if (!f) return null;
    return {
      answer_type: f.answer_type ?? "insufficient_evidence",
      reason: f.reason,
      considered: sourcesOf(viewFromMessage(f)),
      activeSource: evidence?.messageId === f.id ? evidence.index : null,
      onSelectSource: (i: number) => setEvidence({ messageId: f.id, index: i }),
    };
  };

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
          {messages.length === 0 && askingIn !== current && (
            <EmptyState
              title="Ask a question about the indexed documents"
              hint="You get the document's own words back, with the page and clause. Ask a follow-up and it will carry the subject forward — and show you what it carried."
            />
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <UserTurn key={m.id} message={m} />
            ) : attachedElsewhere.has(m.id) ? null : (
              <div key={m.id} className="max-w-[52rem]">
                <AnswerCard
                  view={viewFromMessage(m) as AnswerView}
                  activeSource={evidence?.messageId === m.id ? evidence.index : null}
                  onSelectSource={(i) => setEvidence({ messageId: m.id, index: i })}
                  explainsEarlier={Boolean(m.explains_id)}
                  question={questionFor(m.id)}
                  onExplain={
                    m.answer_type === "extract" && !explainedIds.has(m.id)
                      ? () => void explain(m.id)
                      : undefined
                  }
                  onSaveReport={
                    // Only an ANSWER can be frozen. A refusal has no evidence
                    // to freeze, and the route would refuse it anyway.
                    m.answer_type === "extract" || m.answer_type === "generated"
                      ? () => void saveReport(m.id)
                      : undefined
                  }
                  savingReport={savingReport === m.id}
                  reportNotice={reportNotice[m.id] || null}
                  upgradeFailure={upgradeFailureFor(m.id)}
                  explaining={explainingId === m.id}
                  explainSeconds={explainingId === m.id ? elapsed : undefined}
                />
              </div>
            ),
          )}

          {askingIn === current && (
            <LocalWork elapsed={elapsed} progress={progress} />
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
