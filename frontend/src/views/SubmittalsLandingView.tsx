/**
 * AI Submittal Review: the landing page.
 *
 * #967 PR1 (Stage D redesign, build order item 1 of 4 - a datasheet
 * proofreader starts from the document). Replaces the run-picker and
 * run-card list that used to be the first thing an engineer saw on this
 * page: one row per document from a contractor, one Review button. The
 * review itself - selecting standards, comparing requirements, the
 * findings table - is unchanged; this page only decides which run to open,
 * starting one if none exists yet.
 */
import { useCallback, useEffect, useState } from "react";

import { api, reviews as reviewsApi } from "../api/client";
import type { DocumentRecord, ReviewRunSummary } from "../types/api";
import { DocumentsFromContractors } from "../components/review/DocumentsFromContractors";
import { LIST_MAX, groupRunsByDocument, totalFromResponse } from "../components/review/reviewFormat";

type Phase = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

export function SubmittalsLandingView({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [submittalsTotal, setSubmittalsTotal] = useState<number | null>(null);
  const [runs, setRuns] = useState<ReviewRunSummary[]>([]);
  const [startingDocumentId, setStartingDocumentId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [subs, runsResult] = await Promise.all([
      api.documents({ document_role: ["CONTRACTOR_SUBMITTAL"], limit: LIST_MAX }),
      reviewsApi.reviewRuns(),
    ]);
    if (!runsResult.ok) {
      setPhase({ kind: "error", message: runsResult.error.message });
      return;
    }
    setSubmittalsTotal(subs.ok ? totalFromResponse(subs.response) : null);
    setDocuments(subs.ok ? subs.data : []);
    setRuns(runsResult.data.runs);
    setPhase({ kind: "ready" });
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function reviewDocument(documentId: string) {
    const existing = groupRunsByDocument(runs).find((group) => group.documentId === documentId);
    if (existing) {
      onOpenRun(existing.latest.review_run_id);
      return;
    }
    setStartError(null);
    setStartingDocumentId(documentId);
    const result = await reviewsApi.startReviewRun(documentId);
    setStartingDocumentId(null);
    if (!result.ok) {
      // SHOWN AS THE API RETURNED IT - a refusal (a review already running
      // for this document) is a real answer, not a reason to retry silently.
      setStartError(result.error.message);
      return;
    }
    onOpenRun(result.data.review_run_id);
  }

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6" aria-labelledby="submittals-landing-title">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-signal-400">
          AI Submittal Review
        </p>
        <h1 id="submittals-landing-title" className="mt-2 text-3xl font-semibold text-slateish-100">
          Documents from contractors
        </h1>
        <p className="mt-2 max-w-3xl text-slateish-300">
          Each review compares one contractor submittal against the standards
          that apply to it, and records a finding per requirement with both
          citations.
        </p>
      </header>

      {phase.kind === "loading" && <p className="text-slateish-300">Loading documents…</p>}
      {phase.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">
          {phase.message}
        </p>
      )}
      {startError && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">
          {startError}
        </p>
      )}

      {phase.kind === "ready" && (
        <DocumentsFromContractors
          documents={documents} runs={runs} submittalsTotal={submittalsTotal}
          onReview={(documentId) => void reviewDocument(documentId)}
          startingDocumentId={startingDocumentId}
        />
      )}
    </main>
  );
}
