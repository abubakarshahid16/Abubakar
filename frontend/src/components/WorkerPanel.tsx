/**
 * Worker status.
 *
 * A worker that is alive and ignoring a full queue previously reported as
 * perfectly healthy, so this panel deliberately shows the backlog and the
 * progress clock alongside "alive" - never "alive" on its own.
 *
 * It also used to do the opposite, which is worse. While a 1,400-page book was
 * embedding normally - the document card directly below reading "1,536/2,113
 * embedded" - this panel showed a red STALLED and the raw reason code
 * "1_pending_but_no_progress_for_283s" over a database key. The loudest element
 * on the screen contradicted the truth immediately beneath it, during the
 * longest legitimate operation the product has.
 *
 * So the alarm now distinguishes two different situations that the single
 * `stalled` flag conflates:
 *
 *   nothing is being worked on and the queue is not moving  -> alarm
 *   a document IS being worked on, slowly                   -> caution, named
 *
 * The second is not silenced, because a genuinely wedged document must still
 * surface. It is stated in a sentence, with the file's name, so the reader can
 * check it against the card below instead of being told two contradictory
 * things at once.
 */
import type { DocumentRecord, WorkerStatus } from "../types/api";

import type { Connection } from "./Shell";
import { formatAge } from "./documentStatus";

/** Beyond this, a document being actively worked on is worth a caution. */
const SLOW_DOCUMENT_SECONDS = 600;

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slateish-400">{label}</dt>
      <dd className={`mt-0.5 font-mono text-sm ${tone ?? "text-slateish-200"}`}>{value}</dd>
    </div>
  );
}

/**
 * Reason codes are written for a log, not a reader. "1_pending_but_no_progress
 * _for_283s" is a sentence with the spaces taken out; put them back rather than
 * printing an identifier at someone.
 */
export function humaniseReason(code: string): string {
  const backlog = /^(\d+)_pending_but_no_progress_for_(\d+)s$/.exec(code);
  if (backlog) {
    const n = Number(backlog[1]);
    const secs = Number(backlog[2]);
    const docs = n === 1 ? "1 document is" : `${n} documents are`;
    return `${docs} waiting, and nothing has moved for ${formatAge(secs)}.`;
  }
  // The backend emits two shapes on this field: identifiers like the one
  // above, and prose like "work pending with no progress for 300s". Prose is
  // already addressed to a reader, so it passes through untouched - rewriting
  // it was how this function broke a test that had every right to pass.
  const prose = !code.includes("_");
  const text = prose ? code.trim() : code.replace(/_/g, " ").trim();
  const cased = prose ? text : text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(cased) ? cased : `${cased}.`;
}

