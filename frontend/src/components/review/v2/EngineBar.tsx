/** SPEC 1 and 2: ONE engine choice and ONE Review button, and the engine line that says, before anything starts, which engine runs,
 *  whether text leaves this computer, what it costs and what will not run.
 *
 *  THE LIST (owner, 12 Nov 2026, #1584: "the screen lists every document that will leave the Mac before the review starts"): the plan's
 *  `documents.leaving` is shown with the engine line (the same `LeavingList` as the older panel), and "Review" opens a pre-start step first
 *  (the list, the cost, the contract line, the draft sentence); "Start" calls the ONE start with exactly the ids shown. If the plan or the
 *  list cannot be loaded no Claude start is offered; Local only stays possible and starts at once. */
import { useRef, useState } from "react";

import { ENGINE_CHOICES, type EngineChoice, reviewPoints } from "../../../api/reviewPoints";
import { LeavingList } from "../panels/LeavingList";
import { ENGINE_LABELS, NEEDS_YES, costWords, engineWords, wontRunWords } from "./words";
import { usePlan } from "./usePoints";
import { Button } from "../../kit/Kit";

/** The plan's refusal codes that choosing Claude explicitly lifts (the same list the server's `LIFTED_BY_CLAUDE` holds). */
const LIFTED_BY_CLAUDE = ["NEEDS_YES", "NOT_APPROVED", "BOOKS_NOT_APPROVED", "UNSCORED"];

