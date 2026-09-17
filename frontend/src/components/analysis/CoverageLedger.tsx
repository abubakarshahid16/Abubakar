/**
 * Which documents were searched, which contributed, which failed.
 *
 * The rules, inherited from CoverageNote: a NULL renders as NOTHING. No tick,
 * no green, no "complete" - `coverage.complete` is `false | null` and there is
 * no positive state to draw. A null count is omitted from the header line
 * rather than shown as 0, because "did not measure" and "measured zero" are
 * different facts and only one of them is reassuring.
 *
 * The table is paginated. Never the whole corpus at once.
 */
import { useState } from "react";

import type { AnalysisResult, PerDocumentStatus } from "../../types/analysis";

const STATUS_TEXT: Record<PerDocumentStatus, { icon: string; label: string }> = {
  relevant: { icon: "●", label: "Contributed evidence" },
  no_sufficient_evidence: { icon: "○", label: "Searched, nothing credible" },
  failed: { icon: "✕", label: "Failed to search" },
  not_searchable: { icon: "∅", label: "Not yet searchable" },
  pending: { icon: "…", label: "Waiting" },
  searching: { icon: "◌", label: "Searching…" },
  cancelled: { icon: "–", label: "Cancelled" },
};

function statusTone(s: PerDocumentStatus): string {
  switch (s) {
    case "relevant":
      return "text-signal-400";
    case "failed":
      return "text-danger-500";
    case "not_searchable":
    case "cancelled":
      return "text-warn-500";
    default:
      return "text-slateish-400";
  }
}

const RUN_FINISHED = new Set(["complete", "cancelled", "failed"]);

export function CoverageLedger({
  result,
  pageSize = 20,
}: {
  result: AnalysisResult;
  pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const c = result.coverage;

  // Only the counts that were measured. A null contributes no segment.
  const segments: string[] = [`${c.authorized_documents_selected} authorized`];
  if (c.documents_search_completed != null) segments.push(`${c.documents_search_completed} searched`);
  if (c.relevant_documents != null) segments.push(`${c.relevant_documents} relevant`);
  if (c.no_sufficient_evidence_documents != null)
    segments.push(`${c.no_sufficient_evidence_documents} no sufficient evidence`);
  if (c.failed_documents != null) segments.push(`${c.failed_documents} failed`);
  if (c.not_searchable_documents != null) segments.push(`${c.not_searchable_documents} not searchable`);

  const running = !RUN_FINISHED.has(result.run_status);
  const cancelled = result.run_status === "cancelled";

  const total = result.documents.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, pages - 1);
  const rows = result.documents.slice(current * pageSize, (current + 1) * pageSize);

  return (
    <section aria-labelledby="coverage-ledger-heading" className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <p id="coverage-ledger-heading" className="text-xs uppercase tracking-wide text-slateish-500">
        Coverage
      </p>
      <p className="mt-1 font-mono text-sm text-slateish-200">{segments.join(" · ")}</p>

      {c.complete === false && (
        <p className="mt-2 text-xs font-semibold uppercase tracking-wider text-warn-500">
          This analysis is partial
        </p>
      )}

      {running && (
        <p role="status" aria-live="polite" className="mt-2 text-sm text-slateish-300">
          {result.batches_total != null
            ? `${result.batches_done ?? 0} of ${result.batches_total} batches synthesised`
            : "synthesising…"}
        </p>
      )}

      {cancelled && (
        <p role="status" className="mt-2 rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-sm text-warn-500">
          Cancelled — partial results below are batches, not a consolidated answer
        </p>
      )}

      {total > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Per-document search outcome</caption>
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slateish-500">
                <th scope="col" className="py-1 pr-3 font-normal">Document</th>
                <th scope="col" className="py-1 pr-3 font-normal">Status</th>
                <th scope="col" className="py-1 pr-3 text-right font-normal">Validated passages</th>
                <th scope="col" className="py-1 font-normal">Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const st = STATUS_TEXT[d.status];
                return (
                  <tr key={d.document_id} className="border-t border-ink-700/60">
                    <td className="py-1.5 pr-3 text-slateish-200">{d.filename}</td>
                    <td className={`py-1.5 pr-3 ${statusTone(d.status)}`}>
                      <span aria-hidden="true" className="mr-1.5 font-mono">{st.icon}</span>
                      {st.label}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slateish-300">
                      {/* null = did not search; 0 = searched, found nothing. */}
                      {d.validated_evidence_count === null ? (
                        <span aria-label="not searched">—</span>
                      ) : (
                        d.validated_evidence_count
                      )}
                    </td>
                    <td className="py-1.5 font-mono text-xs text-danger-500">{d.error_code ?? ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {pages > 1 && (
            <nav aria-label="Coverage table pages" className="mt-2 flex items-center justify-between text-xs text-slateish-400">
              <button
                type="button"
                aria-label="Previous page of documents"
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
                className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-1 hover:bg-ink-700 disabled:opacity-40"
              >
                Prev
              </button>
              <span aria-live="polite">
                {current * pageSize + 1}–{Math.min(total, (current + 1) * pageSize)} of {total} documents
              </span>
              <button
                type="button"
                aria-label="Next page of documents"
                disabled={current >= pages - 1}
                onClick={() => setPage(current + 1)}
                className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-1 hover:bg-ink-700 disabled:opacity-40"
              >
                Next
              </button>
            </nav>
          )}
        </div>
      )}

      {result.not_implemented_sections.length > 0 && (
        <p className="mt-3 border-t border-ink-700/60 pt-2 text-xs text-slateish-500">
          Not included in this analysis: {result.not_implemented_sections.join(", ")}
        </p>
      )}
    </section>
  );
}
