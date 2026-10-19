/**
 * OWNER: builder B. D3: "Keep all remaining comments (N)", one confirm, then
 * Undo. N is `ReviewNumbers.remainingToKeep` (the same rule as
 * `useCrsDecisions.remaining`, which `acceptAll` keeps): ordinary comments
 * without a decision. A "Needs you" comment is never kept this way; each
 * one is opened and decided on its own.
 */
import { useState } from "react";

export interface KeepAllRemainingProps {
  /** `numbers.remainingToKeep`. */
  count: number;
  /** Keeps them; returns how many were kept. */
  onKeep: () => number;
  /** Undo is on offer (the last "keep all" can still be taken back). */
  canUndo: boolean;
  onUndo: () => void;
}

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50";

export function KeepAllRemaining({ count, onKeep, canUndo, onUndo }: KeepAllRemainingProps) {
  const [asking, setAsking] = useState(false);
  const [kept, setKept] = useState<number | null>(null);
  if (canUndo && kept !== null) {
    return (
      <p role="status" data-testid="ws-keep-all-done" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
        {kept} {kept === 1 ? "comment" : "comments"} kept. They save once Undo is gone.
        <button type="button" onClick={() => { onUndo(); setKept(null); }} className={`${BUTTON} border-ink-600 text-slateish-100`}>
          Undo
        </button>
      </p>
    );
  }
  if (count === 0) return null;
  if (asking) {
    return (
      <div role="group" aria-label="Keep all remaining comments?" data-testid="ws-keep-all-ask"
        className="flex flex-wrap items-center gap-2 text-sm text-slateish-200">
        <span>
          {count} {count === 1 ? "comment" : "comments"} will be kept as written. Comments marked &quot;Needs you&quot; are
          not touched.
        </span>
        <button type="button" onClick={() => { setKept(onKeep()); setAsking(false); }}
          className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>
          Yes, keep them
        </button>
        <button type="button" onClick={() => setAsking(false)} className={`${BUTTON} border-ink-600 text-slateish-100`}>Cancel</button>
      </div>
    );
  }
  return (
    <button type="button" data-testid="ws-keep-all" onClick={() => setAsking(true)}
      className={`${BUTTON} border-ink-600 text-slateish-100`}>
      Keep all remaining comments (<span data-count="remainingToKeep">{count.toLocaleString()}</span>)
    </button>
  );
}
