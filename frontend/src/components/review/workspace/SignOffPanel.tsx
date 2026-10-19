/**
 * OWNER: builder C (v2.1; builder B before). Sign-off under the comment sheet: the comment sheet's
 * own "Before you sign" box (record the final code, tick each unread page,
 * the items still open; crs/BeforeYouSign.tsx over the same issue gate),
 * then what is left, what is not saved, and Save / Sign and export /
 * Working copy. Sign and export opens the "Preview and confirm" step
 * (useSignOff.sign; workspace/sign/SignConfirm.tsx); nothing is issued from
 * this panel directly. Counts come from `computeReviewNumbers`, the Sign rule from
 * `actionSteps` (the same rule as the bar, which waits for the issue gate
 * too). Messages from saving and signing show in the ActionBar, which stays
 * on screen on every tab.
 */
import { BeforeYouSign } from "../crs/BeforeYouSign";
import type { SignOffPanelProps } from "./contract";
import { actionSteps, signedDate } from "./numbers";

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed";

export function SignOffPanel({ numbers, signOff, run, rows, gate, onRunChanged, onJump }: SignOffPanelProps) {
  const signStep = actionSteps(numbers).find((s) => s.id === "sign");
  const canSign = Boolean(signStep?.enabled) && !signOff.busy;
  const when = signedDate(numbers.signedAt);
  return (
    <section data-testid="ws-sign-off" aria-label="Sign-off"
      className="mt-4 space-y-3 rounded-[var(--radius-md)] border border-ink-700 p-3 text-sm text-slateish-300">
      <h3 className="sr-only">Sign-off</h3>
      {!numbers.signed && (
        <BeforeYouSign run={run} rows={rows} state={gate} onRunChanged={onRunChanged} onJump={onJump} />
      )}
      <div className="flex flex-wrap items-center gap-3">
        {numbers.signed ? (
          <span>{when ? `Signed on ${when}.` : "Signed."}</span>
        ) : (
          <span>
            <span data-count="undecided">{numbers.undecided.toLocaleString()}</span> of{" "}
            <span data-count="comments">{numbers.comments.toLocaleString()}</span>{" "}
            {numbers.comments === 1 ? "comment" : "comments"} left to decide
            {" · "}
            <span data-unsaved>{numbers.unsaved.toLocaleString()}</span> not saved
            {numbers.unopenedNeedsYou > 0 && (
              <>
                {" · "}Sign and export waits until you have opened the {numbers.unopenedNeedsYou.toLocaleString()}{" "}
                {numbers.unopenedNeedsYou === 1 ? "comment that needs" : "comments that need"} your judgement (marked &quot;Needs you&quot;).
              </>
            )}
          </span>
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          <button type="button" disabled={numbers.unsaved === 0 || signOff.busy} onClick={() => void signOff.save()}
            className={`${BUTTON} border-ink-600 text-slateish-100`}>
            Save decisions
          </button>
          <button type="button" disabled={signOff.busy || numbers.unsaved > 0} onClick={() => void signOff.workingCopy()}
            aria-describedby={numbers.unsaved > 0 ? "ws-working-copy-waits" : undefined}
            className={`${BUTTON} border-ink-600 text-slateish-100`}>
            Download working copy
          </button>
          <button type="button" disabled={!canSign} onClick={() => void signOff.sign()} title={signStep?.detail}
            className={`${BUTTON} ${canSign ? "border-signal-500 bg-signal-500 text-ink-950" : "border-ink-700 text-slateish-500"}`}>
            {numbers.signed ? "Signed" : "Sign and export"}
          </button>
        </div>
      </div>
      {/* The working copy is built from what is saved, so a copy taken now
          would leave out the decisions on screen. */}
      {numbers.unsaved > 0 && (
        <p id="ws-working-copy-waits" data-testid="ws-working-copy-waits" className="text-slateish-400">
          Save your decisions first: the working copy only has what is saved.
        </p>
      )}
    </section>
  );
}
