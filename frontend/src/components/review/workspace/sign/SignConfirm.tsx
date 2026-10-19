/**
 * OWNER: builder C (v2.1 gap S2). "Preview and confirm": the step between
 * pressing Sign and export and the contractor's copy being issued.
 *
 * It shows the comment sheet as the contractor will get it (the server's
 * own preview, `reviewsApi.previewCrs`, built by the same builder as the
 * file, drawn by the existing `CrsPreviewSheet` with the internal-only
 * columns and notes left out), one line with the counts ("12 comments,
 * final code 2, signed by Sam Lee"), then ONE button that issues.
 *
 * Nothing is issued until "Issue to contractor" is pressed. That button asks
 * `issueConfirmed(runId)` (workspace/useSignOff.ts), which runs the
 * on-screen sign-off's issuer: the one shared issuing path,
 * crs/issueContractorCopy.ts, with the live checks. Cancel (or Escape)
 * closes the step and issues nothing.
 *
 * v2.1 round 2: the preview is a look only (`CrsPreviewSheet readOnly`: no
 * transmittal form, no reply import, no row buttons). The keyboard stays
 * inside the step while it is open (Tab and Shift+Tab go round), Escape
 * closes it only when the cursor is not in a box being typed in, and on
 * close the keyboard goes back to the Sign button that opened it. Signing
 * an older review (a newer review of the same document exists) asks first:
 * "Issue to contractor" waits for a tick saying so.
 */
import { useEffect, useId, useRef, useState } from "react";

import { issueConfirmed } from "../useSignOff";
import { CrsLook, contractorView } from "./CrsLook";

/** Kept here too: older callers import it from this file. */
export { contractorView };

export interface SignConfirmProps {
  runId: string;
  open: boolean;
  onClose: () => void;
  onIssued: () => void;
  summary: {
    comments: number | null; finalCode: string | null; signer: string | null;
    /** Sign-in is off here (no signer can be named); null or absent when not known. */
    signInOff?: boolean | null;
  };
  /** A newer review of the same document exists (its date, when known):
   *  signing this older one asks first. Absent or null: this is the newest. */
  newerReview?: { at: string | null } | null;
}

/** "12 comments, final code 2, signed by Sam Lee." Unknown parts are said
 *  as unknown, never as 0. */
export function summaryLine(summary: SignConfirmProps["summary"]): string {
  const { comments, finalCode, signer } = summary;
  const parts = [
    comments === null ? "number of comments not known yet"
      : `${comments.toLocaleString()} ${comments === 1 ? "comment" : "comments"}`,
    finalCode ? `final code ${finalCode}` : "no final code recorded",
    signer ? `signed by ${signer}` : summary.signInOff ? "signer not known (sign-in is off)" : "signed under your name",
  ];
  const line = parts.join(", ");
  return `${line[0].toUpperCase()}${line.slice(1)}.`;
}

/** The question when the review being signed is not the newest one. */
export function olderReviewWarning(at: string | null): string {
  return `You are signing an older review. A newer review of this document exists${at ? ` (${at})` : ""}; `
    + "the contractor would get this older sheet, not the newer one.";
}

function isTyping(el: Element | null): boolean {
  const node = el as HTMLElement | null;
  return !!node && (/^(INPUT|TEXTAREA|SELECT)$/.test(node.tagName) || node.isContentEditable);
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-60";

export function SignConfirm({ runId, open, onClose, onIssued, summary, newerReview = null }: SignConfirmProps) {
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  /** The control that opened the step (the Sign button): the keyboard goes
   *  back to it when the step closes. */
  const opener = useRef<HTMLElement | null>(null);
  const [olderOk, setOlderOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The sheet is read again every time the step opens (CrsLook mounts with
  // it): what is issued is what the server holds now.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setOlderOk(false);
    const active = document.activeElement as HTMLElement | null;
    opener.current = active && active !== document.body ? active : null;
    headingRef.current?.focus();
    return () => {
      // Closed: the keyboard goes back to the Sign button that opened it.
      const back = opener.current;
      opener.current = null;
      if (back && back.isConnected) back.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        // Escape in a box being typed in belongs to that box.
        if (!busy && !isTyping(document.activeElement)) onClose();
        return;
      }
      if (event.key !== "Tab") return;
      // Keep the keyboard inside the step.
      const box = dialogRef.current;
      if (!box) return;
      const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) { event.preventDefault(); headingRef.current?.focus(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const at = document.activeElement as HTMLElement | null;
      const inside = !!at && box.contains(at);
      if (event.shiftKey && (!inside || at === first || at === headingRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || at === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const issue = async () => {
    setBusy(true);
    setError(null);
    const outcome = await issueConfirmed(runId);
    setBusy(false);
    if (!outcome.ok) { setError(outcome.message); return; }
    onIssued();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/70 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} data-testid="ws-sign-confirm"
        className="w-full max-w-6xl space-y-3 rounded-[var(--radius-md)] border border-ink-600 bg-ink-900 p-4 text-sm text-slateish-200">
        <h2 id={titleId} ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-slateish-100 outline-none">
          Check the sheet before it goes to the contractor
        </h2>
        <p data-testid="ws-sign-summary" className="text-base text-slateish-100">{summaryLine(summary)}</p>
        <p className="text-slateish-400">
          This is the comment sheet as it stands now, without the columns kept for your own team. The issued
          file is made by the server, which leaves out anything no engineer confirmed, and a copy is kept on
          record. Nothing is sent until you press &quot;Issue to contractor&quot;.
        </p>
        <CrsLook runId={runId} errorTestId="ws-sign-preview-error"
          failNote="You can still issue it; the server makes the file either way." />
        {newerReview && (
          <div role="group" aria-label="Signing an older review" data-testid="ws-sign-older"
            className="space-y-1 rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 p-2">
            <p className="text-warn-500">{olderReviewWarning(newerReview.at)}</p>
            <label className="flex items-center gap-2 text-slateish-100">
              <input type="checkbox" checked={olderOk} onChange={(e) => setOlderOk(e.target.checked)} />
              Yes, sign this older review anyway
            </label>
          </div>
        )}
        {error && <p role="alert" data-testid="ws-sign-error" className="text-danger-500">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={`${BUTTON} border-ink-600 text-slateish-100`}>
            Cancel
          </button>
          <button type="button" onClick={() => void issue()} disabled={busy || (newerReview !== null && !olderOk)}
            className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>
            {busy ? "Issuing…" : "Issue to contractor"}
          </button>
        </div>
      </div>
    </div>
  );
}
