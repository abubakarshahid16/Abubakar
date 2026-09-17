import type { RefObject } from "react";
import type { EvidenceItem } from "../../types/api";
import { OcrConfidence, ProvenanceMark, provenanceLabel } from "../../components/chat/Provenance";

export function AnalysisSources({ selectedItem, sourcesRef }: { selectedItem: EvidenceItem | null; sourcesRef: RefObject<HTMLDivElement | null> }) {
  return (
    <div ref={sourcesRef} data-testid="analysis-sources-panel">
      {selectedItem !== null ? (
        <section aria-label="Selected passage" className="card-3d accent-edge relative surface-floating rounded-[var(--radius-md)] border border-signal-500/40 bg-ink-850 p-4">
          <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-slateish-400">
            <span className="font-medium text-slateish-200">{selectedItem.filename}</span>
            <span>p.{selectedItem.page_start}</span>
            {selectedItem.section !== null && <span>&sect; {selectedItem.section}</span>}
            <ProvenanceMark passage={selectedItem} />
          </div>
          <p className="mt-2 text-xs font-medium text-slateish-300">{provenanceLabel(selectedItem)}</p>
          <OcrConfidence passage={selectedItem} />
          <blockquote className="document-quote mt-2 whitespace-pre-wrap border-l-2 border-signal-500/60 bg-ink-900 py-2 ps-4 pe-3 text-[14px] text-slateish-100">
            {selectedItem.exact_span}
          </blockquote>
          {selectedItem.relevance_score !== null && (
            <details className="mt-3 rounded-[var(--radius-xs)] border border-ink-700 px-2.5 py-2 text-xs text-slateish-400">
              <summary className="cursor-pointer">Retrieval details</summary>
              <p className="mt-1">This passage’s {selectedItem.relevance_score_type ?? "retrieval"} score was {selectedItem.relevance_score.toFixed(3)}. It is a ranking diagnostic, not a quality verdict.</p>
            </details>
          )}
        </section>
      ) : (
        <section className="surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Sources</h2>
          <p className="mt-2 text-sm text-slateish-500">Select a citation or evidence row to inspect the exact passage here.</p>
        </section>
      )}
    </div>
  );
}