export function EngineBar({ documentId, isAdmin, onStarted }: {
  documentId: string | null; isAdmin: boolean | undefined; onStarted: (runId: string) => void;
}) {
  const [engine, setEngine] = useState<EngineChoice>("automatic");
  const [ticked, setTicked] = useState<string[]>([]); // held Schedules the engineer chose to compare: the plan is asked again with them
  const { plan } = usePlan(documentId, engine, ticked);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = plan.state === "ok" ? plan.data : null;
  const previous = useRef<{ documentId: string | null; engine: EngineChoice; data: NonNullable<typeof ready> } | null>(null);
  if (ready) previous.current = { documentId, engine, data: ready };
  const displayed = ready ?? (previous.current?.documentId === documentId && previous.current.engine === engine
    ? previous.current.data : null);
  const leaving = ready?.documents.leaving;
  // A list the server did not give (older server) or could not work out is no list: no Claude start.
  const listKnown = Array.isArray(leaving) && ready?.documents.unreadable !== true;
  const local = engine === "local";
  const failedClosed = !local && plan.state === "error";
  const selectionsReady = (ready?.documents.offered ?? []).every(o => o.ticked === ticked.includes(o.id))
    && ticked.every(id => (leaving ?? []).some(document => document.id === id));
  const canReview = local ? !ready?.refused : ready != null && !ready.refused && listKnown && selectionsReady;
  const contractLine = engine === "claude" && ready?.text_leaves === true && (leaving ?? []).some((d) => d.contract);

  async function start(shown: string[], chosen: string[] = []) {
    if (!documentId) return;
    setBusy(true); setProblem(null);
    const r = await reviewPoints.start(documentId, engine, shown, ...(chosen.length ? [chosen] : []));
    setBusy(false);
    if (!r.ok) { setProblem(r.error.message); return; }
    setStep(false);
    onStarted(r.data.review_run_id);
  }
  function review() {
    if (local || !ready?.text_leaves) { void start([]); return; } // nothing leaves this computer: no step is needed
    setStep(true);
  }
  function choose(c: EngineChoice) { setEngine(c); setTicked([]); setStep(false); setProblem(null); }

  const list = displayed && Array.isArray(displayed.documents.leaving) ? (
    <LeavingList leaving={displayed.documents.leaving} notSent={displayed.documents.not_sent ?? []} notReadable={displayed.documents.not_readable ?? 0}
      textLeaves={displayed.text_leaves} webSearch={displayed.documents.web_search}
      offered={displayed.documents.offered?.map(o => ({ ...o, ticked: ticked.includes(o.id) }))}
      onTick={(id, on) => { setStep(false); setTicked((t) => (on ? [...new Set([...t, id])] : t.filter((x) => x !== id))); }} />
  ) : null;

  return (
    <div data-testid="v2-engine" className="space-y-2">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <div role="radiogroup" aria-label="Who reviews this paper" className="inline-flex overflow-hidden rounded-[var(--radius-sm)] border border-ink-500">
          {ENGINE_CHOICES.map((c) => (
            <button key={c} type="button" role="radio" aria-checked={engine === c} onClick={() => choose(c)}
              className={`px-3 py-1.5 text-sm ${engine === c ? "bg-signal-500 text-ink-950" : "text-slateish-200 hover:bg-ink-700"}`}>
              {ENGINE_LABELS[c]}
            </button>
          ))}
        </div>
        {isAdmin !== false ? (
          <Button variant="primary" size="sm" onClick={review} disabled={busy || !canReview || step}>
            Review
          </Button>
        ) : <span className="text-xs text-slateish-400">Only an administrator can start a review.</span>}
      </div>
      {plan.state === "loading" && documentId && <p className="text-right text-xs text-slateish-400">Checking what this would do…</p>}
      {/* Automatic held this paper back for a reason the explicit choice of Claude lifts (not scored for Automatic, a contract, not approved):
          the way forward is ONE click, never a greyed-out button with no way out (first-time user, 19 Nov: the HAZOP plan) */}
      {engine === "automatic" && ready?.refused && ready.refused_code != null && LIFTED_BY_CLAUDE.includes(ready.refused_code) && (
        <p className="text-right text-xs">
          <Button variant="secondary" size="sm" data-testid="v2-choose-claude" onClick={() => choose("claude")}>
            Choose Claude to review this paper
          </Button>
        </p>
      )}
      {plan.state === "error" && <p role="alert" className="text-right text-xs text-warn-500">{plan.message}</p>}
      {failedClosed && (
        <p role="alert" data-testid="v2-failed-closed" className="text-right text-xs text-warn-500">
          The plan could not be loaded, so Claude is not offered. Choose Local only to review on this computer.
        </p>
      )}
      {ready && !listKnown && !local && (
        <p role="alert" data-testid="v2-no-list" className="text-right text-xs text-warn-500">
          The documents that would leave this computer could not be worked out, so Claude is not offered. Choose Local only to review on this computer.
        </p>
      )}
      {ready && (
        <div data-testid="v2-engine-line" className="space-y-0.5 text-right text-xs text-slateish-300">
          <p>{engineWords(ready)}</p>
          {costWords(ready) && <p>{costWords(ready)}</p>}
          {/* a refused plan already said why in the line above: its AI part's "will not run" would only repeat it */}
          {wontRunWords(ready).filter((w) => !(ready.refused && w.startsWith("The AI review"))).map((w) => <p key={w}>{w}</p>)}
          {ready.unscored_note && <p>{ready.unscored_note}.</p>}
          {ready.needs_yes && <p data-testid="v2-needs-yes">This paper {NEEDS_YES}.</p>}
          {ready.notes.map((n) => <p key={n}>{n}</p>)}
        </div>
      )}
      {list && !step && <div data-testid="v2-leaving" className="text-left">{list}</div>}
      {step && ready && (
        <div role="dialog" aria-label="Before the review starts" data-testid="v2-prestart"
          className="space-y-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 p-3 text-left text-sm">
          {list}
          {costWords(ready) && <p className="text-slateish-300">{costWords(ready)}</p>}
          {contractLine && (
            <p role="note" data-testid="v2-contract-line" className="font-medium text-slateish-100">
              This sends the contract's text to Claude (Anthropic). You chose Claude for this review.
            </p>
          )}
          {engine === "claude" && ready.unscored && ready.unscored_note && (
            <p role="note" className="text-slateish-300">{ready.unscored_note}. Internal copy only.</p>
          )}
          <div className="flex gap-2">
            <Button variant="primary" size="sm" disabled={busy} onClick={() => void start((leaving ?? []).map((d) => d.id), ticked)}>Start</Button>
            <Button variant="secondary" size="sm" onClick={() => setStep(false)}>Cancel</Button>
          </div>
        </div>
      )}
      {problem && <p role="alert" className="text-right text-xs text-danger-500">{problem}</p>}
    </div>
  );
}
