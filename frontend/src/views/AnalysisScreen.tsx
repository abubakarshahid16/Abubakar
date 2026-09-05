/**
 * Container for AnalysisView: owns the three calls, hands the view its props.
 *
 * The three engines are separate endpoints and are called separately, so a
 * model that is down takes out the summary and the recommendation and leaves
 * the gap analysis - which needs no model - still working. A single combined
 * endpoint would have made an unreachable Ollama look like a broken
 * comparison.
 *
 * Nothing here invents a baseline. `baseline_document_id` is whatever the
 * reader chose, and with no choice the gap analysis comes back
 * `not_applicable` rather than measured against a document the system picked.
 */
import { useCallback, useState } from "react";

import { analysis as analysisApi } from "../api/client";
import type {
  AnalysisGapsResult,
  AnalysisRecommendationResult,
  AnalysisSummaryResult,
} from "../types/api";

export type AnalysisState = {
  summary: AnalysisSummaryResult | null;
  gaps: AnalysisGapsResult | null;
  recommendation: AnalysisRecommendationResult | null;
  running: boolean;
  /** Per-engine, because they fail independently. */
  errors: string[];
};

const EMPTY: AnalysisState = {
  summary: null,
  gaps: null,
  recommendation: null,
  running: false,
  errors: [],
};

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>(EMPTY);

  const run = useCallback(
    async (question: string, baseline_document_id: string | null = null) => {
      setState({ ...EMPTY, running: true });
      const body = { question, baseline_document_id };

      // Gaps first and on its own: it needs no model, so it must not be
      // held up by - or lost to - a generation that fails.
      const gaps = await analysisApi.gaps(body);
      const [summary, recommendation] = await Promise.all([
        analysisApi.summary(body),
        analysisApi.recommendations(body),
      ]);

      const errors: string[] = [];
      if (!gaps.ok) errors.push(`Gap analysis: ${gaps.error.message}`);
      if (!summary.ok) errors.push(`Summary: ${summary.error.message}`);
      if (!recommendation.ok) {
        errors.push(`Recommendation: ${recommendation.error.message}`);
      }

      setState({
        summary: summary.ok ? summary.data : null,
        gaps: gaps.ok ? gaps.data : null,
        recommendation: recommendation.ok ? recommendation.data : null,
        running: false,
        errors,
      });
    },
    [],
  );

  return { ...state, run };
}
