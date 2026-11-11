import { useEffect, useMemo, useRef, useState } from "react";

import type { ReviewRunSummary } from "../../../types/api";
import { ProgressTracker } from "./overallProgress";
import { shown } from "./reviewProgress";

/** #1494: bar, timer, labelled estimate and stall light of a running review.
 *  Rendered only when the server sent `progress_detail` (switch
 *  REVIEW_PROGRESS_BAR_ENABLED on). The server's ages are advanced here once a
 *  second between polls, so the clock on screen is the server's clock. */
export function ReviewProgressBlock({ job }: { job: ReviewRunSummary["job"] }) {
  const detail = job?.progress_detail ?? null;
  const [extra, setExtra] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const received = useRef(Date.now());
  useEffect(() => {
    received.current = Date.now();
    setExtra(0);
  }, [detail]);
  useEffect(() => {
    if (!detail) return;
    const t = setInterval(() => {
      setExtra(Math.floor((Date.now() - received.current) / 1000));
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(t);
  }, [detail]);
  const jobId = job?.id;
  const tracker = useMemo(() => new ProgressTracker(), [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!detail) return null;
  const s = shown(detail, extra);
  // The four-step overall bar, when the server says which step the review is on (older servers: the legacy bar below).
  if (typeof detail.step === "number") {
    const v = tracker.update(detail, now, extra);
    const count = detail.step === 3 ? v.count : detail.step === 4 ? s.clausesLine : s.pagesLine;
    return (
      <div className="space-y-1" data-testid="review-progress-block">
        {v.percent !== null && (
          <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v.percent}
            aria-label={v.step ?? "progress"} className="h-2 w-full overflow-hidden rounded bg-slateish-500">
            <div data-testid="review-progress-fill" data-state={v.noProgress ? "no-progress" : "working"}
              className={`progress-fill h-2 rounded ${v.noProgress ? "bg-warn-500" : "bg-signal-500 progress-stripes"}`}
              style={{ width: `${v.percent}%` }} />
          </div>
        )}
        {v.step && <p className="text-sm text-slateish-100" data-testid="review-progress-step">{v.step}</p>}
        <p className="text-xs text-slateish-300" data-testid="review-progress-detail">
          {[count, v.percent !== null ? `${v.percent}% overall` : null, s.elapsed, v.range, v.slow]
            .filter((x): x is string => x !== null && x !== undefined).join(" · ")}
        </p>
        {v.noProgress && (
          <p role="status" data-testid="review-no-progress" data-level="orange" className="text-xs text-warn-500">
            No progress for 5 minutes.
          </p>
        )}
        {s.stall && !v.noProgress && (
          <p role="status" data-testid="review-stall" data-level={s.stall.level}
            className={`text-xs ${s.stall.level === "red" ? "text-danger-500" : "text-warn-500"}`}>
            {s.stall.text}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-1" data-testid="review-progress-block">
      {s.percent !== null && (
        <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={s.percent}
          aria-label={s.pagesLine ?? s.clausesLine ?? "progress"} className="h-2 w-full rounded bg-slateish-500">
          {/* signal-500: the theme's accent, redefined for light and dark (an
              undefined colour class draws nothing: the live review "frozen" bar). */}
          <div className="h-2 rounded bg-signal-500" style={{ width: `${s.percent}%` }} />
        </div>
      )}
      <p className="text-xs text-slateish-300" data-testid="review-progress-detail">
        {[s.pagesLine, s.clausesLine, s.percent !== null ? `${s.percent}%` : null, s.elapsed, s.estimate]
          .filter((x): x is string => x !== null).join(" · ")}
      </p>
      {s.stall && (
        <p role="status" data-testid="review-stall" data-level={s.stall.level}
          className={`text-xs ${s.stall.level === "red" ? "text-danger-500" : "text-warn-500"}`}>
          {s.stall.text}
        </p>
      )}
    </div>
  );
}
