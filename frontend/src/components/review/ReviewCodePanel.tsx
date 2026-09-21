/**
 * The recommended code, and the engineer's decision about it.
 *
 * MASTER PLAN SECTION 15: the AI performs the review and recommends a code;
 * the engineer's final action is governance, not the initial review. Both are
 * shown, side by side, and the recommendation is never replaced by the
 * decision - a screen that showed only the final code would be hiding what
 * the machine actually said, which is the one thing an auditor asks for.
 *
 * A REASON IS REQUIRED WHEN THE TWO DIFFER. The rule is enforced by the
 * server; this form asks for it up front so the refusal is not the first the
 * reader hears of it.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type { ReviewRunSummary } from "../../types/api";
import { REVIEW_CODES } from "../../types/api";
import { whenLabel } from "./reviewFormat";

export interface ReviewCodePanelProps {
  run: ReviewRunSummary;
  onDecided: () => void;
}

type State =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "error"; message: string };

export function ReviewCodePanel({ run, onDecided }: ReviewCodePanelProps) {
  const [code, setCode] = useState<string>(
    run.engineer_final_code ?? run.recommended_code ?? "");
  const [reason, setReason] = useState(run.override_reason ?? "");
  const [state, setState] = useState<State>({ kind: "idle" });

  const differs = Boolean(
    run.recommended_code && code && code !== run.recommended_code);

  async function save() {
    if (differs && !reason.trim()) {
      setState({
        kind: "error",
        message: "A reason is required when the final code differs from the "
          + "recommendation.",
      });
      return;
    }
    setState({ kind: "saving" });
    const result = await reviewsApi.decideCode(
      run.review_run_id, code, reason.trim() || null);
    if (!result.ok) {
      setState({ kind: "error", message: result.error.message });
      return;
    }
    setState({ kind: "idle" });
    onDecided();
  }

  return (
    <section
      aria-labelledby="review-code-title"
      className="space-y-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
    >
      <h3 id="review-code-title" className="text-sm font-semibold text-slateish-200">
        Review code
      </h3>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 p-3">
          <p className="text-xs uppercase tracking-wide text-slateish-400">
            Recommended by the system
          </p>
          <p className="mt-1 font-semibold text-slateish-100">
            {run.recommended_code ?? "—"}
          </p>
          {/* VERBATIM. The recommendation's own sentence, including the
              nominal-estimate note, because that sentence is the evidence
              for the code beside it. */}
          {run.recommended_reason && (
            <p className="mt-1 text-xs text-slateish-400">{run.recommended_reason}</p>
          )}
        </div>

        <div className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 p-3">
          <p className="text-xs uppercase tracking-wide text-slateish-400">
            Engineer's final code
          </p>
          {run.engineer_final_code ? (
            <>
              <p className="mt-1 font-semibold text-emerald-200">
                {run.engineer_final_code}
              </p>
              {/* THE NAME, NOT THE PRIMARY KEY. This printed `decided by
                  user_phase6_demo`, which asks an engineer to recognise their
                  own row id. The id stays - it is what the audit trail and
                  the foreign key hold - but in the tooltip, where somebody
                  who needs it can find it and nobody else has to read it.
                  With no name (the user row is gone) the id is all that is
                  known, and showing it is more honest than showing nothing. */}
              <p className="mt-1 text-xs text-slateish-400">
                {run.decided_by ? (
                  <>
                    {"decided by "}
                    <span title={run.decided_by}>
                      {run.decided_by_name || run.decided_by}
                    </span>
                  </>
                ) : "decided"}
                {run.decided_at ? ` on ${whenLabel(run.decided_at)}` : ""}
              </p>
              {run.override_reason && (
                <p className="mt-1 text-xs text-slateish-300">
                  Override reason: {run.override_reason}
                </p>
              )}
            </>
          ) : (
            <p className="mt-1 text-sm text-slateish-400">
              Not decided yet.
            </p>
          )}
        </div>
      </div>

      <div className="space-y-2 border-t border-ink-700 pt-3">
        <label className="block text-xs text-slateish-400" htmlFor="final-code">
          {run.engineer_final_code ? "Change the final code" : "Set the final code"}
        </label>
        <select
          id="final-code" value={code}
          onChange={(event) => setCode(event.target.value)}
          className="min-w-[18rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
        >
          <option value="">Choose a code…</option>
          {REVIEW_CODES.map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </select>

        {differs && (
          <div>
            <label className="block text-xs text-slateish-400" htmlFor="override-reason">
              This differs from the recommendation — say why (required)
            </label>
            <textarea
              id="override-reason" rows={2} value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. both open items are lookup tables an engineer has now read; neither is a breach"
              className="mt-1 w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
            />
          </div>
        )}

        <button
          type="button" onClick={() => void save()}
          disabled={!code || state.kind === "saving"}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
        >
          {state.kind === "saving" ? "Saving…" : "Record final code"}
        </button>

        {state.kind === "error" && (
          <p role="alert" className="rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {state.message}
          </p>
        )}

        {run.engineer_final_code && (
          <p className="text-xs text-slateish-500">
            This run carries a decision, so re-running it is refused — a new
            review starts a new run rather than rewriting the one the decision
            was made about.
          </p>
        )}
      </div>
    </section>
  );
}
