import { useEffect, useMemo, useRef, useState } from "react";

import type { ReviewRunSummary } from "../../../types/api";
import { ProgressTracker } from "./overallProgress";
import { isGeneralJob, shown } from "./reviewProgress";
import { slowLine } from "./overallProgress";

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
  // A running review on the local model names its model and the minutes of its last measured run (the server's `local_note`): a long step
  // then does not look stuck. Shown with or without the progress detail.
  const note = job?.local_note ? <p className="text-xs text-slateish-300" data-testid="review-local-note">{job.local_note}</p> : null;
  if (!detail) return note;
  const s = shown(detail, extra);
  // The general review: ONE step line (the screen's own, from the job's five named steps) and no earlier-engine step names, bands or
  // "No progress" light (they count four steps of another method and read a clock that only moves at a step's end). The bar counts
  // the job's own steps; the light is red only when the server says the worker is gone.
  if (isGeneralJob(job)) {
    const done = Math.max(0, job?.progress_done ?? 0), total = job?.progress_total ?? 5;
    const slow = slowLine({ ...detail, step: null }, extra);
    return (
      <div className="space-y-1" data-testid="review-progress-block" data-method="general">
        <div role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={Math.min(done, total)}
          aria-label={`${Math.min(done, total)} of ${total} steps finished`} className="h-2 w-full overflow-hidden rounded bg-slateish-500">
          <div data-testid="review-progress-fill" data-state="working" className="progress-fill progress-stripes h-2 rounded bg-signal-500"
            style={{ width: `${Math.round((Math.min(done, total) / total) * 100)}%` }} />
        </div>
        <p className="text-xs text-slateish-300" data-testid="review-progress-detail">
          {[s.elapsed, slow].filter((x): x is string => x !== null).join(" · ")}
        </p>
        {note}
        {detail.stale && (
          <p role="status" data-testid="review-stall" data-level="red" className="text-xs text-danger-500">
            The run may be stuck; see System Health.
          </p>
        )}
      </div>
    );
  }
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
