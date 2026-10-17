/**
 * Owner order section 3: what the review can use, before it is run. Every
 * count carries its denominator and is about this caller's documents.
 *
 * Split out of `ReviewRunsView.tsx` (#925 item 7: that file was 1,421 lines,
 * the project's own quality ratchet's `max_frontend_component_lines` -
 * extracting a self-contained panel, not the whole promised split, but this
 * was the piece an unrelated change (#925 item 1) was about to grow past the
 * ratchet's baseline).
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type { ReviewReadiness, VisionReaderStatus } from "../../types/api";
import { pageList, pagesReadLine } from "./reviewFormat";

export function ReadinessStrip({ readiness, onOpenStandards, onReread }: {
  readiness: ReviewReadiness; onOpenStandards?: () => void;
  onReread: () => Promise<void>;
}) {
  const [rereading, setRereading] = useState(false);
  const [rereadError, setRereadError] = useState<string | null>(null);
  const vision = useVisionReaderStatus(readiness.unread_pages.length > 0, rereading);
  const pages = pagesReadLine(readiness);
  const missing = readiness.standards_missing;
  return (
    <div data-testid="readiness-strip"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-slateish-200">
      {pages && (
        <span>
          {pages}
          {readiness.unread_pages.length > 0 && (
            <span className="text-slateish-400"> (not read: {pageList(readiness.unread_pages)})</span>
          )}
        </span>
      )}
      {/* HONESTY GROUP (2026-09-27): a bare page number said a page was
          unread and nothing about why - the ledger has always known
          (`page_ledger.coverage`'s `not_read_reasons`), it just never
          reached here. One line per page, its own reason, never "unread"
          alone. */}
      {readiness.unread_pages.length > 0 && (
        <ul data-testid="unread-page-reasons"
          className="w-full list-none pl-0 text-xs text-slateish-400">
          {readiness.unread_pages.map((page) => (
            <li key={page}>
              Page {page}: {readiness.unread_page_reasons?.[String(page)]
                || "reason not recorded"}
            </li>
          ))}
        </ul>
      )}
      {readiness.unread_pages.length > 0 && (
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setRereading(true);
              setRereadError(null);
              void onReread().catch((error: unknown) => {
                setRereadError(error instanceof Error ? error.message : "Could not re-read the pages.");
              }).finally(() => setRereading(false));
            }}
            disabled={rereading}
            title="Re-reads the unread pages. When the vision reader is ready, their page images are sent to Claude."
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 text-xs text-signal-300 disabled:opacity-50"
          >
            {rereading ? "Reading…" : "Read unread pages"}
          </button>
          {rereadError && (
            <span role="alert" className="text-xs text-danger-500">{rereadError}</span>
          )}
          <VisionReaderLine status={vision} />
        </span>
      )}
      {readiness.standards_cited > 0 && (
        <span>
          Standards cited: {readiness.standards_held.length} held, {missing.length} missing
          {" "}(of {readiness.standards_cited})
        </span>
      )}
      {missing.length > 0 && onOpenStandards && (
        <button type="button" onClick={onOpenStandards}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 text-xs text-signal-300">
          Upload missing standards
        </button>
      )}
      {readiness.last_run_id && (
        <span className="text-slateish-400" data-testid="readiness-changes">
          {readiness.nothing_changed
            ? "Nothing changed since the last run."
            : readiness.changes.join(" · ")}
        </span>
      )}
    </div>
  );
}

type VisionLine =
  | { kind: "checking" }
  | { kind: "unknown"; message: string }
  | { kind: "known"; status: VisionReaderStatus };

/** Asks the backend whether the vision reader can be used, when there are
 *  unread pages, and again after each re-read finishes (`busy` going false). */
function useVisionReaderStatus(wanted: boolean, busy: boolean): VisionLine | null {
  const [line, setLine] = useState<VisionLine | null>(null);
  useEffect(() => {
    if (!wanted || busy) return;
    let live = true;
    setLine({ kind: "checking" });
    void reviewsApi.visionReaderStatus().then((result) => {
      if (!live) return;
      setLine(result.ok
        ? { kind: "known", status: result.data }
        : { kind: "unknown", message: result.error.message });
    });
    return () => { live = false; };
  }, [wanted, busy]);
  return wanted ? line : null;
}

/** One line beside "Read unread pages": whether page images will be read,
 *  and if not, the real reason and what to change. The text readers still
 *  run either way, so the button stays enabled. */
function VisionReaderLine({ status }: { status: VisionLine | null }) {
  if (!status) return null;
  if (status.kind === "checking") {
    return <span data-testid="vision-reader-status" className="text-xs text-slateish-400">Checking the vision reader…</span>;
  }
  if (status.kind === "unknown") {
    return (
      <span data-testid="vision-reader-status" className="text-xs text-warn-500">
        Vision reader status unknown: {status.message}
      </span>
    );
  }
  const s = status.status;
  if (s.ready) {
    return <span data-testid="vision-reader-status" className="text-xs text-signal-300">Vision reader ready: reading unread pages sends their page images to Claude.</span>;
  }
  return (
    <span data-testid="vision-reader-status" role="status" className="text-xs text-warn-500"
      title={s.detail ? `${s.state} (${s.detail})` : s.state}>
      Page images will not be read: {s.reason} {s.fix}
      {s.detail && <span className="text-slateish-400"> ({s.detail})</span>}
    </span>
  );
}
