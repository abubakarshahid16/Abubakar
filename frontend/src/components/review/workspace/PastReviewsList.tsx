/**
 * OWNER: builder E. The compact past-reviews list.
 *
 * One line per review: date, result, comments, signed yes/no. Comment
 * counts are read lazily (one `loadCommentCount` per review) when the list
 * mounts, i.e. when it is opened. A count that is unknown or failed shows
 * nothing - never 0.
 */
import { useEffect, useState } from "react";

import { whenLabel } from "../reviewFormat";
import type { PastReviewsListProps } from "./contract";
import { loadCommentCount } from "./pastReviews";

function commentsLabel(count: number | null): string {
  if (count == null) return "";
  return count === 1 ? "1 comment" : `${count} comments`;
}

export function PastReviewsList({ reviews, onOpenRun }: PastReviewsListProps) {
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const runKey = reviews.map((r) => r.runId).join("|");

  useEffect(() => {
    let alive = true;
    for (const review of reviews) {
      if (review.commentCount != null) continue;
      void loadCommentCount(review.runId).then((count) => {
        if (alive) setCounts((was) => ({ ...was, [review.runId]: count }));
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
        const count = review.commentCount ?? counts[review.runId] ?? null;
        return (
          <li key={review.runId}>
            <button
              type="button"
              onClick={() => onOpenRun(review.runId)}
              className="grid w-full grid-cols-2 gap-x-3 gap-y-1 px-3 py-2 text-left text-xs text-slateish-300 hover:bg-ink-800 sm:grid-cols-4"
            >
              <span data-field="date">{whenLabel(review.createdAt)}</span>
              <span data-field="result" className="font-semibold text-slateish-100">{review.result}</span>
              <span data-field="comments">{commentsLabel(count)}</span>
              <span data-field="signed">{review.signed ? "Signed: yes" : "Signed: no"}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
