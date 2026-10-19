/**
 * v2.1 (N1): "You have decisions that are not saved yet", asked in the page
 * (not a browser pop-up), at the top of the screen, whenever the reader
 * tries to leave the workspace with something unsaved. See useLeaveGuard.
 */
import { type PendingLeave, leaveWords } from "./useLeaveGuard";

export function LeaveConfirm({ pending, onLeave, onStay }: {
  pending: PendingLeave | null; onLeave: () => void; onStay: () => void;
}) {
  if (!pending) return null;
  const words = leaveWords(pending.kind, pending.count);
  const button = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm font-medium";
  return (
    <div
      role="alertdialog" aria-labelledby="leave-confirm-text" data-testid="leave-confirm"
      className="sticky top-0 z-40 mb-4 rounded-[var(--radius-md)] border border-warn-500/50 bg-ink-850 px-4 py-3 shadow-lg"
    >
      <p id="leave-confirm-text" className="text-sm text-slateish-100">{words.text}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {/* Staying is the safe choice, so the keyboard starts there. */}
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <button type="button" autoFocus onClick={onStay} className={`${button} border-signal-500 bg-signal-500/15 text-slateish-100`}>
          Stay here
        </button>
        <button type="button" onClick={onLeave} className={`${button} border-ink-600 text-slateish-200 hover:border-ink-500`}>
          {words.leave}
        </button>
      </div>
    </div>
  );
}
