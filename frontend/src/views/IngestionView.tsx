/**
 * Ingestion: queue and throughput.
 *
 * This screen was a placeholder carrying a NOT BUILT badge. The data behind it
 * already existed - /api/health for the worker, /api/documents for per-document
 * position, /api/metrics for measured stage rates - so what was missing was the
 * screen, not the instrumentation.
 *
 * It exists to answer one question a reader asks while waiting: what is
 * happening right now, and is it moving. So it shows position rather than a
 * predicted percentage, and it shows the moment a document becomes ANSWERABLE
 * separately from the moment it is fully indexed. Those are minutes apart on a
 * long document - a 1,400-page book is searchable in about 13 seconds and
 * finishes embedding several minutes later - and a reader who is told only
 * "42%" waits for no reason.
 *
 * Every rate obeys the same rule as the dashboard: a stage that has not been
 * timed measurably says so rather than showing a zero.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Connection } from "../components/Shell";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { formatAge, presentStatus } from "../components/documentStatus";
import type { ApiError, DocStatus, DocumentRecord, Metrics } from "../types/api";

const nf = new Intl.NumberFormat();

/** The order a document moves through. Off-track states are handled apart. */
const PIPELINE: DocStatus[] = [
  "queued",
  "extracting",
  "chunking",
  "indexing_keyword",
  "partially_searchable",
  "ready",
];

const OFF_TRACK: DocStatus[] = ["failed", "no_searchable_content"];

function reached(doc: DocumentRecord, stage: DocStatus): boolean {
  if (OFF_TRACK.includes(doc.status)) return false;
  return PIPELINE.indexOf(doc.status) >= PIPELINE.indexOf(stage);
}

