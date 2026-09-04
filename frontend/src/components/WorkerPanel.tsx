/**
 * Worker status.
 *
 * A worker that is alive and ignoring a full queue previously reported as
 * perfectly healthy, so this panel deliberately shows the backlog and the
 * progress clock alongside "alive" - never "alive" on its own.
 */
import type { Connection } from "./Shell";
import { formatAge } from "./documentStatus";

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slateish-400">{label}</dt>
      <dd className={`mt-0.5 font-mono text-sm ${tone ?? "text-slateish-200"}`}>{value}</dd>
    </div>
  );
}

export function WorkerPanel({ connection }: { connection: Connection }) {
  if (connection.state !== "online") {
    return (
      <section
        aria-labelledby="worker-heading"
        className="rounded-lg border border-ink-700 bg-ink-850 p-4"
      >
        <h2 id="worker-heading" className="text-sm font-medium text-slateish-200">
          Ingestion worker
        </h2>
        <p className="mt-2 text-sm text-warn-500">
          Unknown — the backend is not reachable.
        </p>
      </section>
    );
  }

  const w = connection.health.ingestion;
  const stalled = w.stalled;

  return (
    <section
      aria-labelledby="worker-heading"
      className={[
        "rounded-lg border p-4",
        stalled ? "border-danger-500/60 bg-danger-500/10" : "border-ink-700 bg-ink-850",
      ].join(" ")}
    >
      <div className="flex items-center justify-between">
        <h2 id="worker-heading" className="text-sm font-medium text-slateish-200">
          Ingestion worker
        </h2>
        <span
          role="status"
          className={[
            "rounded px-2 py-0.5 text-[11px] font-medium",
            stalled
              ? "bg-danger-500/20 text-danger-500"
              : w.alive
                ? "bg-signal-500/15 text-signal-400"
                : "bg-ink-700 text-slateish-400",
          ].join(" ")}
        >
          {stalled ? "STALLED" : w.alive ? "running" : "not running"}
        </span>
      </div>

      {stalled && (
        <div role="alert" className="mt-3 text-sm text-danger-500">
          <p className="font-medium">The worker is not making progress.</p>
          <ul className="mt-1 list-inside list-disc font-mono text-xs">
            {w.stalled_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="pending"
          value={String(w.pending_count)}
          tone={w.pending_count > 0 ? "text-warn-500" : undefined}
        />
        <Stat label="oldest waiting" value={formatAge(w.oldest_pending_age_seconds)} />
        <Stat label="since progress" value={formatAge(w.seconds_since_progress)} />
        <Stat label="completed" value={String(w.documents_completed)} />
      </dl>

      <p className="mt-3 text-xs text-slateish-400">
        {w.current_document ? (
          <>
            Processing <span className="font-mono">{w.current_document}</span>
          </>
        ) : (
          "Idle — no document is being processed."
        )}
      </p>

      {w.last_error && (
        <p className="mt-2 rounded bg-ink-900 p-2 font-mono text-[11px] text-danger-500">
          last error: {w.last_error.code} — {w.last_error.message}
          {w.last_error.document_id ? ` (${w.last_error.document_id})` : ""}
        </p>
      )}
    </section>
  );
}
