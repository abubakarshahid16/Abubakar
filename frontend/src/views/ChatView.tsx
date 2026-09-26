/**
 * Chat.
 *
 * Owner order 2026-09-26 (chat redesign): one centred conversation, recent
 * chats in the left navigation, answers written as they stream in, and a Stop
 * that stops. Everything the screen promised before still holds, moved rather
 * than removed:
 *
 *  - A quotation and generated prose are visibly different. Only one of them
 *    is the specification, and the reader must never have to guess which.
 *    General knowledge says it is general knowledge, and cites nothing.
 *  - Every document answer opens onto its evidence: document, page, clause,
 *    the quoted words, and the rendered page image ("Open page").
 *  - When a follow-up is resolved, the terms carried in from earlier questions
 *    are shown on the turn. The reader's question is never silently rewritten.
 *  - A response belongs to the request that asked for it: a late answer is
 *    never painted under a conversation the reader has moved to.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, askStream, reports as reportsApi, structuredSearch, type StreamOutcome } from "../api/client";
import { sourcesOf, viewFromMessage, type UpgradeFailure } from "../components/chat/AnswerCard";
import { AssistantAnswer, StreamingAnswer } from "../components/chat/AssistantAnswer";
import { ChatEmptyHeading, ChatStarters } from "../components/chat/ChatEmptyState";
import { Composer, type ModelChoice } from "../components/chat/Composer";
import { EvidencePanel } from "../components/chat/EvidencePanel";
import { LocalWork } from "../components/chat/LocalWork";
import { UserMessage } from "../components/chat/UserMessage";
import type { Connection } from "../components/Shell";
import { ErrorState, ZeroResultsState } from "../components/states";
import type {
  AnswerTier,
  ApiError,
  AskRequest,
  ChatModels,
  ChatStep,
  ChatVerification,
  ConversationSummary,
  Message,
  Progress,
  StructuredSearchResult,
} from "../types/api";

// On the local engine a quotation is the fast, exact default and a written
// answer is ~50 s away behind "Explain". A review or critique is a synthesis
// request, so it goes to the written path instead of returning a misleading
// "not found" - and the reader is told that it did.
function isReviewRequest(text: string): boolean {
  return /\b(review|critique|criteque|assess|assessment|evaluate|evaluation|audit|commentary|comment on|comments? on)\b/i.test(text);
}

/** Append only the turns the transcript does not already have.
 *
 * `chat.ask` commits the USER turn to the database BEFORE generating the
 * answer, so any reload during those seconds already contains it. A blind
 * append then renders the question twice with a single answer beneath it.
 * Keyed by id rather than by position, because the transcript may have been
 * replaced wholesale rather than merely grown.
 */
function appendUnseen(existing: Message[], incoming: Message[]): Message[] {
  const seen = new Set(existing.map((m) => m.id));
  const fresh = incoming.filter((m) => !seen.has(m.id));
  return fresh.length > 0 ? [...existing, ...fresh] : existing;
}

/** An answer being written, for the conversation it belongs to. */
interface Pending {
  conversationId: string;
  /** what the reader typed; null for an Explain, which asks nothing new */
  question: string | null;
  turnId: string | null;
  steps: ChatStep[];
  text: string;
  verification: ChatVerification | null;
  stopping: boolean;
  /** the server did not stream: the old progress panel is shown instead */
  legacy: boolean;
}

interface SendOptions {
  tier?: AnswerTier;
  explainOf?: string;
}

