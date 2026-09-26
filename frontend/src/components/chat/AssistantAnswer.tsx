/**
 * One assistant turn on the Chat screen.
 *
 * WHAT KIND OF ANSWER IT IS DECIDES HOW IT LOOKS, and the kind is the
 * server's (`answer_type`, `answer_kind`), never inferred from the text:
 *
 *   * from the documents - the existing answer card, unchanged in what it
 *     claims: a quotation is labelled the document's words (or OCR), a
 *     written answer the model's words, with every warning it carried;
 *   * general knowledge - plain text under a line that says it is general
 *     knowledge, not from your documents, and with no source numbers at all;
 *   * a draft comment - a card an engineer edits; nothing is filed;
 *   * stopped - what the reader had been shown, marked as stopped.
 *
 * Above every answer, the grey used-line; below it, what can be done next.
 */
import type { ReactNode } from "react";

import type { Message } from "../../types/api";
import { AnswerActions, RewriteChips, SuggestionChips } from "./AnswerActions";
import { AnswerCard, viewFromMessage, type UpgradeFailure } from "./AnswerCard";
import { DraftCommentCard, type FileResult, type UndoResult } from "./DraftCommentCard";
import { Markdown } from "./Markdown";
import { ProgressSteps, UsedLine } from "./UsedLine";
import type { ChatStep, ChatVerification } from "../../types/api";

const DOCUMENT_TYPES = new Set(["extract", "generated", "insufficient_evidence", "model_unavailable", "metadata"]);

export function isGeneral(m: Pick<Message, "answer_type">): boolean {
  return m.answer_type === "general";
}

function Notices({ notices }: { notices: string[] }) {
  if (notices.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1" aria-label="Notes on this answer">
      {notices.map((n) => (
        <li
          key={n}
          className="rounded-[var(--radius-sm)] border border-info-500/30 bg-info-500/[0.06] px-2.5 py-1.5 text-xs text-slateish-300"
        >
          {n}
        </li>
      ))}
    </ul>
  );
}

