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
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../../api/client";
import type { CrsPreview } from "../../../../types/api";
import { CrsPreviewSheet } from "../../CrsPreviewSheet";
import { issueConfirmed } from "../useSignOff";

export interface SignConfirmProps {
  runId: string;
  open: boolean;
  onClose: () => void;
  onIssued: () => void;
  summary: { comments: number | null; finalCode: string | null; signer: string | null };
}

/** Columns and notes the server marks as internal: the contractor's copy
 *  does not carry them, so the preview of that copy does not show them. */
const INTERNAL_COLUMNS = new Set(["AI Review Comments", "Reasoning (internal)", "Rule trust (internal)"]);

/** The preview as the contractor's copy lays it out. */
export function contractorView(preview: CrsPreview): CrsPreview {
  return {
    ...preview,
    columns: preview.columns.filter((c) => !INTERNAL_COLUMNS.has(c) && !/\(internal\)\s*$/i.test(c)),
    review_notes: [],
  };
}

/** "12 comments, final code 2, signed by Sam Lee." Unknown parts are said
 *  as unknown, never as 0. */
export function summaryLine(summary: SignConfirmProps["summary"]): string {
  const { comments, finalCode, signer } = summary;
  const parts = [
    comments === null ? "number of comments not known yet"
      : `${comments.toLocaleString()} ${comments === 1 ? "comment" : "comments"}`,
    finalCode ? `final code ${finalCode}` : "no final code recorded",
    signer ? `signed by ${signer}` : "signed under your name",
  ];
  const line = parts.join(", ");
  return `${line[0].toUpperCase()}${line.slice(1)}.`;
}

type Preview = { kind: "loading" } | { kind: "ready"; preview: CrsPreview } | { kind: "error"; message: string };

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-60";

export function SignConfirm({ runId, open, onClose, onIssued, summary }: SignConfirmProps) {
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [preview, setPreview] = useState<Preview>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (live: () => boolean) => {
    const result = await reviewsApi.previewCrs(runId);
    if (!live()) return;
    setPreview(result.ok ? { kind: "ready", preview: result.data } : { kind: "error", message: result.error.message });
  }, [runId]);

  // Read the sheet again every time the step opens: what is issued is what
  // the server holds now, not what it held the last time.
  useEffect(() => {
    if (!open) return;
    let live = true;
    setPreview({ kind: "loading" });
    setError(null);
    void load(() => live);
    headingRef.current?.focus();
    return () => { live = false; };
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onClose(); };
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
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} data-testid="ws-sign-confirm"
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
        {preview.kind === "loading" && <p className="text-slateish-400">Loading the sheet…</p>}
        {preview.kind === "error" && (
          <p role="alert" data-testid="ws-sign-preview-error" className="text-warn-500">
            The preview of the sheet could not be loaded ({preview.message}). You can still issue it; the server
            makes the file either way.
          </p>
        )}
        {preview.kind === "ready" && (
          <div className="max-h-[55vh] overflow-auto">
            <CrsPreviewSheet preview={contractorView(preview.preview)} runId={runId}
              onChanged={() => void load(() => true)} />
          </div>
        )}
        {error && <p role="alert" data-testid="ws-sign-error" className="text-danger-500">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={`${BUTTON} border-ink-600 text-slateish-100`}>
            Cancel
          </button>
          <button type="button" onClick={() => void issue()} disabled={busy}
            className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>
            {busy ? "Issuing…" : "Issue to contractor"}
          </button>
        </div>
      </div>
    </div>
  );
}
