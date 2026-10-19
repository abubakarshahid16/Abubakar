/**
 * OWNER: builder D. "Review again" inside the workspace: starts a fresh
 * review of the same document and opens it.
 *
 * Before it starts, the document's newest review is read: when it is signed
 * or carries the engineer's final code, the reader is asked in the page
 * ("Yes, start a new review" / "Cancel", the pattern the comment sheet uses)
 * before anything starts. A new review is a new row, so that review stays as
 * it is.
 *
 * A refusal is said in plain words (`startRefusal`): already running (with a
 * button to open the running review when the API named it), administrators
 * only, or a document the reader may not read.
 */
import { useState } from "react";

import type { ReviewAgainButtonProps } from "./contract";
import { type PriorDecision, loadPriorDecision, reviewAgain } from "./newReview";

/** `onOpenRun`: opens a run (the one already running). Left out, `onStarted`
 *  is used, which opens a run in every screen that shows this button. */
type Props = ReviewAgainButtonProps & { onOpenRun?: (runId: string) => void };

function askWords(prior: PriorDecision): string {
  switch (prior.kind) {
    case "signed":
      return "The latest review of this document is already signed. Start a new review anyway? The signed review stays as it is.";
    case "final_code":
      return `An engineer already chose the final code "${prior.finalCode}" on the latest review of this document. `
        + "Start a new review anyway? That review stays as it is.";
    default:
      return "Could not check whether the latest review of this document is already signed. Start a new review anyway?";
  }
}

const primary = "rounded-[var(--radius-md)] bg-signal-500 px-3 py-1.5 text-sm font-medium text-ink-950 hover:bg-signal-400 disabled:opacity-50";
const secondary = "rounded-[var(--radius-md)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500 disabled:opacity-50";

export function ReviewAgainButton({ documentId, filename = null, onStarted, mayStart, onOpenRun }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  const [asking, setAsking] = useState<PriorDecision | null>(null);

  async function start() {
    setBusy(true);
    const outcome = await reviewAgain(documentId, filename);
    setBusy(false);
    if (outcome.ok) { onStarted(outcome.runId); return; }
    setError(outcome.message);
    setRunningRunId("runningRunId" in outcome ? outcome.runningRunId : null);
  }

  async function press() {
    if (busy) return;
    if (mayStart && !mayStart()) return;
    setError(null);
    setRunningRunId(null);
    setBusy(true);
    const prior = await loadPriorDecision(documentId);
    setBusy(false);
    if (prior.kind !== "none") { setAsking(prior); return; }
    await start();
  }

  function confirm() {
    setAsking(null);
    void start();
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      {asking ? (
        <span role="group" aria-label="Start a new review?" className="flex flex-wrap items-center justify-end gap-2 text-sm text-slateish-200">
          <span>{askWords(asking)}</span>
          <button type="button" onClick={confirm} className={primary}>Yes, start a new review</button>
          <button type="button" onClick={() => setAsking(null)} className={secondary}>Cancel</button>
        </span>
      ) : (
        <button type="button" disabled={busy} onClick={() => void press()} className={secondary}>
          {busy ? "Starting…" : "Review again"}
        </button>
      )}
      {error && <span role="alert" className="text-xs text-danger-500">{error}</span>}
      {runningRunId && (
        <button
          type="button"
          onClick={() => (onOpenRun ?? onStarted)(runningRunId)}
          className="text-xs font-semibold text-signal-300 underline-offset-2 hover:underline"
        >
          Open the review that is running
        </button>
      )}
    </span>
  );
}
