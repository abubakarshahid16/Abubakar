/**
 * OWNER: builder E. The compact past-reviews list.
 *
 * One line per review: date, result, findings to decide, signed yes/no.
 * The counts are read lazily, in one batched `loadCommentCounts` call for
 * all rows that need one, when the list mounts, i.e. when it is opened. They count findings (comment +
 * needs-you), not the comment sheet's rows, and say so. A count that is
 * unknown or failed shows nothing - never 0. A signed review has nothing
 * left to decide, so it shows no count (its "Signed: yes" says it) and its
 * count is not read.
 */
import { useEffect, useState } from "react";

import { whenLabel } from "../reviewFormat";
import type { PastReviewsListProps } from "./contract";
import { loadCommentCounts } from "./pastReviews";

function findingsLabel(count: number | null): string {
  if (count == null) return "";
  return `${count.toLocaleString("en-US")} ${count === 1 ? "finding" : "findings"} to decide`;
}

export function PastReviewsList({ reviews, onOpenRun }: PastReviewsListProps) {
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const runKey = reviews.map((r) => r.runId).join("|");

  useEffect(() => {
    let alive = true;
    const ids = reviews.filter((r) => !r.signed && r.commentCount == null).map((r) => r.runId);
    if (ids.length > 0) {
      void loadCommentCounts(ids).then((got) => {
        if (alive) setCounts((was) => ({ ...was, ...got }));
      });
    }
    return () => { alive = false; };
    // Re-read only when the set of runs changes, not on every new array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);

  if (reviews.length === 0) return null;

  return (
    <ul aria-label="Past reviews" className="divide-y divide-ink-700 rounded-[var(--radius-sm)] border border-ink-700">
      {reviews.map((review) => {
        const count = review.signed ? null : review.commentCount ?? counts[review.runId] ?? null;
        return (
          <li key={review.runId}>
            <button
              type="button"
              onClick={() => onOpenRun(review.runId)}
              className="grid w-full grid-cols-2 gap-x-3 gap-y-1 px-3 py-2 text-left text-xs text-slateish-300 hover:bg-ink-800 sm:grid-cols-4"
            >
              <span data-field="date">{whenLabel(review.createdAt)}</span>
              <span data-field="result" className="font-semibold text-slateish-100">{review.result}</span>
              <span data-field="findings">{findingsLabel(count)}</span>
              <span data-field="signed">{review.signed ? "Signed: yes" : "Signed: no"}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
