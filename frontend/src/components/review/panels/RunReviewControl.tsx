/**
 * "Check it" for ONE contractor document (#967 PR 3; the old page's "Run a
 * review" picker, minus the picker - the landing lists the documents).
 *
 * Owner order section 3, kept as it was: the readiness strip (pages read,
 * standards held and missing, with denominators) before running; "Nothing
 * changed since the last run" asked BEFORE a re-run that would give the
 * same result; the server's refusal shown in its own words. Admin only:
 * `POST /api/reviews/run` answers a non-admin with a plain 404, so the
 * reason is said here up front instead of a quietly greyed-out button.
 */
import { useCallback, useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewReadiness } from "../../../types/api";
import { ReadinessStrip } from "../ReadinessStrip";

export function RunReviewControl({ submittalId, isAdmin, label, onStarted, onOpenStandards, onReread }: {
  submittalId: string;
  isAdmin: boolean;
  label: string;
  onStarted: (runId: string) => void;
  onOpenStandards?: () => void;
  /** After unread pages were re-read: the open run's findings may have moved. */
  onReread?: () => Promise<void>;
}) {
  const [readiness, setReadiness] = useState<ReviewReadiness | null>(null);
  const [confirmRerun, setConfirmRerun] = useState(false);
  const [launch, setLaunch] = useState<{ kind: "idle" } | { kind: "running" } | { kind: "error"; message: string }>({ kind: "idle" });

  const loadReadiness = useCallback(async () => {
    const result = await reviewsApi.readiness(submittalId);
    // A readiness the server would not give is shown as nothing: the strip
    // is a help before running, not a gate, and the run button still works.
    setReadiness(result.ok ? result.data : null);
  }, [submittalId]);

  useEffect(() => {
    setConfirmRerun(false);
    void loadReadiness();
  }, [loadReadiness]);

  /** "Nothing changed since the last run" is asked about BEFORE running. */
  function requestRun() {
    if (readiness?.nothing_changed && !confirmRerun) {
      setConfirmRerun(true);
      return;
    }
    setConfirmRerun(false);
    void start();
  }

  async function start() {
    setLaunch({ kind: "running" });
    const result = await reviewsApi.startReviewRun(submittalId);
    if (!result.ok) {
      // SHOWN AS THE API RETURNED IT - a refusal ("a review of this submittal
      // is already running") is a real answer, never retried silently.
      setLaunch({ kind: "error", message: result.error.message });
      return;
    }
    setLaunch({ kind: "idle" });
    onStarted(result.data.review_run_id);
    void loadReadiness();
  }

  return (
    <section aria-label={label} className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button" onClick={requestRun}
          disabled={!isAdmin || launch.kind === "running"}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
        >
          {launch.kind === "running" ? "Checking…" : label}
        </button>
        {!isAdmin && (
          <p className="text-xs text-slateish-400">Only an administrator can start a review.</p>
        )}
        {launch.kind === "running" && (
          <span aria-live="polite" className="text-sm text-slateish-300">
            Selecting applicable standards and comparing requirements. This can take a minute.
          </span>
        )}
      </div>
      {launch.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
          {launch.message}
        </p>
      )}
      {readiness && readiness.submittal_document_id === submittalId && (
        <ReadinessStrip
          readiness={readiness} onOpenStandards={onOpenStandards}
          onReread={async () => {
            const result = await reviewsApi.rereadPages(submittalId);
            if (!result.ok) throw new Error(result.error.message);
            setReadiness(result.data);
            await onReread?.();
          }}
        />
      )}
      {confirmRerun && (
        <div role="alertdialog" aria-label="Nothing changed since the last run"
          className="space-y-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 p-3 text-sm">
          <p className="font-medium text-slateish-100">Nothing changed since the last run.</p>
          <p className="text-slateish-300">
            No datasheet value was read and no standard was added since then,
            so a new run will give the same result. Upload a missing standard
            or re-read the unread pages first, or run it again anyway.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={requestRun}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-100">
              Run again anyway
            </button>
            <button type="button" onClick={() => setConfirmRerun(false)}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-300">
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
