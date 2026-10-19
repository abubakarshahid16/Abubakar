/**
 * v2.1: the Submittals first page with the "Try new design" switch ON.
 * (Switch off, SubmittalsLandingView renders exactly as before and never
 * mounts this.)
 *
 *   +- New review ------------------------------------------------------+
 *   | Choose a submittal [find...] [select v] [Start review]      (L1)  |
 *   | or drop a contractor's file here                       (drop zone) |
 *   +--------------------------------------------------------------------+
 *   [Review all not reviewed (N of the contractor documents listed here)]
 *     (+ the cut-short note when the documents list is cut short)   (L7)
 *   [Search by file name]      [All reviews you may open (N)]  (L4, L5)
 *   "Found by the review" counts comment and Needs-you findings only ...
 *   - Pump datasheet rev B.pdf  [Review ready]
 *       Found by the review: 12 findings, 3 needing your judgement  date
 *                                            [Open] [New review]  (L2, L3)
 *     All reviews of this file (2)                                (W5)
 *
 * Every start from this page is watched (`watchRun`), so the "ready" notice
 * appears wherever the reader goes (L6). A non-administrator sees a plain
 * message in place of the New review card and no start or cancel buttons;
 * nothing is uploaded or started for them.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../../api/client";
import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import type { ReadyCounts } from "../../inbox/inboxState";
import { NewReviewDropZone } from "../NewReviewDropZone";
import { truncationNote } from "../../reviewFormat";
import { startRefusal } from "../newReview";
import { watchRun } from "../reviewWatch";
import { AllReviewsList } from "./AllReviewsList";
import { LandingDocumentRow } from "./LandingDocumentRow";
import { StartReviewBar } from "./StartReviewBar";
import { allRunsOf, landingRowsOf, matchesName } from "./landingRows";
import { loadReadyCounts as defaultLoadReadyCounts } from "./readyCounts";

/** Rule 4: what the "Found by the review" line on the rows counts. Shown
 *  once near the list (not per row), only while some row shows a count. */
export const LANDING_COUNTS_NOTE =
  '"Found by the review" counts comment and Needs-you findings only: what each review found, including any already decided. '
  + "The comment sheet groups findings into fewer comment lines.";

export const NOT_ADMIN_LANDING_MESSAGE =
  "Only an administrator can start a review. You can open any review listed below.";

interface BatchResult {
  asked: number;
  queued: number;
  refused: { filename: string; message: string }[];
}

