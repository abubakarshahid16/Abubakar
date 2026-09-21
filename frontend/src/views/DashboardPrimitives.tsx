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

const STAGE_LABELS: Record<string, string> = {
  extract: "Extraction",
  chunk: "Chunking",
  keyword_index: "Keyword index",
  embed: "Embedding",
};

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
    <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5">
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
    <section className="card-3d surface-card rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slateish-200">What this system can do right now</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slateish-400">
            Green is measured and working on this computer. Amber is a limit you should know
            about before relying on it.
          </p>
        </div>
        <span className="rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/10 px-2 py-1 font-mono text-xs text-warn-500">
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
export function TypeCounts({ byType }: { byType: ClassificationCoverage["by_type"] }) {
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
