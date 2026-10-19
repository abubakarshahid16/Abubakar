/**
 * v2.1 L5: "All reviews you may open (N)" - one flat list of every review the page
 * loaded, newest started first, each with Open. Built from the runs list
 * already on the page (no new endpoint). The chips use the same rules as
 * the document rows.
 */
import type { ReadyCounts } from "../../inbox/inboxState";
import { inboxStateOf } from "../../inbox/inboxState";
import { whenLabel } from "../../reviewFormat";
import { StatusChip } from "./LandingDocumentRow";
import { type RunListItem, countsLine, rowChip } from "./landingRows";

export function AllReviewsList({ items, counts, onOpenRun }: {
  items: RunListItem[];
  counts: Record<string, ReadyCounts | null>;
  onOpenRun: (runId: string) => void;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-slateish-300" data-testid="all-reviews-empty">No review matches.</p>;
  }
  return (
    <ul aria-label="All reviews" className="divide-y divide-ink-700 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850">
      {items.map(({ run, filename }) => {
        const state = inboxStateOf(run);
        const chip = rowChip(state, run);
        const found = countsLine(state, counts[run.review_run_id] ?? null);
        const started = whenLabel(run.created_at) || "date not recorded";
        return (
          <li key={run.review_run_id} className="flex flex-wrap items-center gap-3 px-4 py-2" data-testid="all-reviews-row">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slateish-100">{filename}</p>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slateish-400">
                <StatusChip tone={chip.tone} text={chip.text} />
                {found && <span data-testid="row-counts">{found}</span>}
                <span>Started {started}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={() => onOpenRun(run.review_run_id)}
              aria-label={`Open the review of ${filename} started ${started}`}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500"
            >
              Open
            </button>
          </li>
        );
      })}
    </ul>
  );
}
