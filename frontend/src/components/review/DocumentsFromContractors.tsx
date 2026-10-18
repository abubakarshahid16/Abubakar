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
 *
 * Order 95 piece 3: the list is the inbox. Each document says where its
 * newest review stands (`inboxState`), the chips filter by that ("Needs me"
 * first), and a document reviewed more than once lists its earlier runs.
 */
import { useState } from "react";

import type { DocumentRecord, ReviewRunSummary } from "../../types/api";
import { groupRunsByDocument, truncationNote, whenLabel } from "./reviewFormat";
import { FILTERS, type InboxFilter, inFilter, inboxStateOf, stateLabel } from "./inbox/inboxState";

interface Row {
  documentId: string;
  filename: string;
  latest?: ReviewRunSummary;
  earlier: ReviewRunSummary[];
}

/** One row per document: every CONTRACTOR_SUBMITTAL document plus, in case
 *  a run outlived its document record, every document a run names - so a
 *  run is never silently dropped from the landing page for a reason the
 *  reader cannot see. */
function rowsFor(documents: DocumentRecord[], runs: ReviewRunSummary[]): Row[] {
  const byId = new Map<string, Row>();
  for (const doc of documents) byId.set(doc.id, { documentId: doc.id, filename: doc.filename, earlier: [] });
  for (const group of groupRunsByDocument(runs)) {
    const existing = byId.get(group.documentId);
    byId.set(group.documentId, {
      documentId: group.documentId,
      filename: existing?.filename ?? group.latest.submittal_filename ?? "(unnamed document)",
      latest: group.latest,
      earlier: group.earlier,
    });
  }
  return [...byId.values()];
}

export function DocumentsFromContractors(
  { documents, runs, submittalsTotal, onReview, onOpenRun, startingDocumentId }: {
    documents: DocumentRecord[];
    runs: ReviewRunSummary[];
    submittalsTotal: number | null;
    onReview: (documentId: string) => void;
    onOpenRun?: (runId: string) => void;
    startingDocumentId: string | null;
  },
) {
  const [filter, setFilter] = useState<InboxFilter>("needs_me");
  const rows = rowsFor(documents, runs).map((row) => ({ ...row, state: inboxStateOf(row.latest) }));
  const shown = rows.filter((row) => inFilter(row.state, filter));
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
      <div role="group" aria-label="Show documents" className="flex flex-wrap gap-2">
        {FILTERS.map((chip) => {
          const count = rows.filter((row) => inFilter(row.state, chip.id)).length;
          return (
            <button
              key={chip.id}
              type="button"
              aria-pressed={filter === chip.id}
              onClick={() => setFilter(chip.id)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                filter === chip.id
                  ? "border-signal-500 bg-signal-500/15 text-signal-300"
                  : "border-ink-600 text-slateish-300"
              }`}
            >
              {/* Every count with its boundary: of the documents listed here. */}
              {chip.label} ({count} of {rows.length})
            </button>
          );
        })}
      </div>
      {shown.length === 0 && (
        <p className="text-sm text-slateish-300" data-testid="inbox-empty">
          No document listed here is in this group.
        </p>
      )}
      <ul className="space-y-2">
        {shown.map((row) => (
          <li
            key={row.documentId}
            className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
          >
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-slateish-100">{row.filename}</p>
                <p className="mt-1 text-xs text-slateish-400" data-testid="inbox-state">
                  {stateLabel(row.state)}
                  {row.latest && row.state.kind !== "signed" ? ` · ${whenLabel(row.latest.created_at)}` : ""}
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
            </div>
            {row.earlier.length > 0 && onOpenRun && (
              <details className="mt-2 text-xs text-slateish-300">
                <summary className="cursor-pointer">Earlier runs ({row.earlier.length})</summary>
                <ul className="mt-1 space-y-1">
                  {row.earlier.map((run) => (
                    <li key={run.review_run_id} className="flex flex-wrap items-center gap-2">
                      <span>{whenLabel(run.created_at) || "date not recorded"}</span>
                      <span>· {stateLabel(inboxStateOf(run))}</span>
                      <button
                        type="button"
                        onClick={() => onOpenRun(run.review_run_id)}
                        className="underline"
                        aria-label={`Open the run of ${whenLabel(run.created_at) || "unknown date"}`}
                      >
                        Open
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
