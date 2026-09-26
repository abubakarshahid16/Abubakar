/**
 * What the reader can do with an answer, in one quiet row: Copy, Try again,
 * Exact wording (the document's own words, "/quote"), Save as PDF - then the
 * ways to reshape it (Rewrite as:) and the next questions worth asking.
 *
 * Each control is offered only where it does something real. "Save as PDF" is
 * absent on an answer that cites nothing, because the report route refuses
 * one (NotReportable) and a button that fails every time is worse than none.
 */
import { useState } from "react";

const quiet =
  "rounded-[var(--radius-sm)] px-2 py-1 text-xs text-slateish-400 motion-safe:transition-colors hover:bg-ink-800 hover:text-slateish-200 disabled:opacity-50";

const chip =
  "rounded-[var(--radius-full)] border border-ink-600 px-3 py-1 text-xs text-slateish-200 motion-safe:transition-colors hover:border-signal-500/50 hover:bg-ink-800 disabled:opacity-50";

/** The answer's text with its source markers removed, for the clipboard. */
export function plainText(text: string): string {
  return text
    .replace(/\s*\[S\d+(?:\s*,\s*S?\d+)*(?:\s+"[^"\n]*")?\]/g, "")
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .trim();
}

export function AnswerActions({
  text,
  onRetry,
  onExactWording,
  onSaveReport,
  savingReport,
  reportNotice,
  disabled,
  feedback = null,
  onFeedback,
}: {
  text: string | null;
  onRetry?: () => void;
  onExactWording?: () => void;
  onSaveReport?: () => void;
  savingReport?: boolean;
  reportNotice?: string | null;
  disabled?: boolean;
  /** the reader's own "Was this right?", if they have answered it */
  feedback?: boolean | null;
  onFeedback?: (helpful: boolean) => Promise<boolean>;
}) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const [rated, setRated] = useState<boolean | null>(feedback);
  const [rateFailed, setRateFailed] = useState(false);
  const rate = async (helpful: boolean) => {
    if (!onFeedback) return;
    const before = rated;
    setRated(helpful);
    setRateFailed(false);
    // Shown as chosen at once; put back if the server did not keep it.
    if (!(await onFeedback(helpful))) {
      setRated(before);
      setRateFailed(true);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plainText(text ?? ""));
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
    window.setTimeout(() => setCopied(null), 2000);
  };
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Answer actions">
        {text && (
          <button type="button" className={quiet} onClick={() => void copy()}>
            {copied === "ok" ? "Copied" : copied === "failed" ? "Could not copy" : "Copy"}
          </button>
        )}
        {onRetry && (
          <button type="button" className={quiet} onClick={onRetry} disabled={disabled}>
            Try again
          </button>
        )}
        {onExactWording && (
          <button type="button" className={quiet} onClick={onExactWording} disabled={disabled}>
            Exact wording
          </button>
        )}
        {onSaveReport && (
          <button type="button" className={quiet} onClick={onSaveReport} disabled={savingReport}>
            {savingReport ? "Saving…" : "Save as PDF"}
          </button>
        )}
        {onFeedback && (
          <span className="ms-auto flex items-center gap-1 text-xs text-slateish-500" role="group" aria-label="Was this right?">
            Was this right?
            {([true, false] as const).map((v) => (
              <button
                key={String(v)}
                type="button"
                aria-pressed={rated === v}
                onClick={() => void rate(v)}
                className={[
                  "rounded-[var(--radius-sm)] border px-2 py-0.5 text-xs motion-safe:transition-colors",
                  rated === v
                    ? "border-signal-500/60 bg-signal-500/10 text-signal-300"
                    : "border-ink-600 text-slateish-300 hover:bg-ink-800",
                ].join(" ")}
              >
                {v ? "Yes" : "No"}
              </button>
            ))}
          </span>
        )}
      </div>
      {rateFailed && (
        <p className="mt-1 text-xs text-warn-500" role="status">
          That was not saved. Try again.
        </p>
      )}
      {reportNotice && (
        <p className="mt-1 text-xs text-warn-500" role="status">
          {reportNotice}
        </p>
      )}
    </div>
  );
}

/** How a general answer can be reshaped. Each is sent as the reader's own
 *  follow-up, so it is visible in the transcript and routed like any other. */
export const REWRITES: readonly { label: string; ask: string }[] = [
  { label: "Points", ask: "Give me that in points" },
  { label: "More detail", ask: "Give me that with more detail" },
  { label: "Shorter", ask: "Make that shorter" },
  { label: "For an engineer", ask: "Explain that for an engineer" },
  { label: "Check against my documents", ask: "Check that against my documents" },
];

export function RewriteChips({ onAsk, disabled }: { onAsk: (text: string) => void; disabled?: boolean }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span className="text-xs text-slateish-500">Rewrite as:</span>
      {REWRITES.map((r) => (
        <button key={r.label} type="button" className={chip} onClick={() => onAsk(r.ask)} disabled={disabled}>
          {r.label}
        </button>
      ))}
    </div>
  );
}

export function SuggestionChips({
  suggestions,
  onAsk,
  disabled,
}: {
  suggestions: string[];
  onAsk: (text: string) => void;
  disabled?: boolean;
}) {
  if (suggestions.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2" aria-label="Suggested next questions">
      {suggestions.map((s) => (
        <button key={s} type="button" className={chip} onClick={() => onAsk(s)} disabled={disabled}>
          {s}
        </button>
      ))}
    </div>
  );
}
