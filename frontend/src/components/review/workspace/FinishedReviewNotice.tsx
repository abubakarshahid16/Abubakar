/**
 * OWNER: builder D. "Your review of X is ready", on any page. Mounted once
 * inside the Shell (builder A, App.tsx). Shows one line per watched review
 * that finished, each with "Open it" and "Dismiss". Renders nothing when
 * nothing has finished.
 */
import type { FinishedReview, FinishedReviewNoticeProps } from "./contract";
import { useFinishedReviews } from "./reviewWatch";

function noticeWords(review: FinishedReview): string {
  const of = review.filename ? ` of ${review.filename}` : "";
  if (review.status === "failed") return `Your review${of} did not finish`;
  return `Your review${of} is ready`;
}

export function FinishedReviewNotice({ onOpenRun }: FinishedReviewNoticeProps) {
  const { finished, dismiss } = useFinishedReviews();
  if (finished.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="finished-review-notice"
      className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2"
    >
      {finished.map((review) => (
        <div
          key={review.runId}
          className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 px-4 py-3 text-sm text-slateish-100 shadow-lg"
        >
          <p>{noticeWords(review)}</p>
          <div className="mt-2 flex gap-3">
            <button
              type="button"
              onClick={() => { dismiss(review.runId); onOpenRun(review.runId); }}
              className="font-medium text-signal-400 hover:underline"
            >
              Open it
            </button>
            <button
              type="button"
              onClick={() => dismiss(review.runId)}
              className="text-slateish-300 hover:underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
