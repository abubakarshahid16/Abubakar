/**
 * Order 123 item 1: "New review" on the Submittals page.
 *
 * Before this, starting a review took about 10 clicks over 3 pages: upload
 * on Documents, set the role there, come back here, find the row, Review.
 * Now: New review, drop or choose one file, and the review starts. The file
 * is marked a contractor submittal for you (`prepareSubmittal`) and the page
 * starts (or opens) its review.
 */
import { useState } from "react";

import { Uploader, type UploadState } from "../Uploader";
import { prepareSubmittal } from "./newReview";

export function NewReview({ onReady, onUploaded }: {
  /** The document is a contractor submittal now: start or open its review. */
  onReady: (documentId: string) => void;
  /** Something was stored: the list behind may have a new row. */
  onUploaded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fileDone(name: string, state: UploadState) {
    setError(null);
    setBusy(`Marking ${name} as a contractor submittal…`);
    const prepared = await prepareSubmittal(name, state);
    setBusy(null);
    if (!prepared.ok) {
      setError(prepared.message);
      return;
    }
    setOpen(false);
    onReady(prepared.documentId);
  }

  return (
    <div className="space-y-3" data-testid="new-review">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-signal-400"
      >
        New review
      </button>
      {open && (
        <div className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4">
          <p className="text-sm text-slateish-200">
            Drop the contractor's file. It is marked a contractor submittal for you, the
            standards that apply are picked by the review, and the review starts.
          </p>
          <Uploader single onUploaded={onUploaded} onFileDone={(name, state) => void fileDone(name, state)} />
          {busy && <p role="status" className="text-sm text-slateish-300">{busy}</p>}
          {error && <p role="alert" className="text-sm text-danger-500">{error}</p>}
        </div>
      )}
    </div>
  );
}
