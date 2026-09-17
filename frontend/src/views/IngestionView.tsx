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
import { useCallback, useState } from "react";

import { usePoll } from "../hooks/usePoll";

import { api } from "../api/client";
import type { WatchEvent, WatchStatus } from "../api/client";
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
    <div className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
      <p className="text-xs uppercase tracking-wide text-slateish-500">{label}</p>
      {measured ? (
        <p className={`mt-1 font-mono text-lg leading-tight ${toneClass}`}>
          {typeof value === "number" ? nf.format(value) : value}
        </p>
      ) : (
        <p className="mt-1 text-sm italic leading-tight text-slateish-500">
          not measured yet
        </p>
      )}
      {hint && <p className="mt-1 text-xs text-slateish-500">{hint}</p>}
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
        "flex items-baseline gap-2 rounded-[var(--radius-xs)] border px-2 py-1.5 text-xs",
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
      {detail && <span className="ml-auto font-mono text-xs">{detail}</span>}
    </li>
  );
}

function DocumentProgress({ doc }: { doc: DocumentRecord }) {
  const status = presentStatus(doc);
  const answerable = reached(doc, "partially_searchable");

  if (OFF_TRACK.includes(doc.status)) {
    return (
      <div className="rounded-[var(--radius-md)] border border-warn-500/40 bg-warn-500/5 p-3">
        <p className="text-sm font-medium text-slateish-200">{doc.filename}</p>
        <p className="mt-1 text-xs text-warn-500">{status.label}</p>
        {doc.error && <p className="mt-1 text-xs text-slateish-300">{doc.error.message}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slateish-200">{doc.filename}</p>
        <p className="font-mono text-xs text-slateish-400">
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

/* ── Watched folder ────────────────────────────────────────────────────────
   The client's team drops PDFs into a folder and the system ingests them.
   This panel answers one question: is that working, and what did it last do.

   Every value here is optional at the source, and the rule is the same one the
   rest of this screen obeys - a value the API did not send renders as NOTHING.
   Not a zero, not a dash, not "N/A". `folder_name` in particular is null for
   a non-admin caller, and a dash in its place would tell that reader there is
   no folder when there is one they may not see.                             */

function plural(n: number, word: string): string {
  return n === 1 ? `1 ${word}` : `${n} ${word}s`;
}

/** "checks every 5 minutes". Null when the interval is absent or nonsensical,
 *  because a scan interval of zero is not a fact worth asserting. */
export function intervalWords(seconds: number | null): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null;
  const say = (n: number, unit: string) =>
    n === 1 ? `checks every ${unit}` : `checks every ${n} ${unit}s`;
  if (seconds % 3600 === 0) return say(seconds / 3600, "hour");
  if (seconds % 60 === 0) return say(seconds / 60, "minute");
  return say(Math.round(seconds), "second");
}

/** "2 minutes ago". Null for an absent or unparseable timestamp - a string the
 *  clock cannot read is not turned into a confident phrase. */
export function relativeTime(iso: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const seconds = (now - at) / 1000;
  // A future timestamp means the two clocks disagree, not that a scan is due.
  if (seconds < 10) return "just now";
  if (seconds < 90) return `${Math.round(seconds)} seconds ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${plural(minutes, "minute")} ago`;
  const hours = Math.round(seconds / 3600);
  if (hours < 36) return `${plural(hours, "hour")} ago`;
  return `${plural(Math.round(seconds / 86400), "day")} ago`;
}

/** How many events the API keeps in `recent` - "the newest ten". A group that
 *  fills the whole list may have been bigger than the list can show. */
const RECENT_CAP = 10;

/** Whole seconds since the epoch, or null for a timestamp the clock cannot
 *  read. Second granularity is deliberate: one scan's events share their
 *  timestamp TO THE SECOND, which is the only handle on grouping we have. */
function atSecond(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return Math.floor(ms / 1000);
}

/** One line answering the question this panel could not answer before: was the
 *  folder actually looked at, and what did that look find. A reader who drops a
 *  PDF in, opens this screen and sees three rows reading `duplicate` has been
 *  told a history and nothing about now; twice that reader concluded the
 *  feature was broken when it was merely between scans.
 *
 *  The count is DERIVED, not reported. The API states no scan id and no
 *  per-scan totals; all it gives is that the events of a single scan carry the
 *  same `at` to the second. So "the newest same-second group" is an INFERENCE
 *  about which decisions belong to the latest scan, and it can be wrong in
 *  exactly one direction:
 *
 *   - a scan whose writes straddle a second boundary is split, and only the
 *     later part of it is grouped here;
 *   - a group that fills all ten kept events may have been larger, and by how
 *     much is not knowable from this payload.
 *
 *  Both failure modes make the figure a LOWER BOUND and never an
 *  overstatement, so the wording says "at least" rather than dressing an
 *  inference as a count. The ten-event case says additionally that the list
 *  itself is the limit, because there "at least" understates by an unknown
 *  amount rather than by one boundary's worth, and a bare "10" would read as
 *  the total. Showing an exact number and hoping the grouping held is the
 *  quiet overclaim this line exists to remove.
 *
 *  Null when there is nothing true to say - no scan recorded and no event ever
 *  seen - which renders as nothing, like every other unknown on this screen. */
export function scanSummary(status: WatchStatus): string | null {
  const scanAt = atSecond(status.last_scan_at);
  const events = status.recent;
  // A scan ran and decided nothing at all. This is the ordinary steady state,
  // and it is the case the reader needed most: the folder WAS looked at.
  const quiet = "the last check found nothing new in the folder.";

  if (events.length === 0) return scanAt == null ? null : quiet;

  let newest: number | null = null;
  for (const event of events) {
    const at = atSecond(event.at);
    if (at != null && (newest == null || at > newest)) newest = at;
  }
  // Every event timestamp is unreadable, so which of them shared a scan cannot
  // be worked out. No count is asserted from data this shape.
  if (newest == null) return scanAt == null ? null : quiet;

  // The folder has been checked since the newest decision was made, so the
  // latest check produced no events of its own. Describing the older group
  // here would present a past scan as the current one - the precise untruth
  // the panel already committed by showing only rows.
  //
  // The comparison is strict and unpadded, which errs toward this branch: a
  // scan slow enough that its own last_scan_at lands a second after its events
  // is reported as having found nothing, with its rows visible and timestamped
  // directly below. That understates a real scan rather than attributing
  // decisions to a check that may not have made them.
  if (scanAt != null && scanAt > newest) return quiet;

  const group = events.filter((event) => atSecond(event.at) === newest);
  const added = group.filter((event) => event.outcome === "ingested").length;
  const newPart = added === 0 ? "none of them new" : `including ${plural(added, "new file")}`;
  const line = `the last check saw at least ${plural(group.length, "file")}, ${newPart}.`;
  // The group is the whole window, so the window - not the scan - set the size.
  if (group.length === events.length && events.length >= RECENT_CAP) {
    return `${line} Only the newest ${RECENT_CAP} decisions are kept here, so it may have seen more.`;
  }
  return line;
}

/** Colour is never the only signal: every outcome carries its own WORD, and a
 *  glyph beside it, so the three are told apart with the colour removed. */
function outcomeStyle(outcome: string): { glyph: string; word: string; tone: string } {
  if (outcome === "ingested") return { glyph: "+", word: "ingested", tone: "text-signal-400" };
  if (outcome === "duplicate") return { glyph: "=", word: "duplicate", tone: "text-slateish-300" };
  if (outcome === "failed") return { glyph: "x", word: "failed", tone: "text-danger-500" };
  // An outcome this build does not know is reported as it arrived rather than
  // being folded into one of the three it does.
  return { glyph: "·", word: outcome, tone: "text-slateish-300" };
}

function WatchRow({ event }: { event: WatchEvent }) {
  const style = outcomeStyle(event.outcome);
  const when = relativeTime(event.at);
  return (
    <li className="flex flex-wrap items-baseline gap-2 rounded-[var(--radius-xs)] border border-ink-700 bg-ink-800 px-2 py-1.5 text-xs">
      <span aria-hidden className={`font-mono ${style.tone}`}>
        {style.glyph}
      </span>
      <span className="font-medium text-slateish-200">{event.filename}</span>
      <span className={style.tone}>{style.word}</span>
      {when && (
        <span className="ml-auto font-mono text-xs text-slateish-300" title={event.at}>
          {when}
        </span>
      )}
      {event.outcome === "failed" && event.detail && (
        <span className="w-full text-slateish-300">{event.detail}</span>
      )}
    </li>
  );
}

type WatchState =
  | { kind: "loading" }
  | { kind: "ok"; status: WatchStatus }
  | { kind: "unknown" };

function WatchedFolderPanel() {
  const [state, setState] = useState<WatchState>({ kind: "loading" });

  const load = useCallback(async () => {
    const result = await api.watchStatus();
    // A failed read drops whatever was here. Stale rows presented as current
    // are the same untruth as an unmeasured number shown as zero.
    setState(result.ok ? { kind: "ok", status: result.data } : { kind: "unknown" });
  }, []);

  // The same hook the rest of the app polls with, at its idle cadence: the
  // folder is scanned once every few minutes, so asking three times a second
  // while the worker is busy would buy nothing and cost a request each time.
  usePoll(
    useCallback(() => {
      void load();
    }, [load]),
    false,
  );

  // Nothing is known yet, so nothing is said - a heading over an empty box
  // would imply the panel has an answer it does not have.
  if (state.kind === "loading") return null;

  if (state.kind === "unknown") {
    return (
      <Section title="Watched folder">
        <p className="text-sm text-slateish-300">
          The watched folder could not be read, so its status is unknown.
        </p>
      </Section>
    );
  }

  const status = state.status;

  // Off is a normal state, not a fault. No warning colour, no error card.
  if (!status.enabled) {
    return (
      <Section title="Watched folder">
        <p className="text-sm text-slateish-300">The watched folder is not configured.</p>
      </Section>
    );
  }

  const interval = intervalWords(status.interval_seconds);
  const lastScan = relativeTime(status.last_scan_at);
  const scanLine = scanSummary(status);

  return (
    <Section
      title="Watched folder"
      hint="Documents dropped into this folder are ingested without anyone uploading them."
    >
      <div className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
        {/* Reachability is rendered in ONE direction only.
            false is the state that matters at a client site - a share
            unmounted, a VPN dropped, permissions revoked - and it is written
            in the present tense so it cannot be read as one more past event
            in the list below. true says nothing at all: a panel that reports
            OK on every poll is a panel people stop reading, and silence is
            the honest rendering of normal. null says nothing either - no scan
            has finished, and the interval already tells the reader one is
            coming. `last_error` appears only inside this branch, so it can
            never be shown without the framing that explains it. */}
        {status.reachable === false && (
          <p
            role="alert"
            className="mb-2 rounded-[var(--radius-xs)] border border-danger-500/50 bg-danger-500/10 px-2 py-1.5 text-xs"
          >
            <span className="font-medium text-danger-500">
              The folder is not being read right now.
            </span>
            {status.last_error && (
              <span className="ml-1 text-slateish-300">{status.last_error}</span>
            )}
          </p>
        )}

        {/* The NAME of the folder, which is all the API has: the host path was
            removed from the route, not merely gated. So the line names the
            folder rather than saying where it is - "watch-inbox" beside a
            label reading like a path would have the reader believe they are
            being shown a truncated one. No title or aria-label carries a path
            either; there is none to carry. */}
        {status.folder_name ? (
          <p className="text-xs text-slateish-300">
            watching a folder named{" "}
            <span className="break-all font-mono text-slateish-200">{status.folder_name}</span>
          </p>
        ) : null}

        {(interval || lastScan) && (
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slateish-300">
            {interval && <span>{interval}</span>}
            {lastScan && (
              <span title={status.last_scan_at ?? undefined}>last checked {lastScan}</span>
            )}
          </p>
        )}

        {/* Derived from the events, and worded as derived - see scanSummary.
            It sits above the rows because the rows are a history and this is
            the sentence about now. Null renders as nothing. */}
        {scanLine && <p className="mt-1 text-xs text-slateish-300">{scanLine}</p>}

        {status.recent.length === 0 ? (
          <p className="mt-2 text-sm text-slateish-300">
            Nothing has arrived in the folder yet.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {status.recent.map((event, i) => (
              <WatchRow key={`${event.at}-${event.filename}-${i}`} event={event} />
            ))}
          </ul>
        )}
      </div>
    </Section>
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

  // Same reasoning as Documents, smaller payoff: this screen was already at
  // 15 s rather than 3 s, so the saving is a quarter of the size. It still
  // applies - when the worker is idle this screen renders "Nothing is being
  // processed", and re-fetching that twice a minute buys nothing.
  //
  // The worker flag comes from health, which the shell already polls, so
  // reading it here costs no request.
  const busy =
    connection.state === "online" &&
    (connection.health.ingestion.busy || connection.health.ingestion.stalled);

  usePoll(
    useCallback(() => {
      if (connection.state === "online") void load();
    }, [connection.state, load]),
    busy,
  );

  const worker = connection.state === "online" ? connection.health.ingestion : null;
  // The document being processed comes from the SCOPED metrics, never from
  // health: health is unauthenticated and a document id is not public.
  const activeWorker = metrics?.worker ?? null;

  const pageIdentity = (
    <div className="mb-4">
      <h1 className="text-lg font-semibold text-slateish-200">Ingestion</h1>
      <p className="mt-0.5 text-sm text-slateish-400">
        What the system is doing to your documents, and how fast it is doing it.
      </p>
    </div>
  );

  if (error) return <div>{pageIdentity}<ErrorState error={error} onRetry={onRetryConnection} /></div>;
  // Array.isArray, not a truthiness check. A malformed payload used to crash
  // this whole screen on `documents.filter`, which is the one thing a status
  // screen must never do - it is what you look at when things are wrong.
  if (!metrics || !worker || !Array.isArray(documents)) {
    return <div>{pageIdentity}<Spinner label="Reading the queue" /></div>;
  }

  const inProgress = documents.filter(
    (d) => !OFF_TRACK.includes(d.status) && d.status !== "ready",
  );
  const finished = documents.filter((d) => d.status === "ready");
  const trouble = documents.filter((d) => OFF_TRACK.includes(d.status));
  const currentName =
    documents.find((d) => d.id === activeWorker?.current_document)?.filename ??
    activeWorker?.current_document ??
    null;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>{pageIdentity}</div>
        <p className="font-mono text-xs text-slateish-500">
          every {metrics.refresh_seconds}s
        </p>
      </div>

      <Section title="Right now">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Tile
            label="Worker"
            value={
              activeWorker?.current_document != null
                ? "working"
                : worker.stalled
                  ? "not moving"
                  : worker.alive
                    ? "idle"
                    : "stopped"
            }
            tone={
              worker.stalled && activeWorker?.current_document == null
                ? "danger"
                : worker.alive
                  ? "good"
                  : "warn"
            }
            hint={currentName ?? "nothing in progress"}
          />
          <Tile label="Waiting" value={activeWorker?.pending_count} hint="documents in the queue" />
          <Tile
            label="Oldest wait"
            value={formatAge((activeWorker?.oldest_pending_age_seconds ?? null))}
            hint="how long the front of the queue has waited"
          />
          <Tile
            label="Finished"
            value={activeWorker?.documents_completed}
            hint="since the worker started"
          />
        </div>
      </Section>

      <WatchedFolderPanel />

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
                className="flex flex-wrap items-baseline gap-2 rounded-[var(--radius-xs)] border border-ink-700 bg-ink-850 px-3 py-2 text-xs"
              >
                <span className="font-medium text-slateish-200">{d.filename}</span>
                <span className="font-mono text-xs text-slateish-400">
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
