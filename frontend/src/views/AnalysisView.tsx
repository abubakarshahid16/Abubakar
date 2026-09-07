/**
 * Composes the analysis cards into one readable column.
 *
 * Display order is mandated by RAG-INTELLIGENCE-POC-EXECUTION.md section 7.2:
 *   Summary -> AI Recommendation -> Gap Analysis -> Market -> Claim comparison
 *   -> Coverage ledger / Sources.
 * The recommendation is COMPUTED last (after gaps and market) but DISPLAYED
 * second. That is a backend ordering concern; this view only orders the DOM.
 *
 * Rules this view enforces rather than delegates:
 *  - While running, the coverage/progress card is sticky at the top and never
 *    disappears. Cancel is a two-click confirm (destructive action rule).
 *  - Running with no result yet shows plain grey blocks - no shimmer, no spinner
 *    loops - and says plainly why there is no percentage.
 *  - A refused question (status "insufficient_evidence") shows the refusal and
 *    NO summary and NO recommendation. A refusal has no synthesis.
 *  - A cancelled run renders no SummaryCard; CoverageLedger carries the
 *    cancelled message.
 *  - Gap / Market / Recommendation render nothing at all when their toggle is
 *    off. Not a placeholder, not "disabled" - nothing.
 *  - Collapsible cards keep their warnings (AI advisory, sample data, OCR,
 *    "analysis is partial") in the <summary> line so collapsing cannot hide them.
 *
 * Data and callbacks come in as props. Evidence selection goes out through
 * onCite; the parent owns the evidence drawer, exactly as ChatView does.
 */
import { useEffect, useState, type ReactNode } from "react";

import { ClaimTable } from "../components/analysis/ClaimTable";
import { CoverageLedger } from "../components/analysis/CoverageLedger";
import { GapAnalysisCard } from "../components/analysis/GapAnalysisCard";
import { MarketPanel } from "../components/analysis/MarketPanel";
import { RecommendationCard } from "../components/analysis/RecommendationCard";
import { SummaryCard } from "../components/analysis/SummaryCard";
import type {
  AnalysisResult,
  BaselineSelection,
  EgressState,
  PublicMarketQuery,
} from "../types/analysis";

export interface AnalysisViewProps {
  /** null = nothing has been run yet */
  result: AnalysisResult | null;
  running: boolean;
  documents: { id: string; filename: string }[];
  egress: EgressState;
  onCancel?: () => void;
  onCite: (evidenceId: string) => void;
  onGenerateReport?: () => void;
  onSuggestCorrection?: () => void;
  onNominateBaseline?: (b: BaselineSelection) => void;
  onPreviewQuery?: (q: PublicMarketQuery) => void;
  pendingQuery?: PublicMarketQuery | null;
  onConfirmQuery?: () => void;
  onCancelQuery?: () => void;
  toggles: { gaps: boolean; market: boolean; recommendation: boolean };
}

const RUNNING_COPY =
  "Running — completed batches are reported as they finish; there is no percentage because total duration is unknown.";

// ------------------------------------------------------------------ helpers

/** Plain grey blocks. No animation: reduced-motion by default, not by media query. */
function Skeleton({ lines, label }: { lines: number; label: string }) {
  return (
    <div
      aria-label={label}
      role="img"
      className="rounded-lg border border-ink-700 bg-ink-850 p-4"
    >
      <div className="h-3 w-40 rounded bg-ink-700" />
      <div className="mt-3 space-y-2">
        {Array.from({ length: lines }, (_, i) => (
          <div
            key={i}
            className="h-3 rounded bg-ink-700"
            style={{ width: `${[92, 78, 85, 64, 88][i % 5]}%` }}
          />
        ))}
      </div>
    </div>
  );
}

