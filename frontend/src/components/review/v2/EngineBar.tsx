/** SPEC 1 and 2: ONE engine choice and ONE Review button, and the engine line that says, before anything starts, which engine runs,
 *  whether text leaves this computer, what it costs and what will not run. */
import { useState } from "react";

import { ENGINE_CHOICES, type EngineChoice, reviewPoints } from "../../../api/reviewPoints";
import { ENGINE_LABELS, NEEDS_YES, costWords, engineWords, wontRunWords } from "./words";
import { usePlan } from "./usePoints";

export function EngineBar({ documentId, isAdmin, onStarted }: {
  documentId: string | null; isAdmin: boolean | undefined; onStarted: (runId: string) => void;
}) {
  const [engine, setEngine] = useState<EngineChoice>("automatic");
  const { plan, reload } = usePlan(documentId, engine);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = plan.state === "ok" ? plan.data : null;

  async function start() {
    if (!documentId) return;
    setBusy(true); setProblem(null);
    const r = await reviewPoints.start(documentId, engine);
    setBusy(false);
    if (!r.ok) { setProblem(r.error.message); return; }
    onStarted(r.data.review_run_id);
  }
  async function yes() {
    if (!documentId) return;
    setBusy(true);
    const r = await reviewPoints.recordYes(documentId);
    setBusy(false);
    if (!r.ok) setProblem(r.error.message); else await reload();
  }

  return (
    <div data-testid="v2-engine" className="space-y-2">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <div role="radiogroup" aria-label="Which engine reads this paper" className="inline-flex overflow-hidden rounded-[var(--radius-sm)] border border-ink-500">
          {ENGINE_CHOICES.map((c) => (
            <button key={c} type="button" role="radio" aria-checked={engine === c} onClick={() => setEngine(c)}
              className={`px-3 py-1.5 text-sm ${engine === c ? "bg-signal-500 text-ink-950" : "text-slateish-200 hover:bg-ink-700"}`}>
              {ENGINE_LABELS[c]}
            </button>
          ))}
        </div>
        {isAdmin !== false ? (
          <button type="button" onClick={() => void start()} disabled={busy || !ready || ready.refused != null}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-1.5 text-sm font-semibold text-ink-950 disabled:opacity-50">
            Review
          </button>
        ) : <span className="text-xs text-slateish-400">Only an administrator can start a review.</span>}
      </div>
      {plan.state === "loading" && <p className="text-right text-xs text-slateish-400">Checking what this would do…</p>}
      {plan.state === "error" && <p role="alert" className="text-right text-xs text-warn-500">{plan.message}</p>}
      {ready && (
        <div data-testid="v2-engine-line" className="space-y-0.5 text-right text-xs text-slateish-300">
          <p>{engineWords(ready)}</p>
          {costWords(ready) && <p>{costWords(ready)}</p>}
          {wontRunWords(ready).map((w) => <p key={w}>{w}</p>)}
          {ready.unscored_note && <p>{ready.unscored_note}.</p>}
          {ready.needs_yes && (
            <p data-testid="v2-needs-yes">
              This contract {NEEDS_YES}.{" "}
              {isAdmin !== false && (
                <button type="button" onClick={() => void yes()} disabled={busy}
                  className="text-signal-300 underline-offset-2 hover:underline">Record the owner's yes</button>
              )}
            </p>
          )}
          {ready.notes.map((n) => <p key={n}>{n}</p>)}
        </div>
      )}
      {problem && <p role="alert" className="text-right text-xs text-danger-500">{problem}</p>}
    </div>
  );
}
