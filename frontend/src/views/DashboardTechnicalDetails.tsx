import type { Metrics } from "../types/api";
import { bytes, nf, Stat, Section, Throughput, Bar, loadTone } from "./DashboardPrimitives";
import { humaniseReason } from "../components/WorkerPanel";

type Props = {
  metrics: Metrics;
  corpus: Metrics["corpus"];
  throughput: Metrics["throughput"];
  retrieval: Metrics["retrieval"];
  jobs: Metrics["jobs"];
  worker: Metrics["worker"];
  models: Metrics["models"];
  system: Metrics["system"];
  noSearchable: number;
};

export function DashboardTechnicalDetails({ metrics, corpus, throughput, retrieval, jobs, worker, models, system, noSearchable }: Props) {
  return (
      <details className="mt-8 group">
        <summary className="cursor-pointer select-none rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-4 py-3 text-sm text-slateish-300 hover:text-slateish-100 [&::-webkit-details-marker]:hidden">
          <span className="me-2 inline-block motion-safe:transition-transform group-open:rotate-90">&#9656;</span>
          <span className="font-medium">Technical detail</span>
          <span className="ms-2 text-xs text-slateish-500">
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
                  "rounded-[var(--radius-xs)] border px-2 py-0.5 font-mono text-xs",
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
                className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm"
              >
                <span className="text-slateish-200">{f.filename}</span>
                <span className="ms-2 font-mono text-xs text-danger-500">
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
                className="rounded-[var(--radius-sm)] border border-danger-500/50 bg-danger-500/10 px-3 py-1.5 text-sm text-slateish-300"
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
          <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-xs uppercase tracking-wide text-slateish-500">CPU</p>
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
            <p className="mt-1 text-xs text-slateish-500">
              {system.cpu_physical_cores ?? "?"} physical /{" "}
              {system.cpu_logical_cores ?? "?"} logical ·{" "}
              {system.cpu_percent_since_last_call != null
                ? `average over the last ${system.cpu_window_seconds ?? metrics.refresh_seconds}s`
                : system.cpu_window_seconds == null
                  ? "no prior call to measure against"
                  : `the last window was only ${system.cpu_window_seconds}s — too short to average`}
            </p>
          </div>

          <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-xs uppercase tracking-wide text-slateish-500">Memory</p>
            {/* Free, not used. The reader's question is "is there room for the
                answer model", and used/total made them subtract - which broke
                on rounding: 15.4 of 16 rendered as "15 / 16", implying 1 GB
                free while the alert correctly said 0.6 GB. */}
            <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
              {bytes(system.ram_free_bytes)}{" "}
              <span className="text-sm text-slateish-500">free of {bytes(system.ram_total_bytes)}</span>
            </p>
            <Bar percent={system.ram_percent} tone={loadTone(system.ram_percent)} />
            <p className="mt-1 text-xs text-slateish-500">
              this backend: {bytes(system.process_rss_bytes)} resident
            </p>
          </div>

          <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
            <p className="text-xs uppercase tracking-wide text-slateish-500">Disk</p>
            <p className="mt-1 font-mono text-lg leading-tight text-slateish-100">
              {bytes(system.disk_free_bytes)}{" "}
              <span className="text-sm text-slateish-500">free</span>
            </p>
            <Bar
              percent={system.disk_percent ?? 0}
              tone={loadTone(system.disk_percent ?? 0)}
            />
            <p className="mt-1 text-xs text-slateish-500">
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
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-700">
            <table className="w-full text-left text-sm">
              <thead className="bg-ink-850 text-xs uppercase tracking-wide text-slateish-500">
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
  );
}
