/**
 * v2.1 L2 / L3 / L9: one contractor document on the first page.
 *
 * File name, a plain status chip with counts, the newest activity date, and
 * two actions: "Open" (the latest review) and "New review" (a fresh one,
 * asking first when the latest is signed, coded, or nothing changed). A
 * failed review says why; a running one says its step and offers Cancel
 * (the existing `ReviewJobControl`). "All reviews of this file (N)" folds out
 * below.
 * An administrator-only action is not drawn for a non-administrator.
 */
import type { ReviewRunSummary } from "../../../../types/api";
import type { ReadyCounts } from "../../inbox/inboxState";
import { ReviewJobControl } from "../../panels/ReviewJobControl";
import { whenLabel } from "../../reviewFormat";
import { PastReviewsButton } from "../PastReviewsButton";
import { ReviewAgainButton } from "../ReviewAgainButton";
import { type ChipTone, type LandingRow, countsLine, hasFinishedReview, rowChip } from "./landingRows";

const TONE: Record<ChipTone, string> = {
  attention: "border-warn-500/50 bg-warn-500/10 text-warn-500",
  ready: "border-signal-500/50 bg-signal-500/10 text-signal-300",
  done: "border-signal-500/50 bg-ink-800 text-slateish-100",
  moving: "border-ink-500 bg-ink-800 text-slateish-200",
  failed: "border-danger-500/50 bg-danger-500/10 text-danger-500",
  quiet: "border-ink-600 bg-ink-850 text-slateish-300",
};

export function StatusChip({ tone, text }: { tone: ChipTone; text: string }) {
  return (
    <span data-testid="status-chip" data-tone={tone} className={`inline-block max-w-full break-words rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE[tone]}`}>
      {text}
    </span>
  );
}

export function LandingDocumentRow({ row, counts, allRuns, mayStart, onOpenRun, onOpenCrs, simple = false, onChanged }: {
  row: LandingRow;
  counts: ReadyCounts | null;
  /** The page's whole runs list (All reviews of this file and the "asks first" check
   *  read it; no extra request). */
  allRuns: ReviewRunSummary[];
  /** False for a non-administrator: no New review, no Cancel. */
  mayStart: boolean;
  onOpenRun: (runId: string) => void;
  /** v2.2: open the latest review straight on its CRS tab. Left out, no
   *  "Preview CRS" button. Offered only once the latest review has finished. */
  onOpenCrs?: (runId: string) => void;
  /** v2.2 Simple view: the long "Found by the review" line is folded away. */
  simple?: boolean;
  /** Something changed (a review was cancelled): re-read the list. */
  onChanged: () => void;
}) {
  const chip = rowChip(row.state, row.latest, counts);
  const detail = simple ? "" : countsLine(row.state, counts);
  const moving = row.state.kind === "queued" || row.state.kind === "running";
  const step = row.state.kind === "running" && row.state.label ? row.state.label : "";

  return (
    <li className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4" data-testid="landing-row">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-slateish-100">{row.filename}</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slateish-400">
            <StatusChip tone={chip.tone} text={chip.text} />
            {detail && <span data-testid="row-counts">{detail}</span>}
            {step && <span data-testid="row-step">Now: {step}</span>}
            {row.activityAt && <span>{whenLabel(row.activityAt)}</span>}
          </p>
        </div>
        {row.latest && (
          <button
            type="button"
            onClick={() => onOpenRun(row.latest!.review_run_id)}
            aria-label={`Open the latest review of ${row.filename}`}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950"
          >
            Open
          </button>
        )}
        {onOpenCrs && hasFinishedReview(row) && (
          <button
            type="button"
            onClick={() => onOpenCrs(row.latest!.review_run_id)}
            aria-label={`Preview the CRS of ${row.filename}`}
            className="rounded-[var(--radius-sm)] border border-signal-500 px-3 py-2 text-sm font-semibold text-signal-300"
          >
            Preview CRS
          </button>
        )}
        {mayStart && !moving && (
          <ReviewAgainButton
            documentId={row.documentId}
            filename={row.filename}
            runs={allRuns}
            label="New review"
            ariaLabel={`New review of ${row.filename}`}
            primary={!row.latest}
            onStarted={onOpenRun}
          />
        )}
      </div>
      {mayStart && moving && row.latest && <ReviewJobControl run={row.latest} onChanged={onChanged} />}
      {row.runs.length > 0 && (
        <div className="mt-2">
          <PastReviewsButton documentId={row.documentId} runs={allRuns} onOpenRun={onOpenRun} />
        </div>
      )}
    </li>
  );
}
