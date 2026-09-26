/**
 * A drafted review comment, shown for an engineer to read, edit, copy - and
 * file.
 *
 * A DRAFT IS NOT A FINDING. Nothing is written anywhere until the engineer
 * presses "Add to comment sheet", and what is filed is the text in front of
 * them, edited or not, under their name. Undo is offered for as long as the
 * server allows it (the filer, a few minutes, nobody else has touched it);
 * after that the comment is changed on the review, like any other.
 */
import { useEffect, useState } from "react";

import type { ApiError, FiledComment } from "../../types/api";
import { plainText } from "./AnswerActions";

export type FileResult = { ok: true; data: FiledComment } | { ok: false; error: ApiError };
export type UndoResult = { ok: true } | { ok: false; error: ApiError };

type Filing =
  | { s: "idle" }
  | { s: "filing" }
  | { s: "filed"; result: FiledComment }
  | { s: "already" }
  | { s: "withdrawn" }
  | { s: "failed"; message: string };

export function DraftCommentCard({
  text,
  canFile = false,
  alreadyFiled = false,
  onFile,
  onUndo,
  onOpenReview,
}: {
  text: string;
  /** the draft names a document it can be filed on */
  canFile?: boolean;
  /** reopened: this draft was filed before */
  alreadyFiled?: boolean;
  onFile?: (text: string) => Promise<FileResult>;
  onUndo?: (findingId: string) => Promise<UndoResult>;
  onOpenReview?: (reviewRunId: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => plainText(text));
  const [copied, setCopied] = useState(false);
  const [filing, setFiling] = useState<Filing>(alreadyFiled ? { s: "already" } : { s: "idle" });
  const [undoOpen, setUndoOpen] = useState(false);

  // Undo is offered only until the server's own deadline.
  useEffect(() => {
    if (filing.s !== "filed") return;
    const left = new Date(filing.result.undo_until).getTime() - Date.now();
    setUndoOpen(left > 0);
    if (left <= 0) return;
    const t = window.setTimeout(() => setUndoOpen(false), left);
    return () => window.clearTimeout(t);
  }, [filing]);

  const file = async () => {
    if (!onFile) return;
    setFiling({ s: "filing" });
    const r = await onFile(value.trim());
    setFiling(r.ok ? { s: "filed", result: r.data } : { s: "failed", message: r.error.message });
    if (r.ok) setEditing(false);
  };

  const undo = async () => {
    if (!onUndo || filing.s !== "filed") return;
    const r = await onUndo(filing.result.finding_id);
    setFiling(r.ok ? { s: "withdrawn" } : { s: "failed", message: r.error.message });
  };

  const locked = filing.s === "filing" || filing.s === "filed" || filing.s === "already";

  return (
    <section
      aria-label="Draft comment"
      className="mt-2 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850"
    >
      <header className="flex items-center justify-between gap-2 border-b border-ink-700 px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-slateish-100">Draft comment</p>
          <span className="rounded-[var(--radius-full)] border border-warn-500/40 bg-warn-500/10 px-2 py-0.5 text-xs text-warn-500">
            Needs an engineer
          </span>
        </div>
        {!locked && (
          <button
            type="button"
            aria-pressed={editing}
            onClick={() => setEditing((e) => !e)}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-200 hover:bg-ink-700"
          >
            {editing ? "Done" : "Edit"}
          </button>
        )}
      </header>
      {editing && !locked ? (
        <label className="block px-3.5 py-2.5">
          <span className="sr-only">Draft comment text</span>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={5}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2.5 py-2 text-sm text-slateish-100"
          />
        </label>
      ) : (
        <p className="whitespace-pre-wrap px-3.5 py-2.5 text-[15px] leading-7 text-slateish-200">{value}</p>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-700 px-3.5 py-2">
        <div className="flex items-center gap-2">
          {canFile && onFile && (filing.s === "idle" || filing.s === "failed" || filing.s === "withdrawn" || filing.s === "filing") && (
            <button
              type="button"
              onClick={() => void file()}
              disabled={filing.s === "filing" || !value.trim()}
              className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1.5 text-sm font-semibold text-ink-950 hover:bg-signal-400 disabled:opacity-50"
            >
              {filing.s === "filing" ? "Adding…" : "Add to comment sheet"}
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(value).then(
                () => setCopied(true),
                () => setCopied(false),
              );
            }}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-200 hover:bg-ink-700"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        {(filing.s === "idle" || filing.s === "filing") && (
          <p className="text-xs text-slateish-500">
            {canFile
              ? "Not added to any review yet. Read it against the sources before you add it."
              : "Not added to any review yet. It names no document it could be filed on, so copy it where it belongs."}
          </p>
        )}
      </footer>
      {filing.s === "filed" && (
        <p role="status" className="border-t border-ink-700 bg-signal-500/[0.06] px-3.5 py-2 text-xs text-slateish-200">
          <span aria-hidden className="text-signal-400">✓ </span>
          {filing.result.review_run_id
            ? `Added to the comment sheet for ${filing.result.document_name}, under your name.`
            : `Added to the findings for ${filing.result.document_name}. It has no review run yet, so it is on no comment sheet until one is run.`}
          {filing.result.review_run_id && onOpenReview && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => onOpenReview(filing.result.review_run_id!)}
                className="min-h-0 text-signal-400 underline"
              >
                Open review
              </button>
            </>
          )}
          {undoOpen && onUndo && (
            <>
              {" "}
              <button type="button" onClick={() => void undo()} className="min-h-0 font-semibold text-signal-400 underline">
                Undo
              </button>
            </>
          )}
        </p>
      )}
      {filing.s === "already" && (
        <p role="status" className="border-t border-ink-700 px-3.5 py-2 text-xs text-slateish-400">
          <span aria-hidden className="text-signal-400">✓ </span>
          Added to the comment sheet earlier. Change it on the review.
        </p>
      )}
      {filing.s === "withdrawn" && (
        <p role="status" className="border-t border-ink-700 px-3.5 py-2 text-xs text-slateish-400">
          Withdrawn. It is no longer on the comment sheet.
        </p>
      )}
      {filing.s === "failed" && (
        <p role="alert" className="border-t border-ink-700 px-3.5 py-2 text-xs text-danger-500">
          {filing.message}
        </p>
      )}
    </section>
  );
}
