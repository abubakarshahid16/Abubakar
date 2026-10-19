/**
 * The AI Submittal Review landing page: one row per contractor submittal,
 * one Review button.
 *
 * #967 PR1 (Stage D redesign, build order item 1 of 4). Replaces the old
 * "Run a review" picker and the run-card list with the single list this
 * spec calls for - a datasheet proofreader starts from the document, not
 * from a run you have to pick out of a dropdown first. The
 * technical run detail (standards in scope, AI numbers, the findings
 * table) stays reachable through the same Review button; nothing here
 * changes what a run computes or stores (CLAUDE.md rule 10: frontend only).
 */
import type { DocumentRecord, ReviewRunSummary } from "../../types/api";
import { groupRunsByDocument, runStatusLabel, truncationNote, whenLabel } from "./reviewFormat";
import { PastReviewsButton } from "./workspace/PastReviewsButton";

/** NULL RENDERS AS NOTHING - a document with no run yet says so in words,
 *  never with an invented status. */
function latestRunLabel(latest: ReviewRunSummary | undefined): string {
  if (!latest) return "Not reviewed yet";
  return runStatusLabel(latest.status) || "Not reviewed yet";
}

/** One row per document: every CONTRACTOR_SUBMITTAL document plus, in case
 *  a run outlived its document record, every document a run names - so a
 *  run is never silently dropped from the landing page for a reason the
 *  reader cannot see. */
function rowsFor(documents: DocumentRecord[], runs: ReviewRunSummary[]) {
  const byId = new Map<string, { documentId: string; filename: string; latest?: ReviewRunSummary }>();
  for (const doc of documents) byId.set(doc.id, { documentId: doc.id, filename: doc.filename });
  for (const group of groupRunsByDocument(runs)) {
    const existing = byId.get(group.documentId);
    byId.set(group.documentId, {
      documentId: group.documentId,
      filename: existing?.filename ?? group.latest.submittal_filename ?? "(unnamed document)",
      latest: group.latest,
    });
  }
  return [...byId.values()];
}

export function DocumentsFromContractors(
  { documents, runs, submittalsTotal, onReview, startingDocumentId, onOpenPastRun }: {
    documents: DocumentRecord[];
    runs: ReviewRunSummary[];
    submittalsTotal: number | null;
    onReview: (documentId: string) => void;
    startingDocumentId: string | null;
    /** Workspace v2 (switch on only): when given, each row offers
     *  "Past reviews (N)" and a picked run opens through this. Absent, the
     *  list renders exactly as before. */
    onOpenPastRun?: (runId: string) => void;
  },
) {
  const rows = rowsFor(documents, runs);
  const boundary = truncationNote(documents.length, submittalsTotal, "contractor submittals");

  if (rows.length === 0) {
    return (
      <section className="rounded-[var(--radius-md)] border border-dashed border-ink-600 bg-ink-850 p-6">
        <h2 className="text-lg font-semibold text-slateish-100">No documents from contractors yet</h2>
        <p className="mt-2 max-w-2xl text-sm text-slateish-300">
          Upload a datasheet on the Documents page and set its role to
          contractor submittal to review it here.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="documents-from-contractors-title" className="space-y-3">
      <h2 id="documents-from-contractors-title" className="text-lg font-semibold text-slateish-100">
        Documents from contractors
      </h2>
      {boundary && (
        <p className="text-xs text-slateish-400" data-testid="submittals-boundary">{boundary}</p>
      )}
      <ul className="space-y-2">
        {rows.map((row) => (
          <li
            key={row.documentId}
            className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold text-slateish-100">{row.filename}</p>
              <p className="mt-1 text-xs text-slateish-400">
                {latestRunLabel(row.latest)}
                {row.latest ? ` · ${whenLabel(row.latest.created_at)}` : ""}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onReview(row.documentId)}
              disabled={startingDocumentId === row.documentId}
              className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
            >
              {startingDocumentId === row.documentId ? "Starting…" : "Review"}
            </button>
            {onOpenPastRun && (
              <PastReviewsButton documentId={row.documentId} runs={runs} onOpenRun={onOpenPastRun} />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
