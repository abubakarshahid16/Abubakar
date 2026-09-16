/**
 * Dashboard.
 *
 * One rule governs every value on this screen: it is measured, or it says it
 * is not. There is no zero standing in for unknown, no last-known figure
 * presented as current, and when the backend goes away the numbers are
 * replaced rather than left sitting there looking live.
 *
 * That rule is not decoration. This build has already shipped a rate of
 * 1,021,658,887 pages/sec from a divide-by-almost-zero, a worker reporting
 * healthy with a full queue, and a "ready" document search could not see. A
 * number on a dashboard is read as a fact, so an unmeasured one is the most
 * expensive thing that can be put here.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api, classification, management } from "../api/client";
import type { ClassificationCoverage } from "../api/client";
import type { Connection } from "../components/Shell";
import { DisconnectedState, ErrorState, Spinner } from "../components/states";
import { humaniseReason } from "../components/WorkerPanel";
import type { ApiError, Metrics, MetricWarning, StageThroughput, ManagementSummary } from "../types/api";

const STAGE_LABELS: Record<string, string> = {
  extract: "Extraction",
  chunk: "Chunking",
  keyword_index: "Keyword index",
  embed: "Embedding",
};

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

const nf = new Intl.NumberFormat();

/** A measured value, or an explicit statement that it has not been measured. */
function Stat({
  label,
  value,
  hint,
  tone = "normal",
}: {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  tone?: "normal" | "warn" | "danger" | "good";
}) {
  const measured = value !== null && value !== undefined;
  const toneClass =
    tone === "warn"
      ? "text-warn-500"
      : tone === "danger"
        ? "text-danger-500"
        : tone === "good"
          ? "text-signal-400"
          : "text-slateish-100";
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-slateish-500">{label}</p>
      {measured ? (
        <p className={`mt-1 font-mono text-lg leading-tight ${toneClass}`}>
          {typeof value === "number" ? nf.format(value) : value}
        </p>
      ) : (
        <p className="mt-1 text-sm italic leading-tight text-slateish-500">
          not measured yet
        </p>
      )}
      {hint && <p className="mt-1 text-[11px] text-slateish-500">{hint}</p>}
    </div>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-6">
      <h2 className="text-sm font-semibold text-slateish-200">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-slateish-500">{hint}</p>}
      <div className="mt-2">{children}</div>
    </section>
  );
}

/**
 * The four answers, above the measurements.
 *
 * The screen below is complete and was unreadable: twenty tiles of equal
 * weight, in words - chunks, retrievable, reranker, e5-small - that only
 * somebody who built it knows. A reader arrives with four questions, so those
 * are answered first, in their words, and the detail stays underneath for when
 * a number needs checking.
 */
function Headline({
  label,
  value,
  unit,
  note,
  tone = "normal",
  children,
}: {
  label: string;
  value: string | null;
  unit?: string;
  note: React.ReactNode;
  tone?: "normal" | "warn" | "danger" | "good";
  /** Rendered between the big value and `note`. Used sparingly - today only
   *  by the Documents tile, for the per-type counts - because a headline
   *  tile earns its size by answering one question at a glance, and every
   *  extra line spends a little of that. */
  children?: React.ReactNode;
}) {
  const toneClass =
    tone === "warn"
      ? "text-warn-500"
      : tone === "danger"
        ? "text-danger-500"
        : tone === "good"
          ? "text-signal-400"
          : "text-slateish-100";
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-800 px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slateish-400">{label}</p>
      {value == null ? (
        <p className="mt-2 text-lg italic leading-tight text-slateish-500">
          nothing measured yet
        </p>
      ) : (
        <p className={`mt-2 font-mono text-[2.6rem] leading-none ${toneClass}`}>
          {value}
          {unit && <span className="ml-1.5 text-lg text-slateish-500">{unit}</span>}
        </p>
      )}
      {children}
      <p className="mt-3 text-sm leading-relaxed text-slateish-300">{note}</p>
    </div>
  );
}

