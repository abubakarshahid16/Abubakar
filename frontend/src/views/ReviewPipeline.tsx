/**
 * #791 part 2: the review step by step - how this run was done.
 *
 * WHY. A review is one button and a result; on 10 Oct "not a single
 * compliant" took hours to explain. This shows what each of the ten steps
 * produced (read, clean, equipment, standards, checklist, rules, decide,
 * coverage, CRS, code), with a warning badge where something looks wrong,
 * and the run's AI use - from the trace the server stored when the run
 * finished (`GET /api/reviews/runs/{id}/trace`), never recomputed here.
 *
 * INTERNAL. The items carry document values; the panel is on the engineer's
 * review page only, and the download is the same trace as a JSON file.
 * Fetched on open, like the review notes: most visits to a run are about its
 * findings.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../api/client";
import type { ReviewTrace, ReviewTraceStep } from "../types/api";
import { STEP_NAMES } from "./reviewPipelineSteps";


const BADGE: Record<string, { label: string; className: string }> = {
  ok: { label: "OK", className: "border-ink-600 text-slateish-300" },
  warning: { label: "Warning", className: "border-warn-500 text-warn-500" },
  failed: { label: "Failed", className: "border-danger-500 text-danger-500" },
};

function seconds(step: ReviewTraceStep): string {
  const s = step.timing?.seconds;
  return typeof s === "number" ? ` (${s.toFixed(1)} s)` : "";
}

function StepRow({ step, index }: { step: ReviewTraceStep; index: number }) {
  const badge = BADGE[step.status] ?? BADGE.ok;
  return (
    <li data-testid={`trace-step-${step.step}`} className="space-y-1">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium text-slateish-100">
          {index + 1}. {STEP_NAMES[step.step] ?? step.step}
        </span>
        <span className={`rounded-[var(--radius-sm)] border px-1.5 text-[11px] ${badge.className}`}>
          {badge.label}
        </span>
        <span className="text-xs text-slateish-400">{seconds(step)}</span>
      </div>
      <p className="text-xs text-slateish-300">{step.summary}</p>
      {step.warning && (
        <p className="text-xs text-warn-500">Warning: {step.warning}</p>
      )}
      {step.items.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-signal-300">
            Show {step.items.length} item{step.items.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1 max-h-64 space-y-0.5 overflow-auto font-mono text-[11px] text-slateish-300">
            {step.items.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </details>
      )}
    </li>
  );
}

function AiUse({ ai }: { ai: ReviewTrace["ai"] }) {
  const entries = Object.entries(ai ?? {});
  if (entries.length === 0) return null;
  return (
    <div data-testid="trace-ai" className="text-xs text-slateish-300">
      <p className="font-medium text-slateish-200">AI use in this run</p>
      <ul className="mt-1 space-y-0.5">
        {entries.map(([name, status]) => (
          <li key={name}>
            {name.replace(/_/g, " ")}: {String(status?.plain ?? "no status recorded")}
            {status?.model ? ` (model ${String(status.model)})` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReviewPipeline({ runId }: { runId: string }) {
  const [trace, setTrace] = useState<ReviewTrace | null>(null);
  const [error, setError] = useState<string | null>(null);

  function download() {
    if (!trace) return;
    const blob = new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `review-trace-${runId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <details className="text-sm" data-testid="review-pipeline"
      onToggle={(event) => {
        if (!(event.currentTarget as HTMLDetailsElement).open || trace !== null) return;
        void reviewsApi.reviewTrace(runId).then((r) => {
          if (!r.ok) { setError(r.error.message); return; }
          setTrace(r.data);
        });
      }}>
      <summary className="cursor-pointer text-slateish-200">
        How this review was done - step by step (internal)
      </summary>
      {error && <p role="alert" className="mt-1 text-xs text-danger-500">{error}</p>}
      {trace === null && !error && <p className="mt-1 text-xs text-slateish-400">Loading…</p>}
      {trace !== null && (
        <div className="mt-2 space-y-3">
          {trace.steps.length === 0 ? (
            <p className="text-xs text-slateish-400">No steps were recorded for this run.</p>
          ) : (
            <ol className="space-y-3">
              {trace.steps.map((step, i) => <StepRow key={step.step} step={step} index={i} />)}
            </ol>
          )}
          <AiUse ai={trace.ai} />
          <div className="flex flex-wrap items-center gap-3 text-xs text-slateish-400">
            <span>Source: {trace.source}</span>
            <button type="button" onClick={download}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 text-slateish-200">
              Download trace (JSON, internal)
            </button>
          </div>
        </div>
      )}
    </details>
  );
}
