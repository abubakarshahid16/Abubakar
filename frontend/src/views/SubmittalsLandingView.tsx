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
import { InboxList } from "../components/review/inbox/InboxList";
import { INBOX_IS_DEFAULT } from "../routing";
import { LIST_MAX, groupRunsByDocument, totalFromResponse } from "../components/review/reviewFormat";
import { type ReadyCounts, anyMoving, inboxStateOf } from "../components/review/inbox/inboxState";

/** Order 95 piece 3: while a review is queued or running, the list re-reads
 *  on this interval so its state moves without a refresh. */
export const INBOX_REFRESH_MS = 15_000;

type Phase = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

/** Order 95 piece 3: what "Review all not reviewed" did, document by document. */
interface BatchResult {
  asked: number;
  queued: number;
  refused: { filename: string; message: string }[];
}

/** #1114: the Ready label's counts come from the run's own summary (#1111);
 *  any failure (a server without the route answers 404) leaves them out. */
async function loadReadyCounts(runId: string): Promise<ReadyCounts | null> {
  const res = await reviewsApi.reviewRunSummary(runId);
  return res.ok ? { comment: res.data.counts.comment, needs_you: res.data.counts.needs_you } : null;
}

export function SubmittalsLandingView({ onOpenRun, inbox = INBOX_IS_DEFAULT, onOpenInbox, onOpenList }: {
  onOpenRun: (runId: string) => void;
  /** Order 95 piece 3: show the inbox (/review/inbox) rather than the list. */
  inbox?: boolean;
  onOpenInbox?: () => void;
  onOpenList?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [submittalsTotal, setSubmittalsTotal] = useState<number | null>(null);
  const [runs, setRuns] = useState<ReviewRunSummary[]>([]);
  const [startingDocumentId, setStartingDocumentId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchResult | null>(null);
  const [batching, setBatching] = useState(false);

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

  const moving = inbox && phase.kind === "ready"
    && anyMoving(groupRunsByDocument(runs).map((group) => inboxStateOf(group.latest)));
  useEffect(() => {
    if (!moving) return undefined;
    const timer = window.setInterval(() => { void load(); }, INBOX_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [moving, load]);

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

  /** Order 95 piece 3: queue a background review for each document never
   *  reviewed, one request each, in list order. The job queue runs them one
   *  at a time; nothing is opened. A refusal is reported per document, never
   *  dropped, and never retried silently. */
  async function reviewAll(targets: { documentId: string; filename: string }[]) {
    setBatching(true);
    setBatch(null);
    const refused: BatchResult["refused"] = [];
    let queued = 0;
    for (const target of targets) {
      const result = await reviewsApi.startReviewRun(target.documentId);
      if (result.ok) queued += 1;
      else refused.push({ filename: target.filename, message: result.error.message });
    }
    setBatch({ asked: targets.length, queued, refused });
    setBatching(false);
    await load();
  }

  return (
    <section className="mx-auto w-full max-w-7xl space-y-6" aria-labelledby="submittals-landing-title">
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

      {batch && (
        <div role="status" className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-4 py-3 text-sm text-slateish-200">
          <p>Queued {batch.queued} of {batch.asked} reviews asked for.</p>
          {batch.refused.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-danger-500">
              {batch.refused.map((r) => <li key={r.filename}>{r.filename}: {r.message}</li>)}
            </ul>
          )}
        </div>
      )}

      {!inbox && onOpenInbox && (
        <p className="text-sm text-slateish-300">
          <button type="button" onClick={onOpenInbox} className="font-medium text-signal-400 hover:underline">
            Try the new inbox
          </button>{" "}
          - where each review stands, filtered to what needs you. This list stays the default for now.
        </p>
      )}
      {inbox && onOpenList && (
        <p className="text-sm text-slateish-300">
          <button type="button" onClick={onOpenList} className="font-medium text-signal-400 hover:underline">
            Back to the current list
          </button>
        </p>
      )}

      {phase.kind === "ready" && !inbox && (
        <DocumentsFromContractors
          documents={documents} runs={runs} submittalsTotal={submittalsTotal}
          onReview={(documentId) => void reviewDocument(documentId)}
          startingDocumentId={startingDocumentId}
        />
      )}
      {phase.kind === "ready" && inbox && (
        <InboxList
          documents={documents} runs={runs} submittalsTotal={submittalsTotal}
          onReview={(documentId) => void reviewDocument(documentId)}
          onOpenRun={onOpenRun}
          onReviewAll={(targets) => void reviewAll(targets)}
          reviewingAll={batching}
          startingDocumentId={startingDocumentId}
          loadReadyCounts={loadReadyCounts}
        />
      )}
    </section>
  );
}
