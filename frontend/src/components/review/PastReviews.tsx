/**
 * Order 123 item 5: a document's earlier reviews, on its row of the
 * Submittals list. The row's Review button opens the newest run; every
 * earlier run was reachable only from the inbox (switched off) or by typing
 * its address, so about 57 runs were out of a manager's reach. "Past reviews
 * (N)" lists them - date, result, findings, who decided - and Open takes any
 * of them to the comment sheet: two clicks.
 *
 * Read from the runs list the page already holds (`GET /api/reviews/runs`,
 * one row per run in `main._run_summary`'s shape); nothing more is fetched.
 */
import type { ReviewRunSummary } from "../../types/api";
import { pastFindings, pastResult } from "./pastReviewWords";
import { whenLabel } from "./reviewFormat";

export function PastReviews({ runs, onOpenRun }: {
  /** The document's runs before its newest, newest first. */
  runs: ReviewRunSummary[];
  onOpenRun: (runId: string) => void;
}) {
  if (runs.length === 0) return null;
  return (
    <details className="mt-2 w-full text-xs text-slateish-300" data-testid="past-reviews">
      <summary className="cursor-pointer">Past reviews ({runs.length})</summary>
      <ul className="mt-1 space-y-1">
        {runs.map((run) => {
          const when = whenLabel(run.created_at) || "date not recorded";
          const parts = [when, pastResult(run), pastFindings(run)].filter(Boolean);
          return (
            <li key={run.review_run_id} className="flex flex-wrap items-center gap-2">
              <span>{parts.join(" · ")}</span>
              <button
                type="button"
                onClick={() => onOpenRun(run.review_run_id)}
                className="underline"
                aria-label={`Open the review of ${when}`}
              >
                Open
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
