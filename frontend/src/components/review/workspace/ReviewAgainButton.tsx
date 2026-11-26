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

import type { ReviewRunSummary } from "../../../types/api";
import type { ReviewAgainButtonProps } from "./contract";
import { StartReviewStep } from "../panels/StartReviewStep";
import { type PriorDecision, loadPriorDecision } from "./newReview";
import { priorDecisionWords } from "./priorDecisionWords";
import { Button } from "../../kit/Kit";

/** `onOpenRun`: opens a run (the one already running). Left out, `onStarted`
 *  is used, which opens a run in every screen that shows this button.
 *  v2.1 (landing): `label` names the button ("Start review", "New review");
 *  `runs` is the runs list the screen already holds, so the "asks first"
 *  check needs no runs request; `disabled` (nothing chosen yet); `primary`
 *  for the main button of a card. Left out, the button is exactly as before. */
type Props = ReviewAgainButtonProps & {
  onOpenRun?: (runId: string) => void;
  label?: string;
  runs?: ReviewRunSummary[];
  disabled?: boolean;
  primary?: boolean;
  /** Accessible name when the visible label is shared by many rows. */
  ariaLabel?: string;
  /** v2.1 (N1): the in-page leave question. Called before anything starts;
   *  it runs `go` at once when nothing is unsaved, or after the reader
   *  chose to go on. Used instead of `mayStart` when given. */
  beforeStart?: (go: () => void) => void;
};

/** What `useReviewAgain` needs: the button's props without its looks. */
export type ReviewAgainArgs = Pick<Props, "documentId" | "filename" | "onStarted" | "mayStart" | "onOpenRun" | "runs" | "disabled" | "beforeStart">;

const askWords = priorDecisionWords;


/** v2.1: the "Review again" rule in one place, so every button that starts
 *  a fresh review of a document (the workspace header, the missing
 *  standards panel, the landing rows) asks the same questions in the same
 *  order: first the unsaved decisions (`beforeStart` / `mayStart`), then
 *  "already signed / final code chosen / nothing changed". `question` is
 *  the question, error and "Open the review that is running" link, to show
 *  next to whichever button was pressed. */
export function useReviewAgain({
  documentId, filename = null, onStarted, mayStart, onOpenRun, runs, disabled = false, beforeStart,
}: ReviewAgainArgs) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  const [asking, setAsking] = useState<PriorDecision | null>(null);
  /** The document the question or answer below is about. A different
   *  document chosen since (the landing's select) hides them. */
  const [forDoc, setForDoc] = useState(documentId);
  const [stepFor, setStepFor] = useState<string | null>(null);
  const current = forDoc === documentId;

  /** THE ONE START: a fresh review opens the pre-start step (engine, what will leave this Mac, the list, the cost); its Start begins. */
  function start() {
    setStepFor(documentId);
  }

  async function check() {
    setError(null);
    setRunningRunId(null);
    setAsking(null);
    setForDoc(documentId);
    setBusy(true);
    const prior = runs ? await loadPriorDecision(documentId, runs) : await loadPriorDecision(documentId);
    setBusy(false);
    if (prior.kind !== "none") { setAsking(prior); return; }
    start();
  }

  function press() {
    if (busy || disabled || !documentId) return;
    if (beforeStart) { beforeStart(() => void check()); return; }
    if (mayStart && !mayStart()) return;
    void check();
  }

  function confirm() {
    setAsking(null);
    start();
  }

  const askingNow = asking !== null && current;
  const question = (
    <>
      {askingNow && asking && (
        <span role="group" aria-label="Start a new review?" className="flex flex-wrap items-center justify-end gap-2 text-sm text-slateish-200">
          <span>{askWords(asking)}</span>
          <Button variant="primary" onClick={confirm}>Yes, start a new review</Button>
          <Button onClick={() => setAsking(null)}>Cancel</Button>
        </span>
      )}
      {stepFor === documentId && (
        <span className="block w-full max-w-xl text-left">
          <StartReviewStep
            documentId={documentId}
            filename={filename}
            onCancel={() => setStepFor(null)}
            onOpenRunning={(runId) => (onOpenRun ?? onStarted)(runId)}
            onStarted={(runId) => { setStepFor(null); onStarted(runId); }}
          />
        </span>
      )}
      {error && current && <span role="alert" className="text-xs text-danger-500">{error}</span>}
      {runningRunId && current && (
        <Button variant="secondary" size="sm"
         
          onClick={() => (onOpenRun ?? onStarted)(runningRunId)}
        >
          Open the review that is running
        </Button>
      )}
    </>
  );
  return { busy, asking: askingNow || stepFor === documentId, press, question };
}

export function ReviewAgainButton({
  label = "Review again", primary: isPrimary = false, ariaLabel, ...args
}: Props) {
  const again = useReviewAgain(args);
  const disabled = args.disabled ?? false;
  return (
    <span className="inline-flex flex-col items-end gap-1">
      {!again.asking && (
        <Button variant={isPrimary ? "primary" : "secondary"} disabled={again.busy || disabled} onClick={again.press}
          aria-label={again.busy ? undefined : ariaLabel}
        >
          {again.busy ? "Starting…" : label}
        </Button>
      )}
      {again.question}
    </span>
  );
}
