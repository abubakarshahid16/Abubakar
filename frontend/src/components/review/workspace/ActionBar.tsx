/**
 * OWNER: builder B (v2.2: builder C). "What you need to do": the verdict in
 * one sentence and the numbered steps in fixed order (standards, pages,
 * decide, final code, Preview CRS, sign), the saving line with "Save now", and the final code control that
 * opens from the bar. "Preview CRS" opens the read-only look at the sheet
 * (sign/CrsLook) under the bar; it issues nothing. Every number here comes from `computeReviewNumbers` /
 * `actionSteps`; this file counts nothing itself.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import { FinalCode } from "../crs/BeforeYouSign";
import type { ActionBarProps, ActionStep, ActionStepId, AutosaveStatus } from "./contract";
import { verdictPieces } from "./numbers";
import { type PlainError, plainError } from "./plainError";
import { PlainErrorLine } from "./PlainErrorLine";
import { CrsLook } from "./sign/CrsLook";

/** The data-count name of each step's number (the shared counts). */
const STEP_COUNT: Record<Exclude<ActionStepId, "sign" | "code" | "preview">, "missingStandards" | "unreadPages" | "undecided"> = {
  standards: "missingStandards",
  pages: "unreadPages",
  decide: "undecided",
};

const BUTTON = "inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed";

function StepLabel({ step }: { step: ActionStep }) {
  if (step.id === "sign" || step.id === "code" || step.id === "preview" || step.count === null) return <>{step.label}</>;
  // The label carries "(N)"; N is shown from `step.count` so it can be marked.
  const words = step.label.replace(/\s*\(\d[\d,]*\)\s*$/, "");
  // One span: the button is a flex box, and loose text pieces would each
  // get the flex gap ("Decide comments ( 4 )").
  return (
    <span data-testid="ws-step-label">
      {words} (<span data-count={STEP_COUNT[step.id]}>{step.count.toLocaleString()}</span>)
    </span>
  );
}

type Reread = { busy: boolean; message: string | null; error: PlainError | null };

/** Order 141 D: "Saved" when decisions were taken off unsaved this visit
 *  (their comment left the sheet): never "every decision". */
function savedWords(dropped: number): string {
  if (dropped <= 0) return "Saved. Every decision is on the record.";
  return dropped === 1
    ? "Saved, except 1 decision that was taken off because its comment is no longer on the sheet. Decide that comment again."
    : `Saved, except ${dropped} decisions that were taken off because their comments are no longer on the sheet. Decide those comments again.`;
}

/** D4: the one saving line. "Saved" only after something was saved; a
 *  failure says why in plain words and stays until a save works. */
function SavingLine({ autosave, unsaved }: { autosave: AutosaveStatus; unsaved: number }) {
  const words = autosave.phase === "saving" ? "Saving..."
    : autosave.phase === "failed" ? (autosave.message ?? "Your decisions were not saved. Try again in a moment.")
      : unsaved > 0 && autosave.waiting ? `${unsaved} ${unsaved === 1 ? "decision" : "decisions"} will save once Undo is gone.`
        : unsaved > 0 ? `${unsaved} ${unsaved === 1 ? "decision" : "decisions"} waiting to save...`
          : autosave.phase === "saved" ? savedWords(autosave.dropped ?? 0) : "Decisions save by themselves as you make them.";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <p role="status" data-testid="ws-autosave" data-phase={autosave.phase}
        className={autosave.phase === "failed" ? "text-red-400" : "text-slateish-300"}>
        {words}
      </p>
      {autosave.phase === "failed" && autosave.detail && (
        <details data-testid="ws-autosave-detail" className="text-xs text-slateish-400">
          <summary className="cursor-pointer">Details</summary>
          <p className="mt-1 break-words">{autosave.detail}</p>
        </details>
      )}
      <button type="button" disabled={unsaved === 0 || autosave.phase === "saving"} onClick={() => void autosave.saveNow()}
        className={`${BUTTON} border-ink-600 text-slateish-100`}>
        Save now
      </button>
    </div>
  );
}

