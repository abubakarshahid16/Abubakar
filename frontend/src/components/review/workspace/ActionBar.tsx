/**
 * OWNER: builder B. "What you need to do": the verdict in one sentence and
 * the four buttons in fixed order (standards, pages, decide, sign). Every
 * number here comes from `computeReviewNumbers` / `actionSteps`; this file
 * counts nothing itself.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { ActionBarProps, ActionStep, ActionStepId } from "./contract";
import { verdictPieces } from "./numbers";

/** The data-count name of each step's number (the shared counts). */
const STEP_COUNT: Record<Exclude<ActionStepId, "sign">, "missingStandards" | "unreadPages" | "undecided"> = {
  standards: "missingStandards",
  pages: "unreadPages",
  decide: "undecided",
};

const BUTTON = "inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed";

function StepLabel({ step }: { step: ActionStep }) {
  if (step.id === "sign" || step.count === null) return <>{step.label}</>;
  // The label carries "(N)"; N is shown from `step.count` so it can be marked.
  const words = step.label.replace(/\s*\(\d[\d,]*\)\s*$/, "");
  return (
    <>
      {words} (<span data-count={STEP_COUNT[step.id]}>{step.count.toLocaleString()}</span>)
    </>
  );
}

type Reread = { busy: boolean; message: string | null; error: string | null };

export function ActionBar({ run, numbers, steps, onAction, signOff }: ActionBarProps) {
  const [pagesOpen, setPagesOpen] = useState(false);
  const [reread, setReread] = useState<Reread>({ busy: false, message: null, error: null });
  const pagesStep = steps.find((s) => s.id === "pages");
  const signHelp = steps.find((s) => s.id === "sign")?.detail ?? null;

  const press = (step: ActionStep) => {
    if (step.id === "sign") { void signOff.sign(); return; }
    if (step.id === "pages") setPagesOpen((open) => !open);
    onAction(step.id);
  };

  const readAgain = async () => {
    setReread({ busy: true, message: null, error: null });
    const result = await reviewsApi.rereadPages(run.submittal_document_id);
    if (!result.ok) { setReread({ busy: false, message: null, error: result.error.message }); return; }
    setReread({
      busy: false, error: null,
      message: "Asked to read these pages again. Run the review again to use what was read.",
    });
  };

  return (
    <section role="region" aria-label="What you need to do" data-testid="ws-action-bar"
      className="space-y-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">What you need to do</h2>
      <p data-testid="ws-verdict" className="text-base text-slateish-100">
        {verdictPieces(numbers).map((piece, i) => (piece.count
          ? <span key={i} data-count={piece.count}>{piece.text}</span>
          : <span key={i}>{piece.text}</span>))}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {steps.map((step) => (
          <button
            key={step.id} type="button" data-step={step.id} data-done={step.done ? "true" : "false"}
            disabled={!step.enabled || signOff.busy}
            aria-expanded={step.id === "pages" && step.enabled ? pagesOpen : undefined}
            title={step.id === "sign" && step.detail ? step.detail : undefined}
            onClick={() => press(step)}
            className={`${BUTTON} ${step.id === "sign"
              ? (step.enabled ? "border-signal-500 bg-signal-500 text-ink-950" : "border-ink-700 text-slateish-500")
              : step.done ? "border-ink-700 text-slateish-500" : "border-ink-600 text-slateish-100"} ${step.id === "sign" ? "ml-auto" : ""}`}
          >
            {step.done && step.id !== "sign" && <span aria-label="done">{"✓"}</span>}
            <StepLabel step={step} />
          </button>
        ))}
      </div>
      {signHelp && <p data-testid="ws-sign-waits" className="text-sm text-slateish-300">{signHelp}</p>}
      {pagesOpen && pagesStep && !pagesStep.done && (
        <div data-testid="ws-unread-pages" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
          {pagesStep.count === null && pagesStep.detail ? (
            <span data-testid="ws-page-record-missing">
              {pagesStep.detail} Look through the pages yourself, or ask for the pages to be read again.
            </span>
          ) : pagesStep.count === null ? (
            <span>
              The page checks cannot be read yet, so it is not known which pages were left unread. Look through
              the pages yourself, or ask for the pages to be read again.
            </span>
          ) : (
            <span>
              {pagesStep.detail}. Tick each page you checked yourself in &quot;Before you sign&quot; under the sheet,
              or ask for the pages to be read again.
            </span>
          )}
          <button type="button" disabled={reread.busy} onClick={() => void readAgain()}
            className={`${BUTTON} border-ink-600 text-slateish-100`}>
            {reread.busy ? "Reading..." : "Read these pages again"}
          </button>
        </div>
      )}
      {reread.message && <p role="status" className="text-sm text-slateish-300">{reread.message}</p>}
      {reread.error && <p role="alert" className="text-sm text-red-400">{reread.error}</p>}
      {signOff.message && <p role="status" className="text-sm text-slateish-300">{signOff.message}</p>}
      {signOff.error && <p role="alert" className="text-sm text-red-400">{signOff.error}</p>}
    </section>
  );
}
