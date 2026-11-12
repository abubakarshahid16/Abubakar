/**
 * "AI review of this document": the FIRST thing on a review page that has an
 * AI review. What it is in one sentence, the counts in plain words, the two
 * CRS files with one line each, and "See every point". Drawn only when the
 * run has an AI review. Counts are over the lines of this review.
 */
import { useState } from "react";

import type { AgentOverview } from "./useAgentOverview";
import { downloadAgentCrs } from "./downloadAgentCrs";
import {
  AI_PANEL_TITLE, AI_PANEL_WHAT, CONTRACTOR_CRS_LINE, CONTRACTOR_EMPTY_LINE, INTERNAL_CRS_LINE, classCountsSentence,
  countsSentence, missingWords, pagesTakenWords,
} from "./plainWords";

const BTN = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm";

export function AiReviewPanel({ runId, overview, onSeeEvery, pageCoverage = null }: {
  runId: string; overview: AgentOverview; onSeeEvery: () => void;
  /** The run's page record (`run.page_coverage`); says where it came from when it was copied. */
  pageCoverage?: { carried_from_run?: string | null; carried_from_at?: string | null } | null;
}) {
  const [fileError, setFileError] = useState<string | null>(null);
  if (overview.state !== "ok") return null;
  const { summary, lines } = overview;
  const counts = lines ? countsSentence(lines, "Proven by code" in summary.counts_by_class) : classCountsSentence(summary.counts_by_class);
  const provenFails = lines ? lines.filter((l) => l.verdict_class === "Proven by code" && l.word === "Fail").length : null;

  async function download(copy: "internal" | "contractor") {
    setFileError(null);
    const message = await downloadAgentCrs(runId, copy);
    if (message) setFileError(message);
  }

  return (
    <section aria-labelledby="ai-panel-title" data-testid="ai-review-panel"
      className="space-y-3 rounded-[var(--radius-md)] border border-signal-500/50 bg-ink-900 p-4">
      <h2 id="ai-panel-title" className="text-lg font-semibold text-slateish-100">{AI_PANEL_TITLE}</h2>
      <p className="text-sm text-slateish-200">{AI_PANEL_WHAT}</p>
      <p data-testid="ai-panel-counts" className="text-base text-slateish-100">{counts}</p>
      {overview.missing && (overview.missing.cited + overview.missing.other > 0) && (
        <p data-testid="ai-panel-missing" className="text-sm text-slateish-200">{missingWords(overview.missing)}</p>
      )}
      {pagesTakenWords(pageCoverage) && <p data-testid="ai-panel-pages" className="text-sm text-slateish-200">{pagesTakenWords(pageCoverage)}</p>}
      <ul className="space-y-2 text-sm">
        <li className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void download("internal")} className={`${BTN} border-signal-500 text-signal-300`}>
            Download CRS, internal copy
          </button>
          <span className="text-slateish-300">{INTERNAL_CRS_LINE}</span>
        </li>
        <li className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void download("contractor")} className={`${BTN} border-ink-600 text-slateish-100`}>
            Download CRS, contractor copy
          </button>
          <span className="text-slateish-300">{CONTRACTOR_CRS_LINE}</span>
        </li>
      </ul>
      {provenFails === 0 && <p data-testid="ai-panel-contractor-empty" className="text-sm text-slateish-300">{CONTRACTOR_EMPTY_LINE}</p>}
      {fileError && <p role="alert" className="text-sm text-red-400">{fileError}</p>}
      <button type="button" onClick={onSeeEvery} className={`${BTN} border-ink-600 text-slateish-100`}>See every point</button>
    </section>
  );
}
