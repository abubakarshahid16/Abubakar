/**
 * OWNER: builder B. Sign-off under the comment sheet: what is left, what is
 * not saved, and Save / Sign and export / Working copy. Counts come from
 * `computeReviewNumbers`, the Sign rule from `actionSteps` (the same rule as
 * the bar). Messages from saving and signing show in the ActionBar, which
 * stays on screen on every tab.
 */
import type { SignOffPanelProps } from "./contract";
import { actionSteps, signedDate } from "./numbers";

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed";

export function SignOffPanel({ numbers, signOff }: SignOffPanelProps) {
  const signStep = actionSteps(numbers).find((s) => s.id === "sign");
  const canSign = Boolean(signStep?.enabled) && !signOff.busy;
  const when = signedDate(numbers.signedAt);
  return (
    <section data-testid="ws-sign-off" aria-label="Sign-off"
      className="mt-4 flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-ink-700 p-3 text-sm text-slateish-300">
      <h3 className="sr-only">Sign-off</h3>
      {numbers.signed ? (
        <span>{when ? `Signed on ${when}.` : "Signed."}</span>
      ) : (
        <span>
          <span data-count="undecided">{numbers.undecided.toLocaleString()}</span> of{" "}
          <span data-count="comments">{numbers.comments.toLocaleString()}</span>{" "}
          {numbers.comments === 1 ? "comment" : "comments"} left to decide
          {" · "}
          <span data-unsaved>{numbers.unsaved.toLocaleString()}</span> not saved
        </span>
      )}
      <div className="ml-auto flex flex-wrap gap-2">
        <button type="button" disabled={numbers.unsaved === 0 || signOff.busy} onClick={() => void signOff.save()}
          className={`${BUTTON} border-ink-600 text-slateish-100`}>
          Save decisions
        </button>
        <button type="button" disabled={signOff.busy} onClick={() => void signOff.workingCopy()}
          className={`${BUTTON} border-ink-600 text-slateish-100`}>
          Download working copy
        </button>
        <button type="button" disabled={!canSign} onClick={() => void signOff.sign()}
          className={`${BUTTON} ${canSign ? "border-signal-500 bg-signal-500 text-ink-950" : "border-ink-700 text-slateish-500"}`}>
          {numbers.signed ? "Signed" : "Sign and export"}
        </button>
      </div>
    </section>
  );
}