export function ChatView({
  connection,
  onRetryConnection: _onRetryConnection,
  onNavigate,
  conversationId = null,
  onConversationChange,
  onListChanged,
}: {
  connection: Connection;
  onRetryConnection: () => void;
  onNavigate?: (view: "documents") => void;
  /** the conversation chosen in the navigation (App owns the choice) */
  conversationId?: string | null;
  onConversationChange?: (id: string | null) => void;
  /** the recent-chats list may have changed */
  onListChanged?: () => void;
}) {
  const [current, setCurrent] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [styleNotice, setStyleNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [progressId, setProgressId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [savingReport, setSavingReport] = useState<string | null>(null);
  const [reportNotice, setReportNotice] = useState<Record<string, string>>({});
  const [evidence, setEvidence] = useState<{ messageId: string; index: number } | null>(null);
  const [models, setModels] = useState<ChatModels | null>(null);
  const [model, setModel] = useState<ModelChoice | null>(null);
  const [recent, setRecent] = useState<ConversationSummary[]>([]);

  const [recordsOpen, setRecordsOpen] = useState(false);
  const [recordsKind, setRecordsKind] = useState<"deliverable" | "finding" | "risk" | "stakeholder">("deliverable");
  const [recordsResults, setRecordsResults] = useState<StructuredSearchResult[]>([]);
  const [recordsFailure, setRecordsFailure] = useState<ApiError | null>(null);
  const [recordsSearched, setRecordsSearched] = useState(false);

  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;

  // ------------------------------------------------------ request ownership
  //
  // `owned` is the conversation the screen currently belongs to, held in a ref
  // so it can be read synchronously after an await. A response whose ticket
  // no longer matches is DROPPED, not deferred and not reordered: the reader
  // has moved on, and a late answer under the wrong question is worse than no
  // answer at all. The server has persisted it either way.
  const owned = useRef<string | null>(null);
  // A ref, not state: in a fresh chat there is an await (creating the
  // conversation) before anything else is set, and a double-click there
  // created two conversations and spent two answers.
  const sending = useRef(false);
  // The id this view chose itself (a new conversation), so the navigation
  // echoing it back does not reload a transcript that is being written.
  const chosenHere = useRef<string | null>(null);

  const asking = pending !== null;
  const waitingHere = pending !== null && pending.conversationId === current;

  // -------------------------------------------------------------- engines
  useEffect(() => {
    let cancelled = false;
    void api.chatModels().then((r) => {
      if (cancelled || !r.ok) return;
      setModels(r.data);
      setModel(r.data.default);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const claude = model === "claude";

  const refreshRecent = useCallback(async () => {
    const r = await api.conversations(3);
    if (r.ok) setRecent(r.data.conversations);
  }, []);

  const listChanged = useCallback(() => {
    onListChanged?.();
    void refreshRecent();
  }, [onListChanged, refreshRecent]);

  useEffect(() => {
    void refreshRecent();
  }, [refreshRecent]);

  // ------------------------------------------------------------- opening
  const open = useCallback(async (id: string) => {
    owned.current = id;
    setCurrent(id);
    setEvidence(null);
    setFailure(null);
    const r = await api.conversation(id);
    // Two quick clicks between conversations: without this, the SLOWER
    // response wins and paints its transcript under the other name.
    if (owned.current !== id) return;
    if (r.ok) {
      setMessages(r.data.messages);
      setTitle(r.data.conversation.title);
    } else setFailure(r.error);
  }, []);

  const reset = useCallback(() => {
    owned.current = null;
    setCurrent(null);
    setTitle(null);
    setMessages([]);
    setEvidence(null);
    setFailure(null);
  }, []);

  // The navigation chose a conversation (or "New chat", which is null).
  useEffect(() => {
    if (conversationId === chosenHere.current && conversationId === current) return;
    if (conversationId === null) {
      if (current !== null) reset();
      return;
    }
    if (conversationId !== current) void open(conversationId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const select = useCallback(
    (id: string | null) => {
      chosenHere.current = id;
      onConversationChange?.(id);
    },
    [onConversationChange],
  );

  // ------------------------------------------------------------- timing
  useEffect(() => {
    if (!asking) return;
    setElapsed(0);
    const started = Date.now();
    const t = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [asking]);

  // The old route reports progress by polling; the stream reports it itself.
  useEffect(() => {
    if (!progressId) {
      setProgress(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      const r = await api.progress(progressId);
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
    const el = bottom.current;
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "end" });
  }, [messages.length, pending?.text, waitingHere]);

  // --------------------------------------------------------------- asking
  const send = useCallback(
    async (raw: string, opts: SendOptions = {}) => {
      const text = raw.trim();
      if ((!text && !opts.explainOf) || pendingRef.current || sending.current) return;
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
        setTitle(created.data.title || null);
        setMessages([]);
        select(id);
      }

      // The tier: a written answer when Claude answers; on the local engine a
      // quotation, unless the reader asked for a review, which needs writing.
      let tier: AnswerTier = opts.tier ?? (claude ? "generated" : "extract");
      if (!opts.tier && !claude && isReviewRequest(text)) {
        tier = "generated";
        setStyleNotice(
          "This review was answered as a grounded written explanation; a quotation only returns verbatim text.",
        );
      }

      const conversation = id;
      const tailAtRequest = messages.length > 0 ? messages[messages.length - 1].id : null;
      const first: Pending = {
        conversationId: conversation,
        question: opts.explainOf ? null : text,
        turnId: null,
        steps: [],
        text: "",
        verification: null,
        stopping: false,
        legacy: false,
      };
      setPending(first);
      if (opts.explainOf) setExplainingId(opts.explainOf);
      else setQuestion("");

      const update = (fn: (p: Pending) => Pending) =>
        setPending((p) => (p && p.conversationId === conversation ? fn(p) : p));

      const body: Partial<AskRequest> = {
        question: text,
        tier,
        ...(opts.explainOf ? { explain_of: opts.explainOf } : {}),
        ...(model ? { model } : {}),
      };
      const controller = new AbortController();
      abort.current = controller;
      let outcome: StreamOutcome = await askStream(conversation, body, {
        signal: controller.signal,
        onEvent: (e) => {
          if (e.event === "turn") update((p) => ({ ...p, turnId: e.data.turn_id }));
          else if (e.event === "step")
            update((p) => ({
              ...p,
              steps: [...p.steps.map((s) => ({ ...s, done: true })), e.data],
            }));
          else if (e.event === "delta") update((p) => ({ ...p, text: p.text + e.data.text }));
          else if (e.event === "verification") update((p) => ({ ...p, verification: e.data }));
        },
      });

      if (outcome.kind === "unsupported") {
        // An older backend: ask the plain route and poll its progress.
        update((p) => ({ ...p, legacy: true }));
        const ticket = crypto.randomUUID();
        setProgressId(ticket);
        const r = await api.ask(conversation, { ...body, progress_id: ticket });
        setProgressId(null);
        outcome = r.ok
          ? { kind: "done", result: r.data }
          : { kind: "failed", disconnected: r.disconnected, error: r.error };
      }

      abort.current = null;
      sending.current = false;
      setPending((p) => (p && p.conversationId === conversation ? null : p));
      if (opts.explainOf) setExplainingId((e) => (e === opts.explainOf ? null : e));

      // Dropped: the reader is reading a different conversation now. Both
      // turns are persisted server-side and appear when this one is reopened.
      if (owned.current !== conversation) return;

      if (outcome.kind === "failed") {
        setFailure(outcome.error);
        if (!opts.explainOf) setQuestion(text); // give the question back
        return;
      }
      if (outcome.kind === "aborted") {
        // Stopped before the server answered: whatever it stored is the record.
        void open(conversation);
        listChanged();
        return;
      }
      if (outcome.kind !== "done") return;
      const result = outcome.result;
      if (result.conversation?.title) setTitle(result.conversation.title);
      if (opts.explainOf) {
        // The explanation belongs under the answer it explains only if
        // nothing else arrived in the meantime.
        setMessages((m) => {
          const tail = m.length > 0 ? m[m.length - 1].id : null;
          if (tail !== tailAtRequest) return m;
          return appendUnseen(m, [result.assistant_message]);
        });
      } else {
        setMessages((m) => appendUnseen(m, [result.user_message, result.assistant_message]));
      }
      listChanged();
    },
    [current, claude, model, messages, open, select, listChanged],
  );

  const stop = useCallback(async () => {
    const p = pendingRef.current;
    if (!p || p.stopping) return;
    setPending((x) => (x ? { ...x, stopping: true } : x));
    if (p.turnId) {
      const r = await api.cancelTurn(p.conversationId, p.turnId);
      // The server finishes the turn as "stopped" and the stream ends with it.
      // If the route cannot be reached, closing the connection stops it too.
      if (r.ok) {
        window.setTimeout(() => {
          if (pendingRef.current?.turnId === p.turnId) abort.current?.abort();
        }, 5000);
        return;
      }
    }
    abort.current?.abort();
  }, []);

  const saveReport = useCallback(async (messageId: string) => {
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
    // The route refuses a message that cites nothing. Saying so is the point.
    setReportNotice((n) => ({ ...n, [messageId]: r.error.message }));
  }, []);

  const searchRecords = useCallback(async () => {
    const query = question.trim();
    if (!query) return;
    setRecordsSearched(true);
    setRecordsFailure(null);
    const result = await structuredSearch(query, recordsKind);
    if (result.ok) setRecordsResults(result.data.results);
    else {
      setRecordsResults([]);
      setRecordsFailure(result.error);
    }
  }, [question, recordsKind]);

  const startNew = useCallback(() => {
    reset();
    select(null);
  }, [reset, select]);

  // -------------------------------------------------------- derived views
  const offline = connection.state === "offline";

  const evidenceMessage = evidence ? messages.find((m) => m.id === evidence.messageId) : undefined;
  const evidenceSources = evidenceMessage ? sourcesOf(viewFromMessage(evidenceMessage)) : [];

  /** The question an answer came from: the last user turn before it. */
  const userTurnBefore = (messageId: string): Message | undefined => {
    const index = messages.findIndex((m) => m.id === messageId);
    for (let i = index - 1; i >= 0; i -= 1) if (messages[i].role === "user") return messages[i];
    return undefined;
  };
  // The evidence panel wants what retrieval RAN (the resolved question); the
  // comparison notice wants what the reader TYPED.
  const evidenceQuestion = evidenceMessage
    ? (() => {
        const u = userTurnBefore(evidenceMessage.id);
        return u ? u.resolved_question ?? u.text ?? undefined : undefined;
      })()
    : undefined;
  const questionFor = (messageId: string): string | null => {
    const u = userTurnBefore(messageId);
    return u ? u.text ?? u.resolved_question ?? null : null;
  };

  /** A refused Tier 2 upgrade is reported on the answer it was an upgrade
   *  of, never drawn as a peer refusal of the same question. */
  const isFailedUpgrade = (m: Message) =>
    Boolean(m.explains_id) &&
    (m.answer_type === "insufficient_evidence" || m.answer_type === "model_unavailable");
  const present = new Set(messages.map((m) => m.id));
  const failedUpgrades = new Map<string, Message>();
  const attachedElsewhere = new Set<string>();
  for (const m of messages) {
    if (!isFailedUpgrade(m) || !present.has(m.explains_id!)) continue;
    failedUpgrades.set(m.explains_id!, m);
    attachedElsewhere.add(m.id);
  }
  const explainedIds = new Set(
    messages
      .filter((m) => m.answer_type === "generated")
      .map((m) => m.explains_id)
      .filter((x): x is string => Boolean(x)),
  );
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

  /** What the conversation is about, from the sources the latest answer used. */
  const talkingAbout = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const names = Array.from(
        new Set((messages[i].sources ?? []).filter((s) => s.cited).map((s) => s.display_name)),
      );
      if (names.length > 0) return names;
    }
    return [] as string[];
  }, [messages]);

  const explainNote = claude
    ? "Claude writes it from these passages, usually within half a minute — the quotation above is already the answer."
    : undefined;
  const explainingNote = "The explanation is written below as it arrives.";

  const footer = (
    <p className="mt-2 text-center text-xs text-slateish-500">
      AI can be wrong. Open a source to check the page it came from.
      {model === "claude" &&
        " Claude writes these answers: your question and the passages it needs are sent to it."}
      {model === "local" && " The local model writes these answers; nothing you type leaves this machine."}
    </p>
  );

  const recordsPanel = recordsOpen && (
    <div className="mt-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-slateish-300">Workflow records</span>
        <select
          aria-label="Structured search type"
          value={recordsKind}
          onChange={(e) => {
            setRecordsKind(e.target.value as typeof recordsKind);
            setRecordsSearched(false);
            setRecordsFailure(null);
            setRecordsResults([]);
          }}
          className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1 text-xs text-slateish-300"
        >
          <option value="deliverable">Deliverables / WBS</option>
          <option value="finding">Review findings</option>
          <option value="risk">Risks</option>
          <option value="stakeholder">Stakeholders</option>
        </select>
        <button
          type="button"
          onClick={() => void searchRecords()}
          disabled={!question.trim()}
          className="rounded-[var(--radius-xs)] border border-signal-500/50 px-2 py-1 text-xs text-signal-300 disabled:opacity-50"
        >
          Search records
        </button>
        <button
          type="button"
          onClick={() => setRecordsOpen(false)}
          className="ms-auto text-xs text-slateish-500 underline"
        >
          Close
        </button>
      </div>
      <p className="mt-1 text-xs text-slateish-500">
        Searches for the words in the box. You can also type <span className="font-mono">/records</span> and a phrase.
      </p>
      {recordsFailure && (
        <div className="mt-2">
          <ErrorState error={recordsFailure} />
        </div>
      )}
      {recordsSearched && !recordsFailure && recordsResults.length === 0 && (
        <ZeroResultsState message={`No matching ${recordsKind} found for '${question.trim()}'.`} />
      )}
      {recordsResults.length > 0 && (
        <div aria-label="Structured search results" className="mt-2 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-signal-400">
            Workflow records — not page-cited evidence
          </p>
          {recordsResults.map((item) => (
            <div
              key={`${item.kind}-${item.id}`}
              className="rounded-[var(--radius-xs)] border border-ink-700 px-2 py-1.5 text-xs text-slateish-300"
            >
              <span className="me-2 rounded-full bg-ink-700 px-1.5 py-0.5 text-signal-300">{item.kind}</span>
              {item.label}
              {item.wbs_code ? ` · WBS ${item.wbs_code}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const composer = (hero: boolean) => (
    <>
      <Composer
        value={question}
        onChange={(v) => {
          setQuestion(v);
          setRecordsSearched(false);
          setRecordsFailure(null);
          setRecordsResults([]);
        }}
        onSubmit={() => void send(question)}
        disabled={offline}
        busy={asking}
        hero={hero}
        placeholder={
          hero
            ? "Ask anything, about your documents, a standard, or engineering in general"
            : "Ask a follow-up"
        }
        models={models}
        model={model}
        onModelChange={setModel}
        onRecords={() => setRecordsOpen(true)}
        onUpload={onNavigate ? () => onNavigate("documents") : undefined}
      />
      {!claude && isReviewRequest(question) && (
        <p role="note" className="mt-2 text-xs text-slateish-400">
          A review needs a written answer, so this one will be written rather than quoted.
        </p>
      )}
      {styleNotice && (
        <p role="status" className="mt-2 text-xs text-signal-300">
          {styleNotice}
        </p>
      )}
      {recordsPanel}
      {footer}
    </>
  );

  const empty = messages.length === 0 && !waitingHere && current === null;

  const thread = (
    <>
      {messages.map((m) =>
        m.role === "user" ? (
          <UserMessage key={m.id} message={m} onEdit={(t) => setQuestion(t)} />
        ) : attachedElsewhere.has(m.id) ? null : (
          <AssistantAnswer
            key={m.id}
            message={m}
            question={questionFor(m.id)}
            activeSource={evidence?.messageId === m.id ? evidence.index : null}
            onSelectSource={(i) => setEvidence({ messageId: m.id, index: i })}
            explainsEarlier={Boolean(m.explains_id)}
            onExplain={
              m.answer_type === "extract" && !explainedIds.has(m.id)
                ? () => void send("", { explainOf: m.id, tier: "generated" })
                : undefined
            }
            explaining={explainingId === m.id}
            explainSeconds={explainingId === m.id ? elapsed : undefined}
            explainNote={explainNote}
            explainingNote={explainingNote}
            onSaveReport={
              // Only an ANSWER can be frozen; a refusal has no evidence.
              m.answer_type === "extract" || m.answer_type === "generated"
                ? () => void saveReport(m.id)
                : undefined
            }
            savingReport={savingReport === m.id}
            reportNotice={reportNotice[m.id] || null}
            upgradeFailure={upgradeFailureFor(m.id)}
            onAsk={(t) => void send(t)}
            onRetry={(() => {
              const u = userTurnBefore(m.id);
              if (!u?.text || m.explains_id) return undefined;
              const tier: AnswerTier | undefined = m.answer_type === "extract" ? "extract" : undefined;
              return () => void send(u.text!, { tier });
            })()}
            onExactWording={(() => {
              const u = userTurnBefore(m.id);
              const q = u?.resolved_question ?? u?.text;
              return q ? () => void send(`/quote ${q}`) : undefined;
            })()}
            busy={asking}
          />
        ),
      )}

      {waitingHere && pending && (
        <>
          {pending.question &&
            !messages.some((m) => m.role === "user" && m.text === pending.question && m === messages[messages.length - 1]) && (
              <UserMessage message={{ text: pending.question, carried_terms: [] }} />
            )}
          {pending.legacy ? (
            <LocalWork elapsed={elapsed} progress={progress} />
          ) : (
            <StreamingAnswer
              steps={pending.steps}
              text={pending.text}
              verification={pending.verification}
              onStop={() => void stop()}
              stopping={pending.stopping}
              seconds={elapsed}
            />
          )}
        </>
      )}

    </>
  );


  return (
    <div className="flex h-[calc(100vh-9rem)] min-h-0 flex-col gap-4 lg:h-[calc(100vh-3rem)] lg:flex-row">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {!empty && (
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700 pb-3">
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <h1 className="truncate text-sm font-semibold text-slateish-100">{title ?? "New chat"}</h1>
              {talkingAbout.length > 0 && (
                <span className="rounded-[var(--radius-full)] border border-ink-600 px-2.5 py-0.5 text-xs text-slateish-400">
                  Talking about: <span className="text-slateish-200">{talkingAbout[0]}</span>
                  {talkingAbout.length > 1 && ` + ${talkingAbout.length - 1} more`}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={startNew}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1.5 text-xs text-slateish-300 hover:border-signal-500/50 hover:bg-ink-700"
            >
              New chat
            </button>
          </header>
        )}

        {/* THE COMPOSER KEEPS ITS PLACE IN THE TREE. The first question moves
            it from the middle of the empty screen to the foot of the thread;
            rendered at the same position both times, it is the same element,
            so the reader's focus and a failed question's text survive the
            move instead of landing in a box that was just replaced. */}
        <div
          className={
            empty
              ? "mx-auto flex w-full max-w-[820px] flex-col justify-end px-2 pt-10 sm:flex-1"
              : "min-h-0 flex-1 overflow-y-auto"
          }
        >
          {empty ? (
            <ChatEmptyHeading />
          ) : (
            <div className="mx-auto w-full max-w-[780px] space-y-6 px-1 py-6">
              {messages.length === 0 && !waitingHere && (
                <p className="text-center text-sm text-slateish-500">Ask your first question below.</p>
              )}
              {thread}
              {failure && <ErrorState error={failure} />}
              <div ref={bottom} />
            </div>
          )}
        </div>
        <div
          className={
            empty
              ? "mx-auto w-full max-w-[820px] shrink-0 px-2"
              : "mx-auto w-full max-w-[780px] shrink-0 pb-2 pt-2"
          }
        >
          {composer(empty)}
        </div>
        {empty && (
          <div className="mx-auto w-full max-w-[820px] px-2 pb-10 sm:flex-1">
            <ChatStarters
              onAsk={(t) => void send(t)}
              recent={recent}
              onOpen={(id) => {
                select(id);
                void open(id);
              }}
              disabled={offline || asking}
            />
            {failure && (
              <div className="mt-4">
                <ErrorState error={failure} />
              </div>
            )}
          </div>
        )}
      </section>

      {evidence && evidenceSources.length > 0 && (
        <EvidencePanel
          passages={evidenceSources}
          selected={Math.min(evidence.index, evidenceSources.length - 1)}
          onSelect={(i) => setEvidence({ messageId: evidence.messageId, index: i })}
          onClose={() => setEvidence(null)}
          question={evidenceQuestion}
        />
      )}
    </div>
  );
}