export function AssistantAnswer({
  message: m,
  question,
  activeSource,
  onSelectSource,
  onExplain,
  explaining,
  explainSeconds,
  explainNote,
  explainingNote,
  explainsEarlier,
  onSaveReport,
  savingReport,
  reportNotice,
  upgradeFailure,
  onAsk,
  onRetry,
  onExactWording,
  busy,
  onFeedback,
  onFileComment,
  onUndoComment,
  onOpenReview,
}: {
  message: Message;
  question: string | null;
  activeSource: number | null;
  onSelectSource: (i: number) => void;
  onExplain?: () => void;
  explaining?: boolean;
  explainSeconds?: number;
  explainNote?: string;
  explainingNote?: string;
  explainsEarlier?: boolean;
  onSaveReport?: () => void;
  savingReport?: boolean;
  reportNotice?: string | null;
  upgradeFailure?: UpgradeFailure | null;
  /** send a follow-up in the reader's name */
  onAsk: (text: string) => void;
  onRetry?: () => void;
  onExactWording?: () => void;
  /** an answer is being written: follow-ups wait */
  busy?: boolean;
  onFeedback?: (helpful: boolean) => Promise<boolean>;
  onFileComment?: (text: string) => Promise<FileResult>;
  onUndoComment?: (findingId: string) => Promise<UndoResult>;
  onOpenReview?: (reviewRunId: string) => void;
}) {
  const view = viewFromMessage(m);
  const type = m.answer_type;
  const draftText = typeof m.draft?.text === "string" ? (m.draft.text as string) : null;
  const withheld = view.withheld;

  let body: ReactNode;
  if (withheld) {
    body = <AnswerCard view={view} activeSource={null} onSelectSource={() => undefined} />;
  } else if (draftText) {
    body = (
      <>
        <p className="text-[15px] text-slateish-200">
          Here is a draft comment. Edit it as you need; it is not added anywhere until you use it.
        </p>
        <DraftCommentCard
          text={draftText}
          canFile={Array.isArray(m.draft?.source_ids) && (m.draft!.source_ids as unknown[]).length > 0}
          alreadyFiled={Boolean(m.filed_comment)}
          onFile={onFileComment}
          onUndo={onUndoComment}
          onOpenReview={onOpenReview}
        />
      </>
    );
  } else if (type === "general" || type === "records") {
    body = <Markdown text={m.text ?? ""} />;
  } else if (type === "cancelled") {
    body = (
      <>
        {m.text ? <Markdown text={m.text} /> : null}
        <p className="mt-2 text-xs text-slateish-500">
          You stopped this answer. {m.text ? "The part above is what had been shown." : "Nothing had been shown yet."}
        </p>
      </>
    );
  } else {
    body = (
      <AnswerCard
        view={view}
        plain
        presentationSources={m.sources}
        reportable={Boolean(onSaveReport)}
        activeSource={activeSource}
        onSelectSource={onSelectSource}
        explainsEarlier={explainsEarlier}
        question={question}
        onExplain={onExplain}
        explaining={explaining}
        explainSeconds={explainSeconds}
        explainNote={explainNote}
        explainingNote={explainingNote}
        upgradeFailure={upgradeFailure}
      />
    );
  }

  const answered = !withheld && type !== "guidance" && type !== null;
  const documentAnswer = type != null && DOCUMENT_TYPES.has(type);
  return (
    <article aria-label="Answer" className="w-full">
      {!withheld && (
        <UsedLine text={m.used_line} verification={m.verification} steps={m.steps} />
      )}
      {body}
      {!withheld && <Notices notices={m.notices ?? []} />}
      {answered && (
        <AnswerActions
          text={draftText ? null : m.text}
          onRetry={onRetry}
          onExactWording={documentAnswer && type !== "extract" && type !== "metadata" ? onExactWording : undefined}
          onSaveReport={onSaveReport}
          savingReport={savingReport}
          reportNotice={reportNotice}
          disabled={busy}
          feedback={m.feedback ?? null}
          onFeedback={onFeedback}
        />
      )}
      {!withheld && type === "general" && !draftText && m.answer_kind !== "action" && (
        <RewriteChips onAsk={onAsk} disabled={busy} />
      )}
      {!withheld && (type === "extract" || type === "generated") && !draftText && (
        <SuggestionChips suggestions={m.suggestions ?? []} onAsk={onAsk} disabled={busy} />
      )}
    </article>
  );
}

/** The answer while it is being written: real steps, the text so far, Stop. */
export function StreamingAnswer({
  steps,
  text,
  verification,
  onStop,
  stopping,
  seconds,
}: {
  steps: ChatStep[];
  text: string;
  verification: ChatVerification | null;
  onStop: () => void;
  stopping: boolean;
  seconds: number;
}) {
  return (
    <article aria-label="Answer being written" aria-busy="true" className="w-full">
      <ProgressSteps steps={steps} />
      {steps.length === 0 && !text && (
        <p className="mb-2 text-xs text-slateish-500" role="status">
          Starting · {seconds}s
        </p>
      )}
      {verification && (
        <p className="mb-2 text-xs text-slateish-500">
          {verification.verified} of {verification.total} points found on the page so far
        </p>
      )}
      {text && (
        <div className="relative">
          <Markdown text={text} />
          <span aria-hidden className="ms-0.5 inline-block h-4 w-2 translate-y-0.5 bg-signal-500 motion-safe:animate-pulse" />
        </div>
      )}
      <button
        type="button"
        onClick={onStop}
        disabled={stopping}
        className="mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-full)] border border-ink-600 px-3 py-1 text-xs text-slateish-200 hover:border-danger-500/50 hover:bg-ink-800 disabled:opacity-60"
      >
        <span aria-hidden>■</span> {stopping ? "Stopping…" : "Stop"}
      </button>
    </article>
  );
}
