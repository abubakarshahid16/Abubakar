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

import { api } from "../api/client";
import type { Connection } from "../components/Shell";
import { DisconnectedState, ErrorState, Spinner } from "../components/states";
import { humaniseReason } from "../components/WorkerPanel";
import type { ApiError, Metrics, MetricWarning, StageThroughput } from "../types/api";

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
      <span className="mr-2 font-mono text-[11px] uppercase tracking-wide opacity-80">
        {warning.code}
      </span>
      <span className="text-slateish-300">{warning.message}</span>
    </li>
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

  useEffect(() => {
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
  }, [load]);

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

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slateish-200">System</h1>
          <p className="text-xs text-slateish-500">
            Every value is measured. Anything unmeasured says so rather than
            showing a zero.
          </p>
        </div>
        <p className="font-mono text-[11px] text-slateish-500">
          refreshed {fetchedAt ? new Date(fetchedAt).toLocaleTimeString() : "—"} · every{" "}
          {metrics.refresh_seconds}s
        </p>
      </div>

      {metrics.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {metrics.warnings.map((w) => (
            <Warning key={`${w.code}-${w.document_id ?? "all"}-${w.message}`} warning={w} />
          ))}
        </ul>
      )}

      <Section
        title="Corpus"
        hint="Retrievable is what search can actually see. Excluded chunks are kept for inspection."
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
          <Stat label="Chunks (all rows)" value={corpus.chunks_total} />
          <Stat
            label="Retrievable"
            value={corpus.chunks_retrievable}
            tone={corpus.chunks_retrievable > 0 ? "good" : "danger"}
          />
          <Stat
            label="Excluded"
            value={corpus.chunks_excluded}
            hint="stored, not searchable — see Documents › Excluded"
            tone={corpus.chunks_excluded > 0 ? "warn" : "normal"}
          />
          <Stat label="In keyword index" value={corpus.chunks_indexed_keyword} />
          <Stat
            label="Embedded"
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
        hint="From questions actually asked on this machine, not a synthetic benchmark."
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
          <Stat label="Documents completed" value={worker.documents_completed} />
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

      <Section title="Machine" hint="This laptop is the production machine.">
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
              {system.cpu_percent_since_last_call == null
                ? "the first reading has no prior call to measure against"
                : `average over the last ${metrics.refresh_seconds}s`}
            </p>
          </div>

          <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-slateish-500">Memory</p>
            <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
              {bytes(system.ram_used_bytes)}{" "}
              <span className="text-sm text-slateish-500">
                / {bytes(system.ram_total_bytes)}
              </span>
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

      {metrics.exclusions.length > 0 && (
        <Section
          title="What search cannot see"
          hint="Nothing is dropped silently. Every exclusion is recorded with the rule that caused it."
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
  );
}
