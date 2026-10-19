/**
 * OWNER: builder E (v2.1: builder A). The compact past-reviews list.
 *
 * One line per review (the latest included): date, result, what the review
 * found (its totals, never "left to decide"), and signed, final code
 * recorded but not signed, or not signed. The counts are read lazily, ALL IN ONE
 * request (`loadPastReviewCounts`), when the list mounts, i.e. when it is
 * opened. They count findings (the server's count), not the comment sheet's
 * lines, and the list says so under it (W5). A count that is unknown or
 * failed shows nothing - never 0. A signed review shows "Signed" and no
 * count, and its count is not read.
 *
 * v2.2: given `currentRunId` (the review on screen), every EARLIER finished
 * review of the same file gets "Compare with this one", which opens
 * CompareReviews (what changed since that review) as a dialog. On close the
 * keyboard goes back to the button that opened it. Comparing is a look only.
 */
import { useEffect, useRef, useState } from "react";

import type { ReadyCounts } from "../inbox/inboxState";
import { dayTimeWords } from "./landing/dateWords";
import { CompareReviews } from "./compare/CompareReviews";
import type { PastReview, PastReviewsListProps } from "./contract";
import { PAST_COUNTS_NOTE, type PastReviewRow, loadPastReviewCounts, pastCountsLabel, signedWords } from "./pastReviews";

export interface PastReviewsListWithCompareProps extends PastReviewsListProps {
  /** The review on screen. Absent: no compare buttons (the landing page). */
  currentRunId?: string | null;
}

/** The reviews "Compare with this one" is offered on: finished, not the one
 *  on screen, and made before it (when both dates are known). */
export function comparableReviews(reviews: PastReview[], currentRunId: string | null | undefined): Set<string> {
  if (!currentRunId) return new Set();
  const current = reviews.find((r) => r.runId === currentRunId);
  const at = current?.createdAt ?? null;
  return new Set(reviews.filter((r) => r.runId !== currentRunId && r.status === "completed"
    && (!at || !r.createdAt || r.createdAt < at)).map((r) => r.runId));
}

export function PastReviewsList({ reviews, onOpenRun, currentRunId = null }: PastReviewsListWithCompareProps) {
  const [comparing, setComparing] = useState<PastReview | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const canCompare = comparableReviews(reviews, currentRunId);
  const [counts, setCounts] = useState<Record<string, ReadyCounts | null>>({});
  const runKey = reviews.map((r) => r.runId).join("|");

  useEffect(() => {
    let alive = true;
    // The review on screen is left out: its own numbers are on the page
    // (one source of numbers), so its "found" count is not read or shown.
    const ids = reviews.filter((r) => !r.signed && r.runId !== currentRunId).map((r) => r.runId);
    if (ids.length === 0) return undefined;
    void loadPastReviewCounts(ids).then((got) => {
      if (alive) setCounts((was) => ({ ...was, ...got }));
    });
    return () => { alive = false; };
    // Re-read only when the set of runs changes, not on every new array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey, currentRunId]);

  if (reviews.length === 0) return null;
  const anyCount = reviews.some((r) => !r.signed && r.runId !== currentRunId && counts[r.runId]);

  return (
    <div>
      <ul aria-label="All reviews of this file" className="divide-y divide-ink-700 rounded-[var(--radius-sm)] border border-ink-700">
        {reviews.map((review) => {
          const own = review.runId === currentRunId;
          const words = own ? "This review" : review.signed ? "" : pastCountsLabel(counts[review.runId]);
          return (
            <li key={review.runId} className="flex items-stretch">
              <button
                type="button"
                aria-current={own ? "true" : undefined}
                onClick={() => onOpenRun(review.runId)}
                className="grid min-w-0 flex-1 grid-cols-2 gap-x-3 gap-y-1 px-3 py-2 text-left text-xs text-slateish-300 hover:bg-ink-800 sm:grid-cols-4"
              >
                <span data-field="date">{dayTimeWords(review.createdAt)}</span>
                <span data-field="result" className="font-semibold text-slateish-100">{review.result}</span>
                <span data-field="findings">{words}</span>
                <span data-field="signed">{signedWords(review as PastReviewRow)}</span>
              </button>
              {currentRunId && canCompare.has(review.runId) && (
                <button
                  type="button"
                  data-testid="compare-with"
                  aria-label={`Compare with this one (review of ${dayTimeWords(review.createdAt) || "an earlier date"})`}
                  onClick={(e) => { opener.current = e.currentTarget; setComparing(review); }}
                  className="shrink-0 px-3 text-xs text-signal-300 underline-offset-2 hover:underline"
                >
                  Compare with this one
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {comparing && currentRunId && (
        <CompareReviews
          currentRunId={currentRunId} earlierRunId={comparing.runId} earlierAt={comparing.createdAt}
          onClose={() => { setComparing(null); opener.current?.focus(); }}
        />
      )}
      {anyCount && <p className="mt-1 text-xs text-slateish-400" data-testid="past-counts-note">{PAST_COUNTS_NOTE}</p>}
    </div>
  );
}
