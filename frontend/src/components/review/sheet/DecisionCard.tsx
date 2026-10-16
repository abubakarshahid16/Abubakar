/**
 * "What is your overall decision?" - the last card on the Sheet screen.
 *
 * The four review codes as plain choices, the system's recommendation marked
 * "suggested", and a reason required when the choice differs (the server
 * enforces the same rule; asking first means its refusal is not news).
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewRunSummary } from "../../../types/api";
import { REVIEW_CODES } from "../../../types/api";

/** One sentence per default code. A configured code with no sentence here
 *  shows its own name only - never an invented explanation. */
const CODE_WORDS: Record<string, string> = {
  "Approved": "Everything checked meets the standard; the contractor may go ahead.",
  "Approved with Comments": "The contractor may go ahead and must answer our comments.",
  "Rejected / Revise and Resubmit": "The contractor must fix the comments and send it again.",
  "Manual Review Required": "Not decided here; it needs a fuller engineering review.",
};

export function DecisionCard({ run, onDecided }: { run: ReviewRunSummary; onDecided: () => void }) {
  const codes: readonly string[] = run.review_codes?.length ? run.review_codes : REVIEW_CODES;
  const [code, setCode] = useState(run.engineer_final_code ?? "");
  const [why, setWhy] = useState(run.override_reason ?? "");
  const [state, setState] = useState<{ kind: "idle" | "saving" } | { kind: "error"; message: string }>({ kind: "idle" });
  const differs = Boolean(run.recommended_code && code && code !== run.recommended_code);
  const unchanged = code === (run.engineer_final_code ?? "") && why === (run.override_reason ?? "");

  async function save() {
    if (differs && !why.trim()) {
      setState({ kind: "error", message: "Say why your decision differs from the suggested one." });
      return;
    }
    setState({ kind: "saving" });
    const result = await reviewsApi.decideCode(run.review_run_id, code, why.trim() || null);
    if (!result.ok) { setState({ kind: "error", message: result.error.message }); return; }
    setState({ kind: "idle" });
    onDecided();
  }

  return (
    <section aria-labelledby="decision-title" className="space-y-3 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <h3 id="decision-title" className="text-base font-semibold text-slateish-100">What is your overall decision?</h3>
      <fieldset className="space-y-2">
        <legend className="sr-only">Review code</legend>
        {codes.map((value) => (
          <label key={value} className={`flex cursor-pointer gap-3 rounded-[var(--radius-sm)] border p-3 ${code === value ? "border-signal-500" : "border-ink-700"}`}>
            <input type="radio" name={`code-${run.review_run_id}`} value={value} checked={code === value}
              onChange={() => setCode(value)} className="mt-1" />
            <span className="text-sm">
              <span className="font-medium text-slateish-100">{value}</span>
              {value === run.recommended_code && (
                <span className="ml-2 rounded-full border border-signal-500/50 px-2 py-0.5 text-xs text-signal-300">suggested</span>
              )}
              {CODE_WORDS[value] && <span className="block text-slateish-400">{CODE_WORDS[value]}</span>}
            </span>
          </label>
        ))}
      </fieldset>
      {differs && (
        <div>
          <label htmlFor={`why-code-${run.review_run_id}`} className="block text-xs text-slateish-400">
            Say why (required, because it differs from the suggested decision)
          </label>
          <textarea id={`why-code-${run.review_run_id}`} rows={2} value={why} onChange={(e) => setWhy(e.target.value)}
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100" />
        </div>
      )}
      <button type="button" onClick={() => void save()} disabled={!code || unchanged || state.kind === "saving"}
        className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50">
        {state.kind === "saving" ? "Saving…" : run.engineer_final_code ? "Change my decision" : "Record my decision"}
      </button>
      {!code && <p className="text-xs text-slateish-400">Choose one of the decisions above first.</p>}
      {run.engineer_final_code && unchanged && (
        <p className="text-xs text-slateish-400">Recorded: {run.engineer_final_code}.</p>
      )}
      {state.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
          {state.message}
        </p>
      )}
    </section>
  );
}
