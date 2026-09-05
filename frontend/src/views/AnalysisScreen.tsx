/**
 * Container for AnalysisView: owns the three calls and assembles one result.
 *
 * The three engines are SEPARATE endpoints and are called separately, so a
 * model that is down takes out the summary and the recommendation and leaves
 * the gap analysis - which needs no model - still working. One combined
 * endpoint would have made an unreachable Ollama look like a broken
 * comparison.
 *
 * Nothing here invents a baseline. `baseline_document_id` is whatever the
 * reader nominated, and with no nomination the gap analysis comes back
 * `not_applicable` rather than measured against a document the system chose.
 *
 * TWO VALUES THIS FILE MAY NEVER PRODUCE: `coverage.complete === true` and
 * `confidence === "high"`. Neither is computed here - `complete` is fixed at
 * null because this build computes no per-document coverage for an analysis,
 * and null renders as nothing at all rather than as a tick.
 */
import { useCallback, useEffect, useState } from "react";

import { analysis as analysisApi, api, market as marketApi } from "../api/client";
import type {
  AnalysisResult,
  BaselineSelection,
  EgressState,
  PublicMarketQuery,
} from "../types/analysis";
import { AnalysisView } from "./AnalysisView";

const BLOCKED: EgressState = { web_search_enabled: false, allow_public_egress: false };

/** Everything this build does not compute, stated once. Null, never zero:
 *  a zero is a measurement and none of these has been measured. */
const NO_COVERAGE: AnalysisResult["coverage"] = {
  authorized_documents_selected: 0,
  documents_attempted: null,
  documents_search_completed: null,
  relevant_documents: null,
  no_sufficient_evidence_documents: null,
  failed_documents: null,
  not_searchable_documents: null,
  // false or null, never true - the same rule the answer coverage follows.
  complete: null,
};

export function AnalysisScreen() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [running, setRunning] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [documents, setDocuments] = useState<{ id: string; filename: string }[]>([]);
  const [baseline, setBaseline] = useState<BaselineSelection | null>(null);
  const [egress, setEgress] = useState<EgressState>(BLOCKED);
  const [pendingQuery, setPendingQuery] = useState<PublicMarketQuery | null>(null);
  const [toggles] = useState({ gaps: true, market: true, recommendation: true });

  useEffect(() => {
    void (async () => {
      const [docs, mk] = await Promise.all([api.documents(), marketApi.findings()]);
      if (docs.ok) {
        setDocuments(docs.data.map((d) => ({ id: d.id, filename: d.filename })));
      }
      // On a failed market load the state stays empty and BLOCKED. Defaulting
      // to "egress allowed" on an unreadable response is the wrong direction
      // to fail.
      if (mk.ok) setEgress(mk.data.egress);
    })();
  }, []);

  const run = useCallback(async () => {
    const q = question.trim();
    if (!q) return;
    setRunning(true);
    setErrors([]);
    const body = { question: q, baseline_document_id: baseline?.document_id ?? null };

    // Gaps first and on its own: it needs no model, so it must not be lost to
    // a generation that fails.
    const gaps = await analysisApi.gaps(body);
    const [summary, recommendation] = await Promise.all([
      analysisApi.summary(body),
      analysisApi.recommendations(body),
    ]);

    const failures: string[] = [];
    if (!gaps.ok) failures.push(`Gap analysis: ${gaps.error.message}`);
    if (!summary.ok) failures.push(`Summary: ${summary.error.message}`);
    if (!recommendation.ok) failures.push(`Recommendation: ${recommendation.error.message}`);

    // The evidence ledger is whichever engine answered. Gaps is preferred
    // because it runs without a model, so a citation still resolves to a
    // document and a page when generation failed.
    const ledger =
      (gaps.ok && gaps.data.evidence_ledger) ||
      (summary.ok && summary.data.evidence_ledger) ||
      (recommendation.ok && recommendation.data.evidence_ledger) ||
      [];

    setResult({
      analysis_id: "",
      question: q,
      run_status: failures.length === 3 ? "failed" : "complete",
      status: ledger.length === 0 ? "insufficient_evidence" : "answered",
      coverage: { ...NO_COVERAGE, authorized_documents_selected: documents.length },
      documents: [],
      evidence_ledger: ledger,
      documented_findings: summary.ok ? summary.data.documented_findings : [],
      summary: summary.ok ? summary.data.summary : null,
      summary_truncated: summary.ok ? summary.data.summary_truncated : false,
      summary_cited_evidence_ids: summary.ok ? summary.data.summary_cited_evidence_ids : [],
      claim_clusters: gaps.ok ? (gaps.data.claim_clusters as never) : [],
      gaps: gaps.ok
        ? (gaps.data.gaps as never)
        : { applicability: "insufficient_baseline", baseline: null, items: [] },
      public_market_findings: recommendation.ok
        ? recommendation.data.public_market_findings
        : [],
      recommendation: recommendation.ok
        ? (recommendation.data.recommendation as never)
        : null,
      assumptions: [],
      limitations: failures,
      not_implemented_sections: gaps.ok
        ? gaps.data.not_implemented_sections
        : summary.ok
          ? summary.data.not_implemented_sections
          : [],
      batches_done: null,
      batches_total: null,
      seconds: null,
    });
    setRunning(false);
  }, [question, baseline, documents.length]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-slateish-200">Analysis</h1>
        <p className="mt-1 text-sm text-slateish-400">
          A summary, an advisory recommendation and a mechanical comparison of what
          the documents claim. Every sentence carries the document and page it came
          from; anything that does not is removed rather than shown.
        </p>
      </header>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <label htmlFor="analysis-question" className="sr-only">
          Your question
        </label>
        <input
          id="analysis-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What coating thickness is required, and what does each document say?"
          className="min-w-0 flex-1 rounded border border-ink-600 bg-ink-850 px-3 py-2 text-slateish-100 placeholder:text-slateish-500"
        />
        <button
          type="submit"
          disabled={running || !question.trim()}
          className="rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30 disabled:opacity-40"
        >
          {running ? "Running…" : "Analyse"}
        </button>
      </form>

      {errors.length > 0 && (
        <ul className="rounded border border-warn-500/40 bg-warn-500/[0.08] px-3 py-2 text-xs text-warn-500">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <AnalysisView
        result={result}
        running={running}
        documents={documents}
        egress={egress}
        onCite={() => {}}
        onNominateBaseline={setBaseline}
        onPreviewQuery={setPendingQuery}
        pendingQuery={pendingQuery}
        onConfirmQuery={() => setPendingQuery(null)}
        onCancelQuery={() => setPendingQuery(null)}
        toggles={toggles}
      />
    </div>
  );
}