export function WorkerPanel({
  connection,
  documents = [],
  /** The full worker status, from the SCOPED /api/metrics. Optional: without
   *  it this panel still reports whether the worker is alive, busy or stalled
   *  from /api/health, and simply does not name the document being processed.
   *
   *  It used to take that name from health.current_document, and health is
   *  unauthenticated - so the id of a document being processed was readable
   *  with no login, and this component joined it against the document list to
   *  render a filename. Naming the document is a legitimate thing to show an
   *  authorised reader; it just cannot come from the open route. */
  worker,
}: {
  connection: Connection;
  documents?: DocumentRecord[];
  worker?: WorkerStatus | null;
}) {
  // "Checking" is not "broken". Reporting a connection failure before the
  // first poll has returned made the app's opening statement a false alarm.
  if (connection.state === "connecting") {
    return (
      <section
        aria-labelledby="worker-heading"
        className="rounded-lg border border-ink-700 bg-ink-850 p-4"
      >
        <h2 id="worker-heading" className="text-sm font-medium text-slateish-200">
          Ingestion worker
        </h2>
        <p className="mt-2 text-sm text-slateish-400">Checking&hellip;</p>
      </section>
    );
  }

  if (connection.state === "offline") {
    return (
      <section
        aria-labelledby="worker-heading"
        className="rounded-lg border border-ink-700 bg-ink-850 p-4"
      >
        <h2 id="worker-heading" className="text-sm font-medium text-slateish-200">
          Ingestion worker
        </h2>
        <p className="mt-2 text-sm text-warn-500">
          Unknown &mdash; the backend is not reachable.
        </p>
      </section>
    );
  }

  const w = connection.health.ingestion;
  const currentId = worker?.current_document ?? null;
  const current = currentId
    ? (documents.find((d) => d.id === currentId) ?? null)
    : null;
  // A filename if we have one. Falling back to the id is still better than
  // nothing, but it is the exception, not the label.
  const currentName = current?.filename ?? currentId ?? null;
  // `busy` from health, not an id: the panel knows work is happening even
  // when it is not authorised to know what.
  const working = w.busy;

  // Alarm only when nothing is being worked on. Work in progress is reported
  // as work, however slow.
  const alarm = w.stalled && !working;
  const slow = w.stalled && working;

  return (
    <section
      aria-labelledby="worker-heading"
      className={[
        "rounded-lg border p-4",
        alarm
          ? "border-danger-500/60 bg-danger-500/10"
          : slow
            ? "border-warn-500/50 bg-warn-500/5"
            : "border-ink-700 bg-ink-850",
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
            alarm
              ? "bg-danger-500/20 text-danger-500"
              : working
                ? "bg-signal-500/15 text-signal-400"
                : w.alive
                  ? "bg-signal-500/15 text-signal-400"
                  : "bg-ink-700 text-slateish-400",
          ].join(" ")}
        >
          {alarm ? "not moving" : working ? "working" : w.alive ? "idle" : "not running"}
        </span>
      </div>

      {alarm && (
        <div role="alert" className="mt-3 text-sm text-danger-500">
          <p className="font-medium">
            Nothing is being processed, and the queue is not moving.
          </p>
          <ul className="mt-1 list-inside list-disc text-xs">
            {(worker?.stalled_reasons ?? []).map((r: string) => (
              <li key={r}>{humaniseReason(r)}</li>
            ))}
          </ul>
        </div>
      )}

      {slow && ((worker?.seconds_since_progress ?? 0)) > SLOW_DOCUMENT_SECONDS && (
        <p role="status" className="mt-3 text-sm text-warn-500">
          No progress recorded for {formatAge((worker?.seconds_since_progress ?? 0))} while working on{" "}
          <span className="font-medium">{currentName}</span>. A long document can run for
          minutes between updates &mdash; the document&rsquo;s own card below shows how far it
          has actually got.
        </p>
      )}

      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="pending"
          value={String((worker?.pending_count ?? 0))}
          tone={(worker?.pending_count ?? 0) > 0 ? "text-warn-500" : undefined}
        />
        <Stat label="oldest waiting" value={formatAge((worker?.oldest_pending_age_seconds ?? null))} />
        <Stat label="since progress" value={formatAge((worker?.seconds_since_progress ?? 0))} />
        {/* The count is per WORKER LIFETIME, not per corpus. Unqualified it
            read "4" beside a list of 8 documents on the same screen. The
            Ingestion view already carried this caption; it belongs wherever
            the number does. */}
        <Stat
          label="completed since the worker started"
          value={String(worker?.documents_completed ?? 0)}
        />
      </dl>

      <p className="mt-3 text-xs text-slateish-400">
        {currentName ? (
          <>
            Working on <span className="font-medium text-slateish-200">{currentName}</span>
            {current && current.chunk_count > 0
              ? ` — ${current.embedded_count.toLocaleString()} of ${current.chunk_count.toLocaleString()} passages embedded`
              : ""}
          </>
        ) : (
          "Nothing is being processed right now."
        )}
      </p>

      {worker?.last_error && (
        <p className="mt-2 rounded bg-ink-900 p-2 text-[11px] text-danger-500">
          Last error: {worker.last_error.message}
        </p>
      )}
    </section>
  );
}
