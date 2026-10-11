/**
 * #725 F7: the "CRS & Reports" page lists each review run's CRS.
 *
 * The CRS was reachable only from inside a run on the Review runs screen; the
 * page named after it listed answer reports alone. This lists the runs the
 * caller may read and downloads a run's CRS (internal review copy) with the
 * same call the Review runs screen uses - one export, two places to start it.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../api/client";
import type { ReviewRunSummary } from "../types/api";

export function ReviewCrsList() {
  const [runs, setRuns] = useState<ReviewRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [open, setOpen] = useState(false);

  // Loaded when asked for, not on every visit to the page: most visits are
  // for an answer report, and a list nobody opened is a request nobody made.
  async function show() {
    setOpen(true);
    const res = await reviewsApi.reviewRuns();
    if (res.ok) setRuns(res.data.runs);
    else setError(res.error.message);
  }

  async function download(runId: string) {
    setBusy(runId);
    setError(null);
    const result = await reviewsApi.exportCrs(runId, "internal");
    setBusy(null);
    if (!result.ok) {
      setError(`${result.error.message}. Nothing has been saved.`);
      return;
    }
    const url = URL.createObjectURL(result.data.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.data.filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  return (
    <section aria-label="Review CRSs" className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
      <h2 className="text-sm font-semibold text-slateish-100">Comment Resolution Sheets (review runs)</h2>
      {!open && (
        <button type="button" onClick={() => void show()}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-200">
          Show the review runs' CRSs
        </button>
      )}
      {error !== null && <p role="alert" className="text-sm text-danger-500">{error}</p>}
      {open && runs === null && error === null && <p className="text-sm text-slateish-400">Loading review runs…</p>}
      {runs !== null && runs.length === 0 && (
        <p className="text-sm text-slateish-400">No review runs on documents you can read yet.</p>
      )}
      {runs !== null && runs.length > 0 && (
        <ul className="divide-y divide-ink-700 text-sm">
          {runs.map((run) => (
            <li key={run.review_run_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-slateish-200">
                {run.submittal_filename ?? run.submittal_document_id}
                <span className="ml-2 text-xs text-slateish-400">
                  {run.status}{run.created_at ? ` · ${run.created_at.slice(0, 10)}` : ""}
                </span>
              </span>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void download(run.review_run_id)}
                className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-200"
              >
                Download CRS (internal review copy)
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
