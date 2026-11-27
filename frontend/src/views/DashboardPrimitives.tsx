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
import type { ClassificationCoverage } from "../api/client";
import type { Metrics, StageThroughput } from "../types/api";
import { NEW_LOOK } from "../look";
import { TileLine } from "../components/look/LookParts";

const STAGE_LABELS: Record<string, string> = {
  extract: "Extraction",
  chunk: "Chunking",
  keyword_index: "Keyword index",
  embed: "Making searchable",
};

/** Update 12: the technical-query attachments nobody filed into the library are counted APART, never inside the library's numbers. */
function attachmentsApart(n: number | null | undefined, nf: Intl.NumberFormat): string {
  return n ? ` (${nf.format(n)} technical-query attachment${n === 1 ? "" : "s"} counted apart: not in search, Chat or reviews until filed)` : "";
}

export function bytes(n: number): string {
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

export const nf = new Intl.NumberFormat();

/** The one way this screen says a value has not been measured. Shared by
 *  `Stat`, the CPU card and the Disk card so the wording and style cannot drift
 *  between them - the Disk card once had no such branch at all and rendered
 *  an unmeasured disk as a 0%-used bar in the healthy tone. */
export function NotMeasured() {
  return (
    <p className="mt-1 text-sm italic leading-tight text-slateish-500">
      not measured yet
    </p>
  );
}

/** A measured value, or an explicit statement that it has not been measured. */
export function Stat({
  label,
  value,
  hint,
  tone = "normal",
}: {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  /** "late": the new look's inverted tile (dark red ground, white words; spec "Late tile inverted"); classic: as "warn". */
  tone?: "normal" | "warn" | "danger" | "good" | "late";
}) {
  const measured = value !== null && value !== undefined;
  if (NEW_LOOK) {
    const late = tone === "late";
    return (
      <div className={`rounded-[var(--radius-md)] px-5 py-4 ${late ? "bg-pill-fail-bg text-pill-fail-fg" : "bg-ink-800 shadow-[var(--shadow-resting)]"}`}>
        <p className={`text-sm font-semibold ${late ? "" : "text-slateish-400"}`}>{label}</p>
        {measured ? (
          <p className={`mt-1 font-[family-name:var(--font-heading)] text-[2.5rem] font-bold leading-none ${late ? "" : tone === "warn" ? "text-warn-500" : "text-slateish-100"}`}>
            {typeof value === "number" ? nf.format(value) : value}
          </p>
        ) : (
          <NotMeasured />
        )}
        {hint && <TileLine text={hint} inverted={late} />}
      </div>
    );
  }
  const toneClass =
    tone === "warn"
      ? "text-warn-500"
      : tone === "danger"
        ? "text-danger-500"
        : tone === "good"
          ? "text-signal-400"
          : tone === "late"
            ? "text-warn-500"
            : "text-slateish-100";
  if (NEW_LOOK) {
    // the kit's card, name and number (H's audit 2: one card style on the Dashboard; no mono, no capitals)
    return (
      <div className="kit-card">
        <p className="kit-tile__name">{label}</p>
        {measured ? (
          <p className={`kit-tile__number ${kitTone(tone)}`}>{typeof value === "number" ? nf.format(value) : value}</p>
        ) : (
          <NotMeasured />
        )}
        {hint && <p className="kit-small">{hint}</p>}
      </div>
    );
  }
  return (
    <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
      <p className="text-xs uppercase tracking-wide text-slateish-500">{label}</p>
      {measured ? (
        <p className={`mt-1 font-mono text-lg leading-tight ${toneClass}`}>
          {typeof value === "number" ? nf.format(value) : value}
        </p>
      ) : (
        <NotMeasured />
      )}
      {hint && <p className="mt-1 text-xs text-slateish-500">{hint}</p>}
    </div>
  );
}

export function Section({
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
export function Headline({
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
  if (NEW_LOOK) {
    return (
      <div className="kit-card" data-kind="headline">
        <p className="kit-tile__name">{label}</p>
        {value == null ? (
          <p className="mt-2 text-lg italic leading-tight text-slateish-500">nothing measured yet</p>
        ) : (
          <p className={`kit-tile__number ${kitTone(tone)}`}>
            {value}
            {unit && <span className="ms-1.5 text-lg text-slateish-500">{unit}</span>}
          </p>
        )}
        {children}
        <TileLine text={note} />
      </div>
    );
  }
  return (
    <div className="card-3d surface-floating rounded-[var(--radius-lg)] border border-ink-700 bg-ink-800 px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slateish-400">{label}</p>
      {value == null ? (
        <p className="mt-2 text-lg italic leading-tight text-slateish-500">
          nothing measured yet
        </p>
      ) : (
        <p className={`mt-2 font-mono text-[2.6rem] leading-none ${toneClass}`}>
          {value}
          {unit && <span className="ms-1.5 text-lg text-slateish-500">{unit}</span>}
        </p>
      )}
      {children}
      <p className="mt-3 text-sm leading-relaxed text-slateish-300">{note}</p>
    </div>
  );
}

export function Bar({ percent, tone }: { percent: number; tone: "normal" | "warn" | "danger" }) {
  const colour =
    tone === "danger" ? "bg-danger-500" : tone === "warn" ? "bg-warn-500" : "bg-signal-500";
  return (
    <div
      className="mt-1.5 h-1.5 overflow-hidden rounded-[var(--radius-full)] bg-ink-700"
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full ${colour}`} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

export function loadTone(percent: number): "normal" | "warn" | "danger" {
  if (percent >= 90) return "danger";
  if (percent >= 75) return "warn";
  return "normal";
}

export function ReadinessPanel({ metrics }: { metrics: Metrics }) {
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
        ? `${nf.format(metrics.corpus.documents)} document${metrics.corpus.documents === 1 ? "" : "s"} loaded, ${nf.format(metrics.corpus.chunks_retrievable)} parts of pages a question can reach`
          + attachmentsApart(metrics.corpus.technical_query_attachments, nf)
        : "upload at least one PDF with readable text",
    },
    {
      label: "Answering",
      ok: localModelsReady,
      detail: localModelsReady
        ? "search and the AI are running on this computer"
        : "the AI on this computer is missing or not running - answers will be limited",
    },
    {
      label: "Uploads",
      ok: workerReady,
      detail: !workerReady
        ? "processing has stopped - new uploads will wait"
        : metrics.worker.reviewing && (metrics.worker.uploads_waiting_for_review ?? 0) > 0
          ? `busy with a review: ${nf.format(metrics.worker.uploads_waiting_for_review ?? 0)} upload${metrics.worker.uploads_waiting_for_review === 1 ? "" : "s"} waiting`
          : metrics.worker.reviewing && metrics.worker.pending_count > 0
            ? `a review is running; ${nf.format(metrics.worker.pending_count)} upload${metrics.worker.pending_count === 1 ? " is" : "s are"} read beside it`
            : "new documents will be processed as they arrive",
    },
    {
      label: NEW_LOOK ? "Prices" : "Market data",
      ok: true,
      detail: NEW_LOOK ? "examples only: no live price source is connected" : "illustrative sample only - no live market source is connected",
      tone: "warn" as const,
    },
    {
      label: NEW_LOOK ? "Reports" : "PDF reports",
      ok: false,
      // "not yet available" is a banned phrase here - it was true of OCR once,
      // and of the summary once, and each time it stayed on screen after the
      // thing arrived. Say what exists, not what does not.
      detail: NEW_LOOK ? "one PDF per answer, with its sources kept as they were" : "one PDF per answer, with its evidence frozen in - reports cover single answers, not a whole analysis",
      tone: "warn" as const,
    },
  ];

  return (
    <section className="card-3d surface-card rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slateish-200">What this system can do right now</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slateish-400">
            Green is measured and working on this computer. Amber is a limit you should know
            about before relying on it.
          </p>
        </div>
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
            <li key={g.label} className={`rounded-[var(--radius-sm)] border px-3 py-2 ${klass}`}>
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
/** A figure's tone as the kit's colour classes (kit colours win over page utilities, so a tone is a kit class, never a text-* one). */
export function kitTone(tone: string | undefined): string {
  return tone === "good" ? "kit-ok" : tone === "danger" ? "kit-late" : tone === "warn" || tone === "late" ? "kit-check" : "";
}

export function TypeCounts({ byType }: { byType: ClassificationCoverage["by_type"] }) {
  if (byType.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
      {byType.map((t) => (
        <span key={t.type} className={NEW_LOOK ? "text-xs leading-tight" : "font-mono text-xs leading-tight"}>
          <span className="text-slateish-500">{t.type}</span>{" "}
          <span className="text-slateish-200">{nf.format(t.uploaded)}</span>
        </span>
      ))}
    </div>
  );
}

export function Throughput({ stage, data }: { stage: string; data: StageThroughput | null }) {
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