/** Two-click cancel: first click asks, second confirms. Escape / blur resets. */
function CancelButton({ onCancel }: { onCancel: () => void }) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setArmed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [armed]);

  if (!armed) {
    return (
      <button
        type="button"
        onClick={() => setArmed(true)}
        className="rounded border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
      >
        Cancel analysis?
      </button>
    );
  }

  return (
    <div role="group" aria-label="Confirm cancel" className="flex items-center gap-2">
      <button
        type="button"
        autoFocus
        onClick={() => {
          setArmed(false);
          onCancel();
        }}
        className="rounded border border-danger-500/60 bg-danger-500/10 px-3 py-1.5 text-sm font-medium text-danger-500 hover:bg-danger-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-danger-500"
      >
        Yes, cancel
      </button>
      <button
        type="button"
        onClick={() => setArmed(false)}
        className="rounded px-3 py-1.5 text-sm text-slateish-300 hover:bg-ink-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
      >
        Keep running
      </button>
    </div>
  );
}

function WarnBadge({ children }: { children: ReactNode }) {
  return (
    <span className="ml-2 inline-block rounded border border-warn-500/50 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-warn-500">
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------- view

export function AnalysisView({
  result,
  running,
  documents,
  egress,
  onCancel,
  onCite,
  onGenerateReport,
  onSuggestCorrection,
  onNominateBaseline,
  onPreviewQuery,
  pendingQuery,
  onConfirmQuery,
  onCancelQuery,
  toggles,
}: AnalysisViewProps) {
  const refused = result?.status === "insufficient_evidence";
  const cancelled = result?.run_status === "cancelled";
  const partial = result?.coverage.complete === false;
  const usesOcr =
    result?.evidence_ledger.some((e) => e.text_source === "recognised") ?? false;

  // A refusal or a cancellation has no synthesis. Everything else may.
  const showSummary = result !== null && !refused && !cancelled;
  const showRecommendation = result !== null && toggles.recommendation && !refused;
  const showGaps = result !== null && toggles.gaps;
  const showMarket = result !== null && toggles.market;

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-ink-700 bg-ink-900">
      {/* Persistent progress card. Sticky so it stays in view while the
          reader scrolls partial results underneath it. */}
      {running && (
        <header
          role="status"
          aria-live="polite"
          className="sticky top-0 z-10 border-b border-ink-700 bg-ink-900/95 px-4 py-3"
        >
          <div className="mx-auto flex max-w-[72ch] flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-wide text-slateish-500">Analysis running</p>
              <p className="mt-1 text-sm text-slateish-300">{RUNNING_COPY}</p>
              {result && (
                <p className="mt-1 font-mono text-sm text-slateish-200">
                  {result.batches_total != null
                    ? `${result.batches_done ?? 0} of ${result.batches_total} batches done`
                    : result.run_status.replace(/_/g, " ")}
                  {result.coverage.documents_search_completed != null &&
                    ` · ${result.coverage.documents_search_completed} of ${result.coverage.authorized_documents_selected} documents searched`}
                </p>
              )}
            </div>
            {onCancel && <CancelButton onCancel={onCancel} />}
          </div>
        </header>
      )}

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto max-w-[72ch] space-y-5">
          {/* Nothing run yet, not running: say so plainly. */}
          {result === null && !running && (
            <div className="rounded-lg border border-dashed border-ink-600 bg-ink-850/60 p-10 text-center">
              <p className="text-slateish-300">No analysis has been run.</p>
              <p className="mt-1 text-sm text-slateish-400">
                Choose a mode and ask a question. Results appear here, with every claim tied to a
                passage you can open.
              </p>
            </div>
          )}

          {/* Running, nothing back yet: grey blocks, never a frozen page. */}
          {result === null && running && (
            <div aria-busy="true" className="space-y-5">
              <Skeleton lines={4} label="Summary placeholder while the analysis runs" />
              {toggles.recommendation && (
                <Skeleton lines={3} label="Recommendation placeholder while the analysis runs" />
              )}
              {toggles.gaps && <Skeleton lines={3} label="Gap analysis placeholder while the analysis runs" />}
              {toggles.market && <Skeleton lines={2} label="Market placeholder while the analysis runs" />}
              <Skeleton lines={5} label="Coverage ledger placeholder while the analysis runs" />
            </div>
          )}

          {result && (
            <>
              <section aria-labelledby="analysis-question-heading">
                <h2 id="analysis-question-heading" className="sr-only">
                  Question
                </h2>
                <p className="rounded-lg bg-ink-700 px-3 py-2 text-[15px] text-slateish-100">
                  {result.question}
                </p>
              </section>

              {/* Refusal: prominent, and nothing synthesised follows it. */}
              {refused && (
                <section
                  role="alert"
                  aria-labelledby="analysis-refused-heading"
                  className="rounded-lg border border-warn-500/60 bg-warn-500/10 p-4"
                >
                  <h2
                    id="analysis-refused-heading"
                    className="text-[11px] font-semibold uppercase tracking-wider text-warn-500"
                  >
                    No answer &mdash; insufficient evidence
                  </h2>
                  <p className="mt-2 text-[15px] text-slateish-200">
                    The retrieved passages do not support an answer to this question, so no summary
                    and no recommendation were generated.
                  </p>
                  {result.limitations.length > 0 && (
                    <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slateish-300">
                      {result.limitations.map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-3 border-t border-warn-500/30 pt-2 text-xs text-slateish-400">
                    The coverage ledger below shows which documents were searched and what each
                    returned.
                  </p>
                </section>
              )}

              {/* 1. Summary */}
              {showSummary && (
                <section aria-labelledby="analysis-summary-heading">
                  <h2 id="analysis-summary-heading" className="mb-2 text-sm font-semibold text-slateish-200">
                    Summary
                    {partial && <WarnBadge>analysis is partial</WarnBadge>}
                    {usesOcr && <WarnBadge>cites recognised (OCR) text</WarnBadge>}
                  </h2>
                  <SummaryCard result={result} onCite={onCite} onSuggestCorrection={onSuggestCorrection} />
                </section>
              )}

              {/* 2. AI Recommendation - RecommendationCard is itself a <details>
                     with the advisory label in its <summary>, so it is not
                     wrapped in a second one. */}
              {showRecommendation && (
                <section aria-labelledby="analysis-recommendation-heading">
                  <h2 id="analysis-recommendation-heading" className="mb-2 text-sm font-semibold text-slateish-200">
                    AI Recommendation
                    <WarnBadge>advisory</WarnBadge>
                    {partial && <WarnBadge>analysis is partial</WarnBadge>}
                  </h2>
                  <RecommendationCard recommendation={result.recommendation} onCite={onCite} />
                </section>
              )}

              {/* 3. Gap analysis */}
              {showGaps && (
                <section aria-labelledby="analysis-gaps-heading">
                  <details open className="group">
                    <summary className="cursor-pointer list-item rounded px-1 py-1 text-sm font-semibold text-slateish-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400">
                      <span id="analysis-gaps-heading">Gap Analysis</span>
                      <WarnBadge>preliminary</WarnBadge>
                      {partial && <WarnBadge>analysis is partial</WarnBadge>}
                      {usesOcr && <WarnBadge>OCR text involved</WarnBadge>}
                    </summary>
                    <div className="mt-2">
                      <GapAnalysisCard
                        gaps={result.gaps}
                        onNominateBaseline={onNominateBaseline}
                        documents={documents}
                        onCite={onCite}
                      />
                    </div>
                  </details>
                </section>
              )}

              {/* 4. Public market */}
              {showMarket && (
                <section aria-labelledby="analysis-market-heading">
                  <details open>
                    <summary className="cursor-pointer list-item rounded px-1 py-1 text-sm font-semibold text-slateish-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400">
                      <span id="analysis-market-heading">Public Market Information</span>
                      <WarnBadge>sample data &mdash; not live</WarnBadge>
                    </summary>
                    <div className="mt-2">
                      <MarketPanel
                        findings={result.public_market_findings}
                        egress={egress}
                        onPreviewQuery={onPreviewQuery}
                        pendingQuery={pendingQuery}
                        onConfirmQuery={onConfirmQuery}
                        onCancelQuery={onCancelQuery}
                      />
                    </div>
                  </details>
                </section>
              )}

              {/* 5. Claim comparison - verbatim, so it survives refusal and cancel. */}
              <section aria-labelledby="analysis-claims-heading">
                <h2 id="analysis-claims-heading" className="mb-2 text-sm font-semibold text-slateish-200">
                  Claim comparison
                </h2>
                <ClaimTable clusters={result.claim_clusters} onCite={onCite} />
              </section>

              {/* 6. Coverage ledger / sources */}
              <section aria-labelledby="analysis-coverage-heading">
                <h2 id="analysis-coverage-heading" className="mb-2 text-sm font-semibold text-slateish-200">
                  Coverage and sources
                </h2>
                <CoverageLedger result={result} />

                {result.evidence_ledger.length > 0 && (
                  <div className="mt-3 rounded-lg border border-ink-600 bg-ink-850 p-4">
                    <h3 className="text-xs uppercase tracking-wide text-slateish-500">
                      Cited passages ({result.evidence_ledger.length})
                    </h3>
                    <ol className="mt-2 space-y-1.5 text-sm">
                      {result.evidence_ledger.map((e, i) => (
                        <li key={e.evidence_id} className="flex items-baseline gap-2">
                          <span className="font-mono text-xs text-slateish-500">[{i + 1}]</span>
                          <button
                            type="button"
                            onClick={() => onCite(e.evidence_id)}
                            className="min-w-0 text-left text-slateish-200 underline decoration-ink-500 underline-offset-2 hover:decoration-signal-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
                          >
                            <span className="truncate">{e.filename}</span>
                            <span className="ml-1 text-slateish-500">
                              p.{e.page_start}
                              {e.page_end !== e.page_start && `–${e.page_end}`}
                              {e.section && ` · ${e.section}`}
                            </span>
                            {e.text_source === "recognised" && (
                              <span className="ml-1 text-[11px] uppercase tracking-wider text-slateish-500">
                                OCR
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {(result.assumptions.length > 0 ||
                  result.limitations.length > 0 ||
                  result.not_implemented_sections.length > 0) && (
                  <div className="mt-3 rounded-lg border border-ink-600 bg-ink-850 p-4 text-sm">
                    {result.assumptions.length > 0 && (
                      <>
                        <h3 className="text-xs uppercase tracking-wide text-slateish-500">Assumptions</h3>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-slateish-300">
                          {result.assumptions.map((a, i) => (
                            <li key={i}>{a}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {result.limitations.length > 0 && !refused && (
                      <>
                        <h3 className="mt-3 text-xs uppercase tracking-wide text-slateish-500">Limitations</h3>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-slateish-300">
                          {result.limitations.map((l, i) => (
                            <li key={i}>{l}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {result.not_implemented_sections.length > 0 && (
                      <>
                        <h3 className="mt-3 text-xs uppercase tracking-wide text-slateish-500">
                          Not produced by this build
                        </h3>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-slateish-400">
                          {result.not_implemented_sections.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </section>
            </>
          )}

          {onGenerateReport && (
            <footer className="border-t border-ink-700 pt-4">
              <button
                type="button"
                onClick={onGenerateReport}
                disabled={running || result === null}
                className="rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
              >
                Generate report
              </button>
              <p className="mt-1.5 text-xs text-slateish-500">
                Single-answer evidence report. Names every section this build does not produce.
              </p>
            </footer>
          )}
        </div>
      </main>
    </div>
  );
}
