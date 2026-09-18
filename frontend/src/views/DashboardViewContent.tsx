import { useCallback, useEffect, useRef, useState } from "react";
import { api, classification, management } from "../api/client";
import type { ClassificationCoverage } from "../api/client";
import type { Connection } from "../components/Shell";
import { DisconnectedState, ErrorState, Spinner } from "../components/states";
import { MetricWarningRow } from "../components/dashboard/MetricWarning";
import type { ApiError, Metrics, ManagementSummary } from "../types/api";
import { nf, Stat, Headline, ReadinessPanel, TypeCounts } from "./DashboardPrimitives";
import { DashboardTechnicalDetails } from "./DashboardTechnicalDetails";

export function DashboardView({
  connection,
  onRetryConnection,
}: {
  connection: Connection;
  onRetryConnection: () => void;
}) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<{ error: ApiError; disconnected: boolean } | null>(null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  // null covers BOTH "has not answered yet" and "the request failed" -
  // deliberately one state, not two, because both cases render the same way:
  // the Documents tile with no per-type counts, exactly as it looked before
  // classification coverage existed. There is no error state for this one
  // add-on; the rest of the dashboard does not depend on it.
  const [coverage, setCoverage] = useState<ClassificationCoverage | null>(null);
  const [delivery, setDelivery] = useState<ManagementSummary | null>(null);
  const first = useRef(true);

  const load = useCallback(async () => {
    const r = await api.metrics();
    if (r.ok) {
      setMetrics(r.data);
      setError(null);
      setFetchedAt(Date.now());
    } else {
      // The numbers are dropped, not kept. A stale figure presented as
      // current is the same class of lie as an unmeasured one.
      setMetrics(null);
      setError({ error: r.error, disconnected: r.disconnected });
    }
    first.current = false;
  }, []);

  const loadCoverage = useCallback(async () => {
    const r = await classification.coverage();
    // Success or failure, this is the whole handler: on failure fall back to
    // null rather than keeping a previous answer, for the same reason
    // `load` above drops metrics rather than leaving them looking live.
    setCoverage(r.ok ? r.data : null);
  }, []);

  const loadDelivery = useCallback(async () => {
    const r = await management.summary();
    setDelivery(r.ok ? r.data : null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (!cancelled) {
        void load();
        void loadCoverage();
        void loadDelivery();
      }
    };
    tick();
    const timer = window.setInterval(tick, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [load, loadCoverage, loadDelivery]);

  // The shell already knows the backend is gone, so say so at once rather
  // than waiting for this screen's own fetch to time out.
  if (connection.state === "offline" || error?.disconnected) {
    return <DisconnectedState onRetry={onRetryConnection} />;
  }
  if (error) {
    return <ErrorState error={error.error} onRetry={load} />;
  }

  if (!metrics) return <Spinner label="Reading metrics" />;

  const { corpus, system, models, worker, jobs, retrieval, throughput } = metrics;
  const noSearchable = corpus.by_status["no_searchable_content"] ?? 0;

  // Coverage is scoped exactly like every other count on this screen: shown
  // to a caller only when the register's own boundary claim matches the
  // dashboard's stated one. THIS SCREEN ALREADY SHIPPED THE OPPOSITE BUG ONCE
  // (see the boundary comment above, on `metrics.corpus_wide`) - a count that
  // is arithmetically fine but describes a different set of documents than
  // the sentence above it claims. Showing nothing is safer than showing
  // per-type counts under the wrong boundary.
  const coverageInScope = coverage != null && coverage.corpus_wide === metrics.corpus_wide;
  const byType = coverageInScope ? coverage!.by_type : [];

  return (
    <div className="aurora-field">
      <div aria-hidden className="aurora-a" />
      <div aria-hidden className="aurora-b" />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slateish-200">System</h1>
          <p className="text-xs text-slateish-500">
            Every value is measured. Anything unmeasured says so rather than
            showing a zero.
          </p>
          {/* THE BOUNDARY, STATED IN BOTH DIRECTIONS. This screen once
              reported 12 documents to a reader whose Documents screen
              correctly said "No documents yet", because /api/metrics resolved
              an access scope and discarded it. The count was arithmetically
              right and unreadable: a count with no stated boundary reads as
              total. An admin is now deliberately allowed corpus-wide figures,
              which is only defensible while the screen says so out loud. */}
          <p className="mt-1 text-xs text-slateish-400">
            {metrics.corpus_wide ? (
              <>
                <span className="font-semibold text-slateish-300">
                  Corpus-wide figures.
                </span>{" "}
                These counts cover every document in the corpus, including
                documents you cannot open. You are seeing them because you hold
                the admin capability.
              </>
            ) : (
              <>
                <span className="font-semibold text-slateish-300">
                  Your documents only.
                </span>{" "}
                These counts cover the documents you have been granted, not the
                whole corpus.
              </>
            )}
          </p>
        </div>
        <p className="font-mono text-xs text-slateish-500">
          refreshed {fetchedAt ? new Date(fetchedAt).toLocaleTimeString() : "—"} · every{" "}
          {metrics.refresh_seconds}s
        </p>
      </div>

      <ReadinessPanel metrics={metrics} />

      {delivery && (
        <section className="card-3d surface-card rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4" aria-label="EPC delivery overview">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-slateish-200">EPC delivery overview</h2>
              <p className="mt-1 text-xs text-slateish-500">Live WBS, review, and overdue-risk counts for your accessible project scope.</p>
            </div>
            <a href="#deliverables" className="text-xs font-medium text-signal-400 hover:underline">Open deliverables</a>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Deliverables" value={delivery.deliverables_total} hint="registered in WBS" />
            <Stat label="Review findings" value={delivery.review_findings_total} hint="AI or engineer findings" />
            <Stat label="Overdue" value={delivery.overdue_alerts} hint="requires follow-up" tone={delivery.overdue_alerts ? "warn" : "good"} />
            <Stat label="Approved" value={delivery.deliverables_by_status?.approved ?? 0} hint="current revisions" tone="good" />
          </div>
        </section>
      )}

      {/* THE ONE SENTENCE. Before the numbers, what they add up to - written
          only from values that were measured, so it never claims readiness
          the tiles below would contradict. */}
      <p className="mt-6 text-[1.35rem] leading-snug text-slateish-100">
        {corpus.documents === 0 ? (
          <>No documents yet. Upload a PDF to start asking questions.</>
        ) : metrics.warnings.length > 0 ? (
          <>
            Ready to answer questions about{" "}
            <span className="font-semibold">{nf.format(corpus.documents)} document{corpus.documents === 1 ? "" : "s"}</span>
            , with <span className="font-semibold text-warn-500">{metrics.warnings.length} thing{metrics.warnings.length === 1 ? "" : "s"} to look at</span>.
          </>
        ) : (
          <>
            Ready to answer questions about{" "}
            <span className="font-semibold">{nf.format(corpus.documents)} document{corpus.documents === 1 ? "" : "s"}</span>
            . Nothing needs attention.
          </>
        )}
      </p>

      {/* ---------------------------------------------- the four answers */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Headline
          label="Searchable"
          value={
            corpus.chunks_total > 0
              ? `${Math.round((100 * corpus.chunks_retrievable) / corpus.chunks_total)}`
              : null
          }
          unit="%"
          tone={
            corpus.chunks_total === 0
              ? "normal"
              : corpus.chunks_retrievable / corpus.chunks_total >= 0.9
                ? "good"
                : "warn"
          }
          note={
            corpus.chunks_total === 0
              ? "No documents loaded yet."
              : `${nf.format(corpus.chunks_retrievable)} of ${nf.format(
                  corpus.chunks_total,
                )} passages can be found by a question. The rest are contents pages, front matter and scans — each listed below with the reason it was left out.`
          }
        />
        <Headline
          label="Typical answer"
          value={retrieval?.p50 != null ? (retrieval.p50 / 1000).toFixed(1) : null}
          unit="s"
          tone={
            retrieval?.p50 == null ? "normal" : retrieval.p50 < 3000 ? "good" : "warn"
          }
          note={
            retrieval?.p50 == null
              ? "No question has been asked on this machine yet, so there is nothing to average."
              : `Half of answers arrive faster than this. The slowest one in twenty takes ${(
                  (retrieval.p95 ?? retrieval.p50) / 1000
                ).toFixed(1)}s. Taken from ${nf.format(
                  retrieval.samples,
                )} questions actually asked here, not a benchmark.`
          }
        />
        <Headline
          label="Documents"
          value={String(corpus.documents)}
          tone={corpus.documents > 0 ? "normal" : "warn"}
          note={
            corpus.documents === 0 ? (
              "Upload a PDF on the Documents screen to begin."
            ) : (
              <>
                {`${nf.format(corpus.pages_extracted)} pages read. ${
                  Object.entries(corpus.by_status)
                    .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)
                    .join(", ") || "no status recorded"
                }.`}
                {/* SCOPED to a caller who can see the register at all - see
                    `coverageInScope` above - and shown only when it is
                    actually non-zero, never as "0 awaiting a type", which
                    would claim a measurement nobody made for a caller with
                    no coverage answer at all. */}
                {coverageInScope && coverage!.needs_classification > 0 && (
                  <span className="ms-1 text-warn-500">
                    · {nf.format(coverage!.needs_classification)} awaiting a type
                  </span>
                )}
              </>
            )
          }
        >
          {corpus.documents > 0 && <TypeCounts byType={byType} />}
        </Headline>
        <Headline
          label="Needs attention"
          value={String(metrics.warnings.length)}
          tone={metrics.warnings.length === 0 ? "good" : "warn"}
          note={
            metrics.warnings.length === 0
              ? "Nothing is wrong that the system can detect."
              : "Listed immediately below, each with what it means and what to do about it."
          }
        />
      </div>

      {metrics.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {metrics.warnings.slice(0, 7).map((w) => (
            <MetricWarningRow key={`${w.code}-${w.document_id ?? "all"}-${w.message}`} warning={w} />
          ))}
          {metrics.warnings.length > 7 && <li className="text-sm text-slateish-400">{metrics.warnings.length - 7} more items are available in the relevant workspace screen.</li>}
        </ul>
      )}

      {/* EVERYTHING BELOW IS STILL HERE - folded, not removed. A client
          opening this screen was met by thirty near-identical tiles in which
          "keyword search ready 8,145" and "last heartbeat 0.7 s ago" carried
          the same weight as "is anything wrong". The four answers above and
          the warnings are what a reader came for; the rest is the operator's
          console, one click away, with every number intact. Nothing about
          the honesty rules changes: an unmeasured value still says so. */}
      <DashboardTechnicalDetails metrics={metrics} corpus={corpus} throughput={throughput} retrieval={retrieval} jobs={jobs} worker={worker} models={models} system={system} noSearchable={noSearchable} />
    </div>
  );
}
