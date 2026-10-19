/**
 * OWNER: builder D. "Your review of X is ready", on any page. Mounted once
 * inside the Shell (builder A, App.tsx). Shows one line per watched review
 * that finished, each with "Open it" and "Dismiss". Renders nothing when
 * nothing has finished.
 *
 * v2.1 (W4): it never covers the open evidence panel. The panel is a fixed
 * column on the right (z-30); while it is open (`panelOpen`, told by the
 * app from the address) the notice moves to the bottom left (beside the
 * menu on a wide screen, so it does not cover the menu either), and it
 * always sits one layer below the panel (z-20), so where the two could
 * still meet (a narrow screen, where the panel is full width) the panel
 * wins.
 */
import type { FinishedReview, FinishedReviewNoticeProps } from "./contract";
import { useFinishedReviews } from "./reviewWatch";

function noticeWords(review: FinishedReview): string {
  const of = review.filename ? ` of ${review.filename}` : "";
  if (review.status === "failed") return `Your review${of} did not finish`;
  return `Your review${of} is ready`;
}

export interface FinishedNoticePlacement {
  /** An evidence panel is open on the right: keep clear of it. */
  panelOpen?: boolean;
}

export function FinishedReviewNotice({ onOpenRun, panelOpen = false }: FinishedReviewNoticeProps & FinishedNoticePlacement) {
  const { finished, dismiss } = useFinishedReviews();
  if (finished.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="finished-review-notice"
      data-placement={panelOpen ? "left" : "right"}
      className={`fixed bottom-4 z-20 flex max-w-sm flex-col gap-2 ${panelOpen ? "left-4 md:left-[17rem]" : "right-4"}`}
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
              onClick={() => {
                // The app may refuse to leave (unsaved decisions, and the
                // reader chose to stay): it says so by returning false, and
                // the notice stays so the review can still be opened later.
                const opened: unknown = onOpenRun(review.runId);
                if (opened !== false) dismiss(review.runId);
              }}
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
