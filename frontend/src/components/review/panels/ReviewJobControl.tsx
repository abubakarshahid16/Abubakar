/** Moved verbatim from `ReviewRunsView.tsx` (#967 PR 3). */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewRunSummary } from "../../../types/api";

/** P3: cancel a queued or running review. Shown beside the card, not inside
 *  it - the card is itself a button. The server's answer is shown as given. */
export function ReviewJobControl({ run, onChanged }: { run: ReviewRunSummary; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const job = run.job;
  if (!job || !(run.status === "queued" || run.status === "running") || job.cancel_requested) return null;
  return (
    <div className="flex items-center gap-2 ps-4">
      <button type="button" className="text-xs text-danger-500 underline"
        onClick={() => {
          void reviewsApi.cancelJob(job.id).then((r) => {
            if (!r.ok) { setError(r.error.message); return; }
            setError(null);
            onChanged();
          });
        }}>
        Cancel this review
      </button>
      {error && <span role="alert" className="text-xs text-danger-500">{error}</span>}
    </div>
  );
}
