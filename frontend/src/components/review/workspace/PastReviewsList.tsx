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
 */
import { useEffect, useState } from "react";

import { whenLabel } from "../reviewFormat";
import type { ReadyCounts } from "../inbox/inboxState";
import type { PastReviewsListProps } from "./contract";
import { PAST_COUNTS_NOTE, type PastReviewRow, loadPastReviewCounts, pastCountsLabel, signedWords } from "./pastReviews";

export function PastReviewsList({ reviews, onOpenRun }: PastReviewsListProps) {
  const [counts, setCounts] = useState<Record<string, ReadyCounts | null>>({});
  const runKey = reviews.map((r) => r.runId).join("|");

  useEffect(() => {
    let alive = true;
    const ids = reviews.filter((r) => !r.signed).map((r) => r.runId);
    if (ids.length === 0) return undefined;
    void loadPastReviewCounts(ids).then((got) => {
      if (alive) setCounts((was) => ({ ...was, ...got }));
    });
    return () => { alive = false; };
    // Re-read only when the set of runs changes, not on every new array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);

  if (reviews.length === 0) return null;
  const anyCount = reviews.some((r) => !r.signed && counts[r.runId]);

  return (
    <div>
      <ul aria-label="All reviews of this file" className="divide-y divide-ink-700 rounded-[var(--radius-sm)] border border-ink-700">
        {reviews.map((review) => {
          const words = review.signed ? "" : pastCountsLabel(counts[review.runId]);
          return (
            <li key={review.runId}>
              <button
                type="button"
                onClick={() => onOpenRun(review.runId)}
                className="grid w-full grid-cols-2 gap-x-3 gap-y-1 px-3 py-2 text-left text-xs text-slateish-300 hover:bg-ink-800 sm:grid-cols-4"
              >
                <span data-field="date">{whenLabel(review.createdAt)}</span>
                <span data-field="result" className="font-semibold text-slateish-100">{review.result}</span>
                <span data-field="findings">{words}</span>
                <span data-field="signed">{signedWords(review as PastReviewRow)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {anyCount && <p className="mt-1 text-xs text-slateish-400" data-testid="past-counts-note">{PAST_COUNTS_NOTE}</p>}
    </div>
  );
}
