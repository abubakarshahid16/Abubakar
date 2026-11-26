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
import { useEffect, useRef } from "react";

import type { FinishedReview, FinishedReviewNoticeProps } from "./contract";
import { useFinishedReviews } from "./reviewWatch";
import { Button } from "../../kit/Kit";

function noticeWords(review: FinishedReview): string {
  const of = review.filename ? ` of ${review.filename}` : "";
  if (review.status === "failed") return `Your review${of} did not finish`;
  return `Your review${of} is ready`;
}

/** How long a "ready" notice stays on screen before it closes itself. A notice that a review did not finish stays until dismissed. */
export const READY_NOTICE_MS = 12_000;

export interface FinishedNoticePlacement {
  /** An evidence panel is open on the right: keep clear of it. */
  panelOpen?: boolean;
  /** The review the reader has open now: its "ready" notice is closed (the reader already found it). */
  openRunId?: string | null;
}

export function FinishedReviewNotice({ onOpenRun, panelOpen = false, openRunId = null }: FinishedReviewNoticeProps & FinishedNoticePlacement) {
  const { finished, dismiss } = useFinishedReviews();
  const timers = useRef(new Map<string, number>());
  useEffect(() => {
    const ready = finished.filter((r) => r.status !== "failed");
    for (const r of ready) {
      if (r.runId === openRunId) dismiss(r.runId); // opened by any route: the notice has done its job
      else if (!timers.current.has(r.runId)) timers.current.set(r.runId, window.setTimeout(() => dismiss(r.runId), READY_NOTICE_MS));
    }
    for (const [id, timer] of [...timers.current]) {
      if (!ready.some((r) => r.runId === id)) { window.clearTimeout(timer); timers.current.delete(id); }
    }
  }, [finished, openRunId, dismiss]);
  useEffect(() => () => { for (const t of timers.current.values()) window.clearTimeout(t); timers.current.clear(); }, []);
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
            <Button variant="secondary"
             
              onClick={() => {
                // The app may refuse to leave (unsaved decisions, and the
                // reader chose to stay): it says so by returning false, and
                // the notice stays so the review can still be opened later.
                const opened: unknown = onOpenRun(review.runId);
                if (opened !== false) dismiss(review.runId);
              }}
            >
              Open it
            </Button>
            <Button variant="secondary"
             
              onClick={() => dismiss(review.runId)}
            >
              Dismiss
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