function Bar({ percent, tone }: { percent: number; tone: "normal" | "warn" | "danger" }) {
  const colour =
    tone === "danger" ? "bg-danger-500" : tone === "warn" ? "bg-warn-500" : "bg-signal-500";
  return (
    <div
      className="mt-1.5 h-1.5 overflow-hidden rounded bg-ink-700"
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full ${colour}`} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

function loadTone(percent: number): "normal" | "warn" | "danger" {
  if (percent >= 90) return "danger";
  if (percent >= 75) return "warn";
  return "normal";
}

function Warning({ warning }: { warning: MetricWarning }) {
  const style =
    warning.severity === "error"
      ? "border-danger-500/50 bg-danger-500/10 text-danger-500"
      : warning.severity === "warning"
        ? "border-warn-500/50 bg-warn-500/10 text-warn-500"
        : "border-ink-600 bg-ink-850 text-slateish-400";
  return (
    <li
      className={`rounded border px-3 py-2 text-sm ${style}`}
      role={warning.severity === "error" ? "alert" : "status"}
    >
      {/* The message leads. This row used to open with the raw code -
          NEEDS_OCR, EQUATION_PAGES - which is a database enum, not a sentence.
          The code stays at the end for a bug report. */}
      <span className="text-slateish-300">{warning.message}</span>
      <span className="ml-2 font-mono text-[10px] uppercase tracking-wide opacity-50">
        {warning.code}
      </span>
    </li>
  );
}

function ReadinessPanel({ metrics }: { metrics: Metrics }) {
  const documentsReady = metrics.corpus.documents > 0 && metrics.corpus.chunks_retrievable > 0;
  const localModelsReady =
    metrics.models.embed_model_present &&
    metrics.models.reranker_present &&
    metrics.models.answer_model_reachable;
  const workerReady = metrics.worker.alive && !(metrics.worker.stalled && metrics.worker.current_document == null);
  const gates = [
    {
      label: "Your documents",
      ok: documentsReady,
      detail: documentsReady
        ? `${nf.format(metrics.corpus.documents)} document${metrics.corpus.documents === 1 ? "" : "s"} loaded, ${nf.format(metrics.corpus.chunks_retrievable)} passages a question can reach`
        : "upload at least one PDF with readable text",
    },
    {
      label: "Answering",
      ok: localModelsReady,
      detail: localModelsReady
        ? "search and the answer model are running on this computer"
        : "a model is missing or not running - answers will be limited",
    },
    {
      label: "Uploads",
      ok: workerReady,
      detail: workerReady ? "new documents will be processed as they arrive" : "processing has stopped - new uploads will wait",
    },
    {
      label: "Market data",
      ok: true,
      detail: "illustrative sample only - no live market source is connected",
      tone: "warn" as const,
    },
    {
      label: "PDF reports",
      ok: false,
      // "not yet available" is a banned phrase here - it was true of OCR once,
      // and of the summary once, and each time it stayed on screen after the
      // thing arrived. Say what exists, not what does not.
      detail: "one PDF per answer, with its evidence frozen in - reports cover single answers, not a whole analysis",
      tone: "warn" as const,
    },
  ];

  return (
    <section className="mt-4 rounded-lg border border-ink-700 bg-ink-850 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slateish-200">What this system can do right now</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slateish-400">
            Green is measured and working on this computer. Amber is a limit you should know
            about before relying on it.
          </p>
        </div>
        <span className="rounded border border-warn-500/40 bg-warn-500/10 px-2 py-1 font-mono text-[11px] text-warn-500">
          Prototype
        </span>
      </div>
      <ul className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {gates.map((g) => {
          const tone = g.tone ?? (g.ok ? "good" : "danger");
          const klass =
            tone === "good"
              ? "border-signal-500/35 bg-signal-500/10 text-signal-400"
              : tone === "warn"
                ? "border-warn-500/35 bg-warn-500/10 text-warn-500"
                : "border-danger-500/35 bg-danger-500/10 text-danger-500";
          return (
            <li key={g.label} className={`rounded border px-3 py-2 ${klass}`}>
              <p className="text-xs font-semibold">{g.label}</p>
              <p className="mt-1 text-xs leading-relaxed text-slateish-300">{g.detail}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * The per-type upload counts inside the Documents headline tile.
 *
 * Renders WHATEVER `by_type` returns, in the order the register gave it -
 * never a hardcoded list of type names. A register with two types, or five,
 * or none loaded at all, must not make this component invent or drop a row.
 */
function TypeCounts({ byType }: { byType: ClassificationCoverage["by_type"] }) {
  if (byType.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
      {byType.map((t) => (
        <span key={t.type} className="font-mono text-xs leading-tight">
          <span className="text-slateish-500">{t.type}</span>{" "}
          <span className="text-slateish-200">{nf.format(t.uploaded)}</span>
        </span>
      ))}
    </div>
  );
}

function Throughput({ stage, data }: { stage: string; data: StageThroughput | null }) {
  const label = STAGE_LABELS[stage] ?? stage;
  if (!data) {
    return (
      <Stat
        label={label}
        value={null}
        hint="no run has been timed long enough to measure"
      />
    );
  }
  return (
    <Stat
      label={label}
      value={`${nf.format(data.median)} ${data.unit}`}
      hint={`median of ${data.samples} run${data.samples === 1 ? "" : "s"} · best ${nf.format(data.best)}`}
    />
  );
}

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
    <div>
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
        <p className="font-mono text-[11px] text-slateish-500">
          refreshed {fetchedAt ? new Date(fetchedAt).toLocaleTimeString() : "—"} · every{" "}
          {metrics.refresh_seconds}s
        </p>
      </div>

      <ReadinessPanel metrics={metrics} />

      {delivery && (
        <section className="mt-5 rounded-lg border border-ink-700 bg-ink-850 p-4" aria-label="EPC delivery overview">
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
            <Stat label="Approved" value={delivery.deliverables_by_status.approved ?? 0} hint="current revisions" tone="good" />
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
                  <span className="ml-1 text-warn-500">
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
          {metrics.warnings.map((w) => (
            <Warning key={`${w.code}-${w.document_id ?? "all"}-${w.message}`} warning={w} />
          ))}
        </ul>
      )}

      {/* EVERYTHING BELOW IS STILL HERE - folded, not removed. A client
          opening this screen was met by thirty near-identical tiles in which
          "keyword search ready 8,145" and "last heartbeat 0.7 s ago" carried
          the same weight as "is anything wrong". The four answers above and
          the warnings are what a reader came for; the rest is the operator's
          console, one click away, with every number intact. Nothing about
          the honesty rules changes: an unmeasured value still says so. */}
      <details className="mt-8 group">
        <summary className="cursor-pointer select-none rounded-lg border border-ink-700 bg-ink-850 px-4 py-3 text-sm text-slateish-300 hover:text-slateish-100 [&::-webkit-details-marker]:hidden">
          <span className="mr-2 inline-block transition-transform group-open:rotate-90">&#9656;</span>
          <span className="font-medium">Technical detail</span>
          <span className="ml-2 text-xs text-slateish-500">
            corpus counts, processing speed, retrieval latency, jobs, worker, models, machine, exclusion rules
          </span>
        </summary>
        <div className="mt-4 space-y-2">
      <Section
        title="Corpus"
        hint="A passage is a block of text a question can match. Searchable is what a question can actually reach; the rest are kept so you can inspect them."
      >
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          <Stat label="Documents" value={corpus.documents} />
          <Stat
            label="Pages extracted"
            value={corpus.pages_extracted}
            hint={
              corpus.pages_declared === corpus.pages_extracted
                ? "all declared pages extracted"
                : `${nf.format(corpus.pages_declared)} declared by the PDFs`
            }
            tone={corpus.pages_extracted < corpus.pages_declared ? "warn" : "normal"}
          />
          <Stat label="Passages stored" value={corpus.chunks_total} />
          <Stat
            label="Searchable"
            value={corpus.chunks_retrievable}
            tone={corpus.chunks_retrievable > 0 ? "good" : "danger"}
          />
          <Stat
            label="Excluded"
            value={corpus.chunks_excluded}
            hint="stored, not searchable — see Documents › Excluded"
            tone={corpus.chunks_excluded > 0 ? "warn" : "normal"}
          />
          <Stat label="Keyword search ready" value={corpus.chunks_indexed_keyword} />
          <Stat
            label="Meaning search ready"
            value={corpus.chunks_embedded}
            hint={
              corpus.chunks_retrievable > 0
                ? `${Math.round((100 * corpus.chunks_embedded) / corpus.chunks_retrievable)}% of retrievable`
                : undefined
            }
          />
          <Stat
            label="No searchable content"
            value={noSearchable}
            tone={noSearchable > 0 ? "warn" : "normal"}
            hint={
              noSearchable > 0
                ? "finished, but search can see none of it"
                : "no document finished empty"
            }
          />
        </div>

        {Object.keys(corpus.by_status).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(corpus.by_status).map(([status, n]) => (
              <span
                key={status}
                className={[
                  "rounded border px-2 py-0.5 font-mono text-[11px]",
                  status === "no_searchable_content"
                    ? "border-warn-500/50 bg-warn-500/10 text-warn-500"
                    : status === "failed"
                      ? "border-danger-500/50 bg-danger-500/10 text-danger-500"
                      : "border-ink-600 text-slateish-400",
                ].join(" ")}
              >
                {status} {n}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section
        title="Processing speed"
        hint="Median of timed runs on this machine. A stage never timed long enough to measure reports nothing rather than zero."
      >
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {["extract", "chunk", "keyword_index", "embed"].map((stage) => (
            <Throughput key={stage} stage={stage} data={throughput[stage] ?? null} />
          ))}
        </div>
      </Section>

      <Section
        title="Retrieval latency"
        hint="From questions actually asked on this machine, not a synthetic benchmark. The quoted answer needs no model; the Explain button does."
      >
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Stat
            label="Median"
            value={retrieval?.p50 != null ? `${nf.format(retrieval.p50)} ms` : null}
            hint={retrieval ? `${retrieval.samples} question(s) measured` : undefined}
          />
          <Stat
            label="95th percentile"
            value={retrieval?.p95 != null ? `${nf.format(retrieval.p95)} ms` : null}
          />
          <Stat
            label="Worst"
            value={retrieval ? `${nf.format(retrieval.worst)} ms` : null}
          />
          <Stat label="Questions measured" value={retrieval ? retrieval.samples : null} />
        </div>
      </Section>

      <Section title="Jobs">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Stat label="Running" value={jobs.running} />
          <Stat label="Queued documents" value={worker.pending_count} />
          <Stat
            label="Failed documents"
            value={jobs.failed_documents}
            tone={jobs.failed_documents > 0 ? "danger" : "normal"}
          />
          <Stat
            label="Oldest pending"
            value={
              worker.oldest_pending_age_seconds != null
                ? `${Math.round(worker.oldest_pending_age_seconds)} s`
                : "nothing pending"
            }
          />
        </div>
        {jobs.failures.length > 0 && (
          <ul className="mt-2 space-y-1">
            {jobs.failures.map((f) => (
              <li
                key={f.id}
                className="rounded border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm"
              >
                <span className="text-slateish-200">{f.filename}</span>
                <span className="ml-2 font-mono text-[11px] text-danger-500">
                  {f.error_code ?? "failed"}
                </span>
                {f.error_message && (
                  <p className="mt-0.5 text-xs text-slateish-400">{f.error_message}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Worker">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Stat
            label="State"
            value={
              worker.stalled && worker.current_document == null
                ? "not moving"
                : worker.current_document != null
                  ? "working"
                  : worker.alive
                    ? "idle"
                    : "stopped"
            }
            tone={
              worker.stalled && worker.current_document == null
                ? "danger"
                : worker.alive
                  ? "good"
                  : "warn"
            }
          />
          <Stat
            label="Last heartbeat"
            value={`${worker.seconds_since_heartbeat.toFixed(1)} s ago`}
          />
          {/* Since the WORKER STARTED, not out of the corpus. This tile sat
              on the same page as "DOCUMENTS 8" and read as 4 of 8. */}
          <Stat
            label="Documents completed since the worker started"
            value={worker.documents_completed}
          />
          <Stat
            label="Current document"
            value={worker.current_document ?? "nothing in progress"}
          />
        </div>
        {worker.stalled_reasons.length > 0 && (
          <ul className="mt-2 space-y-1">
            {worker.stalled_reasons.map((reason) => (
              <li
                key={reason}
                role="alert"
                className="rounded border border-danger-500/50 bg-danger-500/10 px-3 py-1.5 text-sm text-slateish-300"
              >
                {humaniseReason(reason)}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Models" hint="Configured and running are different states.">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Stat
            label="Embedding"
            value={models.embed_model}
            tone={models.embed_model_present ? "good" : "danger"}
            hint={models.embed_model_present ? "present on disk" : "NOT on disk"}
          />
          <Stat
            label="Reranker"
            value={models.reranker_model}
            tone={models.reranker_present ? "good" : "danger"}
            hint={models.reranker_present ? "present on disk" : "NOT on disk"}
          />
          <Stat
            label="Answer model"
            value={models.answer_model}
            tone={models.answer_model_reachable ? "good" : "warn"}
            hint={
              models.answer_model_reachable
                ? models.answer_model_loaded
                  ? "loaded — no cold start"
                  : "installed, not resident — first Explain pays the load"
                : `Ollama unreachable${models.ollama_error ? ` (${models.ollama_error})` : ""} — Tier 1 still works`
            }
          />
          <Stat
            label="Explain available"
            value={models.answer_model_reachable ? "yes" : "no"}
            tone={models.answer_model_reachable ? "good" : "warn"}
            hint="Tier 2 only; quoted answers never need it"
          />
        </div>
      </Section>

      {/* ABSENT for any reader without the admin capability (#77): the
          machine's core count, RAM and disk are not anybody's document, so no
          grant could scope them, and they were being served to every caller
          of a product whose stated boundary is "nothing leaves this machine".
          The whole card goes rather than its values, because `bytes(undefined)`
          and `percent ?? 0` would render "0 B free of 0 B" and a zeroed bar -
          a stated measurement that is false, which is a worse defect than the
          leak. An engineer sees no Machine card; the warnings below still
          reach them, figure-free. */}
      {system && (
      <Section title="Machine" hint="Everything runs here. No document or question leaves this computer.">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-slateish-500">CPU</p>
            {system.cpu_percent_since_last_call == null ? (
              <p className="mt-1 text-sm italic leading-tight text-slateish-500">
                not measured yet
              </p>
            ) : (
              <>
                <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
                  {system.cpu_percent_since_last_call.toFixed(0)}%
                </p>
                <Bar
                  percent={system.cpu_percent_since_last_call}
                  tone={loadTone(system.cpu_percent_since_last_call)}
                />
              </>
            )}
            <p className="mt-1 text-[11px] text-slateish-500">
              {system.cpu_physical_cores ?? "?"} physical /{" "}
              {system.cpu_logical_cores ?? "?"} logical ·{" "}
              {system.cpu_percent_since_last_call != null
                ? `average over the last ${system.cpu_window_seconds ?? metrics.refresh_seconds}s`
                : system.cpu_window_seconds == null
                  ? "no prior call to measure against"
                  : `the last window was only ${system.cpu_window_seconds}s — too short to average`}
            </p>
          </div>

          <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-slateish-500">Memory</p>
            {/* Free, not used. The reader's question is "is there room for the
                answer model", and used/total made them subtract - which broke
                on rounding: 15.4 of 16 rendered as "15 / 16", implying 1 GB
                free while the alert correctly said 0.6 GB. */}
            <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
              {bytes(system.ram_free_bytes)}{" "}
              <span className="text-sm text-slateish-500">free of {bytes(system.ram_total_bytes)}</span>
            </p>
            <Bar percent={system.ram_percent} tone={loadTone(system.ram_percent)} />
            <p className="mt-1 text-[11px] text-slateish-500">
              this backend: {bytes(system.process_rss_bytes)} resident
            </p>
          </div>

          <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-slateish-500">Disk</p>
            <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
              {bytes(system.disk_free_bytes)}{" "}
              <span className="text-sm text-slateish-500">free</span>
            </p>
            <Bar
              percent={system.disk_percent ?? 0}
              tone={loadTone(system.disk_percent ?? 0)}
            />
            <p className="mt-1 text-[11px] text-slateish-500">
              documents and index: {bytes(system.data_dir_bytes)}
            </p>
          </div>
        </div>
      </Section>
      )}

      {metrics.exclusions.length > 0 && (
        <Section
          title="Why search cannot see it"
          hint="One row per RULE, not per passage — a single page rule can cover several passages, so these counts are smaller than the Excluded total above. Nothing is dropped silently; every exclusion is recorded with the rule that caused it."
        >
          <div className="overflow-x-auto rounded-lg border border-ink-700">
            <table className="w-full text-left text-sm">
              <thead className="bg-ink-850 text-[11px] uppercase tracking-wide text-slateish-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Scope</th>
                  <th className="px-3 py-2 font-medium">Rule</th>
                  <th className="px-3 py-2 text-right font-medium">Count</th>
                  <th className="px-3 py-2 text-right font-medium">Characters</th>
                </tr>
              </thead>
              <tbody>
                {metrics.exclusions.map((e) => (
                  <tr key={`${e.scope}-${e.rule}`} className="border-t border-ink-700">
                    <td className="px-3 py-1.5 text-slateish-400">{e.scope}</td>
                    <td className="px-3 py-1.5 font-mono text-xs text-slateish-300">
                      {e.rule}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slateish-200">
                      {nf.format(e.count)}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slateish-400">
                      {nf.format(e.characters_dropped)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
        </div>
      </details>
    </div>
  );
}
