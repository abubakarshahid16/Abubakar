/**
 * v2.1 (N1): "You have decisions that are not saved yet", asked in the page
 * (not a browser pop-up), at the top of the screen, whenever the reader
 * tries to leave the workspace with something unsaved. See useLeaveGuard.
 *
 * v2.1 round 2: Escape means "Stay here", and the keyboard goes back to
 * where it was before the question opened. The question sits above the
 * evidence panel (that layer is z-[60]; this one is z-[70]), so it is never
 * hidden behind it on a narrow screen. "Save and leave" (when a save is
 * known) saves first and leaves only if the save worked.
 */
import { useEffect, useRef, useState } from "react";

import { type PendingLeave, leaveWords } from "./useLeaveGuard";

/** Above the evidence panel's layer (WorkspaceEvidence EVIDENCE_LAYER, z-[60]). */
export const LEAVE_CONFIRM_LAYER = "z-[70]";

export interface LeaveConfirmProps {
  pending: PendingLeave | null;
  onLeave: () => void;
  onStay: () => void;
  /** Save, then leave only if the save worked. No button without it. */
  onSaveAndLeave?: () => void | Promise<void>;
  /** True while "Save and leave" is saving. */
  saving?: boolean;
  /** Plain words when "Save and leave" could not save. */
  saveError?: string | null;
}

export function LeaveConfirm({ pending, ...rest }: LeaveConfirmProps) {
  if (!pending) return null;
  return <Question pending={pending} {...rest} />;
}

function Question({ pending, onLeave, onStay, onSaveAndLeave, saving = false, saveError = null }:
  LeaveConfirmProps & { pending: PendingLeave }) {
  const words = leaveWords(pending.kind, pending.count);
  // Where the keyboard was when the question opened (read before this
  // question takes it), so it goes back there afterwards.
  const [opener] = useState<Element | null>(() => (typeof document === "undefined" ? null : document.activeElement));
  const stayButton = useRef<HTMLButtonElement>(null);
  const stayRef = useRef(onStay);
  useEffect(() => { stayRef.current = onStay; }, [onStay]);

  useEffect(() => {
    // Staying is the safe choice, so the keyboard starts there.
    stayButton.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, [opener]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Escape answers this question only: nothing under it closes too.
      event.preventDefault();
      event.stopPropagation();
      stayRef.current();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  const button = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60";
  return (
    <div
      role="alertdialog" aria-labelledby="leave-confirm-text" data-testid="leave-confirm"
      className={`sticky top-0 ${LEAVE_CONFIRM_LAYER} mb-4 rounded-[var(--radius-md)] border border-warn-500/50 bg-ink-850 px-4 py-3 shadow-lg`}
    >
      <p id="leave-confirm-text" className="text-sm text-slateish-100">{words.text}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button ref={stayButton} type="button" onClick={onStay} disabled={saving}
          className={`${button} border-signal-500 bg-signal-500/15 text-slateish-100`}>
          Stay here
        </button>
        {onSaveAndLeave && (
          <button type="button" onClick={() => void onSaveAndLeave()} disabled={saving}
            className={`${button} border-ink-600 text-slateish-100 hover:border-ink-500`}>
            {saving ? "Saving..." : words.saveLeave}
          </button>
        )}
        <button type="button" onClick={onLeave} disabled={saving}
          className={`${button} border-ink-600 text-slateish-200 hover:border-ink-500`}>
          {words.leave}
        </button>
      </div>
      {saveError && <p role="alert" data-testid="leave-save-error" className="mt-2 text-sm text-red-400">{saveError}</p>}
    </div>
  );
}