export function ActionBar({ run, numbers, steps, onAction, signOff, autosave, onCodeRecorded }: ActionBarProps) {
  const [pagesOpen, setPagesOpen] = useState(false);
  const [codeOpen, setCodeOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  // #1171 review, item 7: each finished save makes the open preview read the
  // sheet again, so it never shows the sheet from before the save. Adjusted
  // during render when the phase changes (no effect, no extra render pass).
  const [seenPhase, setSeenPhase] = useState(autosave?.phase);
  const [saves, setSaves] = useState(0);
  if (autosave?.phase !== seenPhase) {
    setSeenPhase(autosave?.phase);
    if (autosave?.phase === "saved") setSaves((n) => n + 1);
  }
  const [reread, setReread] = useState<Reread>({ busy: false, message: null, error: null });
  const pagesStep = steps.find((s) => s.id === "pages");
  const signHelp = steps.find((s) => s.id === "sign")?.detail ?? null;

  const press = (step: ActionStep) => {
    if (step.id === "sign") { void signOff.sign(); return; }
    if (step.id === "pages") setPagesOpen((open) => !open);
    if (step.id === "code") setCodeOpen((open) => !open);
    if (step.id === "preview") setPreviewOpen((open) => !open);
    onAction(step.id);
  };

  const readAgain = async () => {
    setReread({ busy: true, message: null, error: null });
    const result = await reviewsApi.rereadPages(run.submittal_document_id);
    if (!result.ok) {
      setReread({ busy: false, message: null, error: plainError("The pages could not be sent to be read again.", result) });
      return;
    }
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
      {/* v2.2 round 2: all six steps in one wrapping row, Sign last and drawn
          as the main button. No ml-auto: it pushed Sign alone onto its own
          line on screens up to 1440px wide. */}
      <ol aria-label="Steps, in order" className="flex flex-wrap items-center gap-2">
        {steps.map((step, i) => (
          <li key={step.id} data-step-item={step.id} className="flex items-center gap-1">
            {/* The step number is drawn beside the button, not in its name:
                the list already says the order to a screen reader. */}
            <span aria-hidden="true" data-step-number={i + 1}
              className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold ${step.done
                ? "bg-ink-700 text-slateish-500" : "bg-ink-600 text-slateish-100"}`}>
              {i + 1}
            </span>
            <button
              type="button" data-step={step.id} data-done={step.done ? "true" : "false"}
              disabled={!step.enabled || signOff.busy}
              aria-expanded={step.id === "pages" && step.enabled ? pagesOpen
                : step.id === "code" && step.enabled ? codeOpen
                  : step.id === "preview" && step.enabled ? previewOpen : undefined}
              title={step.id === "sign" && step.detail ? step.detail : undefined}
              onClick={() => press(step)}
              className={`${BUTTON} ${step.id === "sign"
                ? `font-semibold ${step.enabled ? "border-signal-500 bg-signal-500 text-ink-950" : "border-signal-500/60 text-slateish-400"}`
                : step.done ? "border-ink-700 text-slateish-500" : "border-ink-600 text-slateish-100"}`}
            >
              {step.done && step.id !== "sign" && <span aria-label="done">{"✓"}</span>}
              <StepLabel step={step} />
            </button>
          </li>
        ))}
      </ol>
      {signHelp && <p data-testid="ws-sign-waits" className="text-sm text-slateish-300">{signHelp}</p>}
      {pagesOpen && pagesStep && !pagesStep.done && (
        <div data-testid="ws-unread-pages" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
          {pagesStep.count === null && pagesStep.detail ? (
            <span data-testid="ws-page-record-missing">
              {pagesStep.detail} Look through the pages yourself, or ask for the pages to be read again.
            </span>
          ) : pagesStep.count === null ? (
            <span>
              It is not known yet which pages were left unread. Look through the pages yourself, or ask for the
              pages to be read again.
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
      {codeOpen && !numbers.signed && numbers.finalCodeRecorded !== true && (
        <div data-testid="ws-final-code">
          <FinalCode run={run} onChanged={() => { setCodeOpen(false); onCodeRecorded?.(); }} />
        </div>
      )}
      {previewOpen && (
        <div role="group" aria-label="Preview of the comment sheet" data-testid="ws-crs-preview"
          className="space-y-2 rounded-[var(--radius-sm)] border border-ink-700 p-3 text-sm text-slateish-200">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-slateish-300">
              {numbers.signed
                ? "This is the comment sheet as it stands now. It is a look only."
                : "This is the comment sheet as the contractor would get it. It is a look only: nothing is sent."}
            </p>
            <button type="button" onClick={() => setPreviewOpen(false)}
              className={`${BUTTON} border-ink-600 text-slateish-100`}>
              Close preview
            </button>
          </div>
          {!numbers.signed && numbers.unsaved > 0 && (
            <p role="status" className="text-warn-500" data-testid="ws-crs-preview-unsaved">
              {numbers.unsaved === 1
                ? "1 decision is not saved yet, so this preview does not show it. The preview reads the sheet again after each save."
                : `${numbers.unsaved.toLocaleString()} decisions are not saved yet, so this preview does not show them. The preview reads the sheet again after each save.`}
            </p>
          )}
          <CrsLook key={saves} runId={run.review_run_id} errorTestId="ws-crs-preview-error" />
        </div>
      )}
      {autosave && <SavingLine autosave={autosave} unsaved={numbers.unsaved} />}
      {reread.message && <p role="status" className="text-sm text-slateish-300">{reread.message}</p>}
      {reread.error && <PlainErrorLine error={reread.error} testId="ws-reread-error" />}
      {signOff.message && <p role="status" className="text-sm text-slateish-300">{signOff.message}</p>}
      {signOff.error && <p role="alert" className="text-sm text-red-400">{signOff.error}</p>}
    </section>
  );
}
