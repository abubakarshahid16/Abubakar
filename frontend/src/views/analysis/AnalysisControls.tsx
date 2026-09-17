// @ts-nocheck
import React from "react";
import { ModeSelector } from "../../components/analysis/ModeSelector";
import { TypeFilter, pendingFilterNotice } from "../../components/classification/TypeFilter";
import { RunPlan } from "./AnalysisRunPlan";

export function AnalysisControls({ ctx }: { ctx: any }) {
  const { questionId, question, comparisonType, selectedTypes, appliedScope, typeVocabulary,
    mode, toggles, running, canRun, elapsed, waitingOn, baselineRefusal, store, engines } = ctx;
  return <section aria-label="Analysis controls" className="card-3d surface-floating rounded-[var(--radius-lg)] border border-ink-600 bg-ink-800 p-4">
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-4">
        <div><label htmlFor={questionId} className="block text-xs font-semibold uppercase tracking-wide text-slateish-400">Question</label>
          <textarea id={questionId} rows={4} value={question} onChange={(e) => store.setQuestion(e.target.value)} placeholder="Example: What does PID mean in this control section?" className="mt-2 w-full resize-y rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-base text-slateish-100 placeholder:text-slateish-500" />
        </div>
        <label htmlFor="comparison-type" className="block text-xs font-semibold uppercase tracking-wide text-slateish-400">Comparison workflow
          <select id="comparison-type" value={comparisonType} onChange={(e) => store.patch({ comparisonType: e.target.value })} className="mt-2 block w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm font-normal normal-case text-slateish-200">
            <option value="">No named comparison</option><option value="baseline_vs_submittal">Baseline vs submittal</option><option value="requirements_vs_submittal">Requirements vs submittal</option><option value="revision_delta">Revision delta</option><option value="discipline_coordination">Discipline coordination</option>
          </select>
          {comparisonType && <span className="mt-1 block text-xs font-normal normal-case text-slateish-500">Pick the documents for this workflow; the system will not invent an authoritative baseline.</span>}
        </label>
        <div aria-label="Search in"><p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slateish-400">Search scope</p><p className="mb-2 text-xs text-slateish-400">Leave all filters clear to search across every indexed document. Select a category only when you want to narrow the run.</p>
          <TypeFilter vocabulary={typeVocabulary} selected={selectedTypes} onToggle={store.toggleType} onClear={store.clearTypes} applied={appliedScope} label="Document categories" layout="column" />
          {appliedScope === null && pendingFilterNotice(selectedTypes) !== null && <p className="mt-1 text-xs text-slateish-400">{pendingFilterNotice(selectedTypes)}</p>}
        </div>
        <ModeSelector mode={mode} onChange={store.changeMode} toggles={toggles} onToggle={store.changeToggle} />
      </div>
      <div className="space-y-3"><RunPlan mode={mode} engines={engines} />
        {mode === "comprehensive" && <p className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/[0.08] px-3 py-2 text-xs text-warn-500">Persistent analysis jobs, streaming progress and cancellation are not exposed by this backend yet. This frontend sends the available wider synchronous request and labels that limitation.</p>}
        <button type="button" disabled={!canRun} aria-busy={running} onClick={() => void store.runAnalysis()} className="w-full rounded-[var(--radius-sm)] border border-signal-500/70 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-[var(--shadow-raised)] motion-safe:transition-all hover:shadow-[var(--shadow-glow)] active:scale-[0.98] disabled:cursor-not-allowed disabled:border-ink-500 disabled:bg-ink-700 disabled:text-slateish-500 disabled:shadow-none">{running ? "Running…" : "Run analysis"}</button>
        {running && <div role="status" aria-live="polite" data-testid="analysis-run-status" className="rounded-[var(--radius-xs)] border border-ink-700 bg-ink-850 p-3"><div className="flex items-baseline justify-between gap-3"><p className="text-sm font-medium text-slateish-200">Working on this machine</p><span data-testid="analysis-elapsed" className="shrink-0 font-mono text-sm tabular-nums text-slateish-300">{elapsed}s</span></div>{waitingOn.length > 0 && <p className="mt-1.5 text-xs text-slateish-400">Still waiting on: {waitingOn.join(", ")}.</p>}<p className="mt-1.5 text-xs text-slateish-500">Generation runs on this CPU and is not streamed; the backend reports no stage for analysis, so only the elapsed time is shown. Leaving this screen does not cancel the run - the result will be here when you come back.</p></div>}
        {baselineRefusal !== null && <p role="alert" className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-xs text-warn-500">{baselineRefusal}</p>}
      </div>
    </div>
  </section>;
}