function Tile({
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

/** One step of the pipeline for one document. Reached, current, or not yet. */
function Step({
  label,
  done,
  current,
  detail,
}: {
  label: string;
  done: boolean;
  current: boolean;
  detail?: string;
}) {
  return (
    <li
      className={[
        "flex items-baseline gap-2 rounded border px-2 py-1.5 text-xs",
        current
          ? "border-signal-500/60 bg-signal-500/10 text-signal-300"
          : done
            ? "border-ink-600 bg-ink-800 text-slateish-300"
            : "border-ink-700 text-slateish-500",
      ].join(" ")}
    >
      <span aria-hidden className="font-mono">
        {done ? "done" : current ? "now" : "··"}
      </span>
      <span className="font-medium">{label}</span>
      {detail && <span className="ml-auto font-mono text-[11px]">{detail}</span>}
    </li>
  );
}

function DocumentProgress({ doc }: { doc: DocumentRecord }) {
  const status = presentStatus(doc);
  const answerable = reached(doc, "partially_searchable");

  if (OFF_TRACK.includes(doc.status)) {
    return (
      <div className="rounded-lg border border-warn-500/40 bg-warn-500/5 p-3">
        <p className="text-sm font-medium text-slateish-200">{doc.filename}</p>
        <p className="mt-1 text-xs text-warn-500">{status.label}</p>
        {doc.error && <p className="mt-1 text-xs text-slateish-300">{doc.error.message}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slateish-200">{doc.filename}</p>
        <p className="font-mono text-[11px] text-slateish-400">
          {doc.page_count != null ? `${nf.format(doc.page_count)} pages` : "reading the manifest"}
        </p>
      </div>

      <ol className="mt-2 space-y-1">
        <Step
          label="Text read from the pages"
          done={reached(doc, "chunking")}
          current={doc.status === "extracting"}
          detail={
            doc.page_count != null
              ? `${nf.format(doc.pages_done)} / ${nf.format(doc.page_count)}`
              : undefined
          }
        />
        <Step
          label="Split into passages"
          done={reached(doc, "indexing_keyword")}
          current={doc.status === "chunking"}
          detail={doc.chunk_count_total > 0 ? nf.format(doc.chunk_count_total) : undefined}
        />
        <Step
          label="Searchable by keyword — questions can be asked now"
          done={answerable}
          current={doc.status === "indexing_keyword"}
        />
        <Step
          label="Fully indexed — wording no longer has to match the document"
          done={doc.status === "ready"}
          current={doc.status === "partially_searchable"}
          detail={
            doc.chunk_count > 0
              ? `${nf.format(doc.embedded_count)} / ${nf.format(doc.chunk_count)}`
              : undefined
          }
        />
      </ol>

      {answerable && doc.status !== "ready" && (
        <p className="mt-2 text-xs text-signal-400">
          You can ask questions about this document now. Answers will improve as the
          remaining passages finish.
        </p>
      )}
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  extract: "Reading pages",
  chunk: "Splitting into passages",
  keyword_index: "Building the keyword index",
  embed: "Embedding passages",
  retrieval: "Answering questions",
};

export function IngestionView({
  connection,
  onRetryConnection,
}: {
  connection: Connection;
  onRetryConnection: () => void;
}) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    const [m, d] = await Promise.all([api.metrics(), api.documents()]);
    if (m.ok && d.ok) {
      setMetrics(m.data);
      setDocuments(d.data);
      setError(null);
    } else {
      // Dropped rather than kept. A stale queue shown as current is the same
      // class of untruth as an unmeasured number displayed as zero.
      setMetrics(null);
      setDocuments(null);
      setError(m.ok ? (d.ok ? null : d.error) : m.error);
    }
  }, []);

  useEffect(() => {
    if (connection.state !== "online") return;
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void load();
    };
    tick();
    const timer = window.setInterval(tick, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [connection.state, load]);

  const worker = connection.state === "online" ? connection.health.ingestion : null;

  if (error) return <ErrorState error={error} onRetry={onRetryConnection} />;
  // Array.isArray, not a truthiness check. A malformed payload used to crash
  // this whole screen on `documents.filter`, which is the one thing a status
  // screen must never do - it is what you look at when things are wrong.
  if (!metrics || !worker || !Array.isArray(documents)) {
    return <Spinner label="Reading the queue" />;
  }

  const inProgress = documents.filter(
    (d) => !OFF_TRACK.includes(d.status) && d.status !== "ready",
  );
  const finished = documents.filter((d) => d.status === "ready");
  const trouble = documents.filter((d) => OFF_TRACK.includes(d.status));
  const currentName =
    documents.find((d) => d.id === worker.current_document)?.filename ??
    worker.current_document;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slateish-200">Ingestion</h1>
          <p className="mt-0.5 text-sm text-slateish-400">
            What the system is doing to your documents, and how fast it is doing it.
          </p>
        </div>
        <p className="font-mono text-[11px] text-slateish-500">
          every {metrics.refresh_seconds}s
        </p>
      </div>

      <Section title="Right now">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Tile
            label="Worker"
            value={
              worker.current_document != null
                ? "working"
                : worker.stalled
                  ? "not moving"
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
            hint={currentName ?? "nothing in progress"}
          />
          <Tile label="Waiting" value={worker.pending_count} hint="documents in the queue" />
          <Tile
            label="Oldest wait"
            value={formatAge(worker.oldest_pending_age_seconds)}
            hint="how long the front of the queue has waited"
          />
          <Tile
            label="Finished"
            value={worker.documents_completed}
            hint="since the worker started"
          />
        </div>
      </Section>

      {inProgress.length > 0 && (
        <Section
          title="In progress"
          hint="A document becomes answerable before it is fully indexed. Both moments are shown."
        >
          <div className="space-y-2">
            {inProgress.map((d) => (
              <DocumentProgress key={d.id} doc={d} />
            ))}
          </div>
        </Section>
      )}

      {inProgress.length === 0 && trouble.length === 0 && (
        <Section title="In progress">
          <EmptyState
            title="Nothing is being processed"
            hint="Upload a document on the Documents screen and this is where you will watch it arrive — page by page, then passage by passage, with the moment it becomes searchable called out separately from the moment it finishes."
          />
        </Section>
      )}

      {trouble.length > 0 && (
        <Section title="Needs attention" hint="Finished, but not searchable.">
          <div className="space-y-2">
            {trouble.map((d) => (
              <DocumentProgress key={d.id} doc={d} />
            ))}
          </div>
        </Section>
      )}

      <Section
        title="Throughput"
        hint="Median of timed runs on this machine. A stage never timed long enough to measure reports nothing rather than zero."
      >
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {Object.entries(metrics.throughput).map(([stage, t]) => (
            <Tile
              key={stage}
              label={STAGE_LABELS[stage] ?? stage.replace(/_/g, " ")}
              value={t ? `${t.median} ${t.unit}` : null}
              hint={
                t
                  ? `median of ${t.samples} run${t.samples === 1 ? "" : "s"} · best ${t.best}`
                  : "no run has been timed long enough to measure"
              }
            />
          ))}
        </div>
      </Section>

      {finished.length > 0 && (
        <Section title="Fully indexed" hint={`${finished.length} document${finished.length === 1 ? "" : "s"}.`}>
          <ul className="space-y-1">
            {finished.map((d) => (
              <li
                key={d.id}
                className="flex flex-wrap items-baseline gap-2 rounded border border-ink-700 bg-ink-850 px-3 py-2 text-xs"
              >
                <span className="font-medium text-slateish-200">{d.filename}</span>
                <span className="font-mono text-[11px] text-slateish-400">
                  {d.page_count != null ? `${nf.format(d.page_count)} pages` : ""}
                  {" · "}
                  {nf.format(d.chunk_count)} searchable passages
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
