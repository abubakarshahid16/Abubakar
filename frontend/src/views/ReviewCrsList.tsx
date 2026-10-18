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

/** Runs fetched per page (#1131). */
export const RUNS_PAGE = 50;

export function ReviewCrsList() {
  const [runs, setRuns] = useState<ReviewRunSummary[] | null>(null);
  // The server's count of every run the caller may read: the list says how
  // many it shows of how many, never a page passed off as the whole.
  const [total, setTotal] = useState<number | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [open, setOpen] = useState(false);

  // Loaded when asked for, not on every visit to the page: most visits are
  // for an answer report, and a list nobody opened is a request nobody made.
  async function show() {
    setOpen(true);
    const res = await reviewsApi.reviewRunsPage(0, RUNS_PAGE);
    if (res.ok) {
      setRuns(res.data.runs);
      setTotal(res.data.total);
    } else setError(res.error.message);
  }

  async function showMore() {
    if (runs === null) return;
    setMore(true);
    const res = await reviewsApi.reviewRunsPage(runs.length, RUNS_PAGE);
    setMore(false);
    if (!res.ok) {
      setError(res.error.message);
      return;
    }
    // A run already listed (the list moved while reading) is not shown twice.
    const seen = new Set(runs.map((r) => r.review_run_id));
    setRuns([...runs, ...res.data.runs.filter((r) => !seen.has(r.review_run_id))]);
    setTotal(res.data.total);
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
      {runs !== null && runs.length > 0 && total !== null && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-slateish-400">
          <span data-testid="crs-runs-count">
            Showing {runs.length.toLocaleString()} of {total.toLocaleString()} review runs
          </span>
          {runs.length < total && (
            <button type="button" disabled={more} onClick={() => void showMore()}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-200">
              {more ? "Loading…" : "Show more"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
