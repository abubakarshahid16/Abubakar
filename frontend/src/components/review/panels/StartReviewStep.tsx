/**
 * THE ONE START (owner, 12 Nov 2026, #1584: "the screen lists every document that will leave the Mac before the review starts").
 * Every button that starts a review of a paper opens this step: the engine choice, "Text leaves this Mac: yes/no", the list of the
 * documents that would leave, the cost and the contract line (`StartPanel`), then Start calls `POST /api/reviews/start` with exactly the
 * ids shown. Local only starts at once from it. The old one-click start (`POST /api/reviews/run`) has no caller left.
 */
import { useState } from "react";

import { type Engine, reviewPlan } from "../../../api/reviewPlan";
import { startRefusal } from "../workspace/newReview";
import {
  SIGN_IN_ENDED_LINE, clearStartFailure, isSignInEnded, recordStartFailure, startFailureReason,
} from "../workspace/startFailures";
import { watchRun } from "../workspace/reviewWatch";
import { StartPanel } from "./StartPanel";
import { Button } from "../../kit/Kit";

export function StartReviewStep({ documentId, filename = null, onStarted, onOpenRunning, onCancel }: {
  documentId: string;
  filename?: string | null;
  onStarted: (runId: string) => void;
  /** Opens the review that is already running (a refusal names it). Left out, `onStarted` opens it. */
  onOpenRunning?: (runId: string) => void;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);

  async function go(engine: Engine, shownDocumentIds: string[], ticked: string[] = []) {
    setBusy(true);
    setError(null);
    setRunningRunId(null);
    const result = await reviewPlan.start(documentId, engine, shownDocumentIds, ...(ticked.length ? [ticked] : []));
    setBusy(false);
    if (!result.ok) {
      // A refusal (already running, administrators only) is a real answer, in plain words (`startRefusal`), never retried silently.
      const refusal = await startRefusal(result);
      const ended = isSignInEnded(result.error);
      // G3: the answer is kept per paper, so the row says "Not reviewed: the start failed (...)" even when this screen is gone (a 401
      // sends the page to Sign in). A review that is already running is not a failed start: the running one is offered instead.
      if (refusal.runningRunId === null) recordStartFailure(documentId, startFailureReason(result.error, refusal.message), ended);
      setError(ended ? `${SIGN_IN_ENDED_LINE}.` : refusal.message || startFailureReason(result.error, ""));
      setRunningRunId(refusal.runningRunId);
      return;
    }
    clearStartFailure(documentId);
    watchRun(result.data.review_run_id, result.data.submittal_filename ?? filename);
    onStarted(result.data.review_run_id);
  }

  return (
    <div className="space-y-2" data-testid="start-review-step">
      <StartPanel submittalId={documentId} starting={busy} onStart={(e, ids, ticked) => void go(e, ids, ticked)} onCancel={onCancel} />
      {error && <p role="alert" className="text-xs text-danger-500">{error}</p>}
      {runningRunId && (
        <Button variant="secondary" size="sm" onClick={() => (onOpenRunning ?? onStarted)(runningRunId)}>
          Open the review that is running
        </Button>
      )}
    </div>
  );
}
