/**
 * OWNER: builder D. "Review again" inside the workspace: starts a fresh
 * review of the same document and opens it. A refusal (for example a review
 * of this document is already running) is shown exactly as the API said it.
 */
import { useState } from "react";

import type { ReviewAgainButtonProps } from "./contract";
import { reviewAgain } from "./newReview";

export function ReviewAgainButton({ documentId, filename = null, onStarted }: ReviewAgainButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (busy) return;
    setBusy(true);
    setError(null);
    const outcome = await reviewAgain(documentId, filename);
    setBusy(false);
    if (outcome.ok) onStarted(outcome.runId);
    else setError(outcome.message);
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={busy}
        onClick={() => void run()}
        className="rounded-[var(--radius-md)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500 disabled:opacity-50"
      >
        {busy ? "Starting…" : "Review again"}
      </button>
      {error && <span role="alert" className="text-xs text-danger-500">{error}</span>}
    </span>
  );
}