export function WorkspaceLanding({
  documents, runs, submittalsTotal, documentsFailed = false, isAdmin, onOpenRun, onReload,
  loadReadyCounts = defaultLoadReadyCounts,
}: {
  documents: DocumentRecord[];
  runs: ReviewRunSummary[];
  submittalsTotal: number | null;
  /** The contractor documents list could not be read (the runs could). */
  documentsFailed?: boolean;
  /** False: a non-administrator (no start, no upload, no cancel). Left out:
   *  not known yet; the server decides and refuses in plain words. */
  isAdmin?: boolean;
  onOpenRun: (runId: string) => void;
  onReload: () => Promise<void> | void;
  loadReadyCounts?: (runIds: string[]) => Promise<Record<string, ReadyCounts | null>>;
}) {
  const mayStart = isAdmin !== false;
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [counts, setCounts] = useState<Record<string, ReadyCounts | null>>({});
  const [batch, setBatch] = useState<BatchResult | null>(null);
  const [batching, setBatching] = useState(false);
  /** L7: "Review all" asks once before it starts anything. */
  const [confirmAll, setConfirmAll] = useState(false);
  const asked = useRef(new Set<string>());

  const rows = useMemo(() => landingRowsOf(documents, runs), [documents, runs]);
  const allItems = useMemo(() => allRunsOf(documents, runs), [documents, runs]);
  const shownRows = rows.filter((row) => matchesName(row.filename, query));
  const shownItems = allItems.filter((item) => matchesName(item.filename, query));
  const notReviewed = rows.filter((row) => row.state.kind === "not_reviewed");
  /** Rule 4: the not-reviewed count comes from the contractor documents
   *  list, which may be cut short; say so where that count is shown. */
  const documentsCut = truncationNote(documents.length, submittalsTotal, "contractor submittals");
  const anyCountShown = Object.values(counts).some((c) => c !== null);

  // Only the finished, unsigned runs on screen need counts; each id is asked once.
  const wanted = (showAll
    ? shownItems.map((i) => i.run).filter((r) => r.status === "completed" && !r.crs_issued_at)
    : shownRows.filter((r) => r.state.kind === "ready" && r.latest).map((r) => r.latest!)
  ).map((r) => r.review_run_id);
  const wantedKey = wanted.join(",");
  useEffect(() => {
    if (!wantedKey) return;
    const ids = wantedKey.split(",").filter((id) => !asked.current.has(id));
    if (ids.length === 0) return;
    for (const id of ids) asked.current.add(id);
    const nulls = () => Object.fromEntries(ids.map((id) => [id, null]));
    void loadReadyCounts(ids).then(
      (got) => setCounts((prev) => ({ ...prev, ...nulls(), ...pickOnly(got, ids) })),
      () => setCounts((prev) => ({ ...prev, ...nulls() })),
    );
  }, [loadReadyCounts, wantedKey]);

  /** L7: queue a review of every document never reviewed, one request each,
   *  in list order; each queued review is watched (L6). A refusal is named
   *  per document in plain words, never retried silently. Nothing opens. */
  async function reviewAll() {
    setConfirmAll(false);
    if (!mayStart || batching) return;
    setBatching(true);
    setBatch(null);
    const refused: BatchResult["refused"] = [];
    let queued = 0;
    for (const target of notReviewed) {
      const result = await reviewsApi.startReviewRun(target.documentId);
      if (result.ok) {
        queued += 1;
        watchRun(result.data.review_run_id, result.data.submittal_filename ?? target.filename);
      } else {
        refused.push({ filename: target.filename, message: (await startRefusal(result)).message });
      }
    }
    setBatch({ asked: notReviewed.length, queued, refused });
    setBatching(false);
    await onReload();
  }

  return (
    <div className="space-y-6">
      <section
        aria-labelledby="new-review-card-title"
        className="space-y-4 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
        data-testid="new-review-card"
      >
        <h2 id="new-review-card-title" className="text-lg font-semibold text-slateish-100">New review</h2>
        {!mayStart ? (
          <p className="text-sm text-slateish-300" data-testid="not-admin-message">{NOT_ADMIN_LANDING_MESSAGE}</p>
        ) : (
          <>
            {documentsFailed && (
              <p role="alert" className="text-sm text-danger-500">
                The list of contractor submittals could not be loaded, so there is nothing to choose from. You can still drop a file.
              </p>
            )}
            <StartReviewBar documents={documents} submittalsTotal={submittalsTotal} runs={runs} onStarted={onOpenRun} />
            <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">or</p>
            <NewReviewDropZone onStarted={onOpenRun} isAdmin={isAdmin} heading={null} />
          </>
        )}
      </section>

      {mayStart && notReviewed.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm text-slateish-300">
          {confirmAll && !batching ? (
            <span role="group" aria-label="Start all the reviews?" className="flex flex-wrap items-center gap-2 text-slateish-200">
              <span data-testid="review-all-question">
                Start {notReviewed.length.toLocaleString("en-US")} review{notReviewed.length === 1 ? "" : "s"}? They run one after another.
              </span>
              <button
                type="button"
                onClick={() => void reviewAll()}
                className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1.5 text-sm font-semibold text-ink-950"
              >
                Yes
              </button>
              <button
                type="button"
                onClick={() => setConfirmAll(false)}
                className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100"
              >
                Cancel
              </button>
            </span>
          ) : (
            <>
              <button
                type="button"
                disabled={batching}
                onClick={() => setConfirmAll(true)}
                className="rounded-[var(--radius-sm)] border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-300 disabled:opacity-50"
              >
                {batching
                  ? "Queuing reviews…"
                  : `Review all not reviewed (${notReviewed.length.toLocaleString("en-US")} of the contractor documents listed here)`}
              </button>
              <span className="text-xs text-slateish-400">
                Each runs in the background, one at a time. You get a notice when each one is ready.
              </span>
              {documentsCut && (
                <span className="basis-full text-xs text-slateish-400" data-testid="review-all-cut-note">
                  {documentsCut} Documents not listed are not counted or started.
                </span>
              )}
            </>
          )}
        </div>
      )}
      {batch && (
        <div role="status" className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-4 py-3 text-sm text-slateish-200">
          <p>Queued {batch.queued} of {batch.asked} reviews asked for.</p>
          {batch.refused.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-danger-500">
              {batch.refused.map((r) => <li key={r.filename}>{r.filename}: {r.message}</li>)}
            </ul>
          )}
        </div>
      )}

      <section aria-labelledby="landing-list-title" className="space-y-3">
        <h2 id="landing-list-title" className="text-lg font-semibold text-slateish-100">
          {showAll ? "All reviews" : "Documents from contractors"}
        </h2>
        {rows.length === 0 ? (
          <div className="rounded-[var(--radius-md)] border border-dashed border-ink-600 bg-ink-850 p-6" data-testid="landing-empty">
            <p className="font-semibold text-slateish-100">No documents from contractors yet</p>
            <p className="mt-2 max-w-2xl text-sm text-slateish-300">
              {mayStart
                ? "Start one with the New review card above: drop a contractor's PDF or Word file there and the review starts by itself."
                : "Nothing has been reviewed yet. Ask an administrator to start a review."}
            </p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by file name"
                aria-label="Search by file name"
                className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-slateish-100"
              />
              <button
                type="button"
                aria-pressed={showAll}
                onClick={() => setShowAll((was) => !was)}
                className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                  showAll ? "border-signal-500 bg-signal-500/15 text-signal-300" : "border-ink-600 text-slateish-300"
                }`}
              >
                All reviews you may open ({allItems.length.toLocaleString("en-US")})
              </button>
            </div>
            {anyCountShown && (
              <p className="text-xs text-slateish-400" data-testid="landing-counts-note">{LANDING_COUNTS_NOTE}</p>
            )}
            {showAll ? (
              <AllReviewsList items={shownItems} counts={counts} onOpenRun={onOpenRun} />
            ) : shownRows.length === 0 ? (
              <p className="text-sm text-slateish-300" data-testid="landing-no-match">No file name matches what you typed.</p>
            ) : (
              <ul className="space-y-2">
                {shownRows.map((row) => (
                  <LandingDocumentRow
                    key={row.documentId}
                    row={row}
                    counts={row.latest ? counts[row.latest.review_run_id] ?? null : null}
                    allRuns={runs}
                    mayStart={mayStart}
                    onOpenRun={onOpenRun}
                    onChanged={() => void onReload()}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  );
}

/** Only the asked ids, each a count or null (never undefined). */
function pickOnly(got: Record<string, ReadyCounts | null>, ids: string[]): Record<string, ReadyCounts | null> {
  return Object.fromEntries(ids.map((id) => [id, Object.prototype.hasOwnProperty.call(got, id) ? got[id] : null]));
}
