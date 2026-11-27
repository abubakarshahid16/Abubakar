/** SPEC 3: the review code box: the proposed code with ONE line of reason, "x of N decided", and where the engineer records the final
 *  code (a reason is asked when it differs from the proposal, as the older panel asks). Order 14: nothing is preselected (the engineer
 *  picks), and an approving code while points are still to decide asks why; the server refuses it without a reason too. */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { PointsListing } from "../../../api/reviewPoints";
import { REVIEW_CODES } from "../../../types/api";
import { reasonLabel, reasonRule } from "../codeReason";
import { Button, LinkButton } from "../../kit/Kit";

export function CodeBox({ listing, onRecorded }: { listing: PointsListing; onRecorded: () => void }) {
  const p = listing.proposed_code;
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<string>(listing.final_code ?? p.code ?? "");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const left = listing.of - listing.decided;
  const rule = reasonRule(code, p.code, left);  // the one rule of every picker (`codeReason`)

  async function save() {
    if (!listing.code_run_id) return;
    if (!code) { setProblem("Choose a code first."); return; }
    if (rule.required && !reason.trim()) {
      setProblem(rule.because === "open" ? `A reason is needed: ${left} of ${listing.of} points are still to decide.` : "A reason is needed when the final code is not the proposed one.");
      return;
    }
    setSaving(true); setProblem(null);
    const r = await reviewsApi.decideCode(listing.code_run_id, code, reason.trim() || null);
    setSaving(false);
    if (!r.ok) { setProblem(r.error.message); return; }
    setOpen(false);
    onRecorded();
  }

  return (
    <section data-testid="v2-code-box" aria-label="Review code" className="space-y-1 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-slateish-100">
          <span className="text-xs uppercase tracking-wide text-slateish-400">Proposed review code · </span>
          <strong data-testid="v2-code-line">{p.line}</strong>
          <span className="ml-2 text-xs text-slateish-400">proposed by the system; you decide</span>
        </p>
        <p data-testid="v2-decided" className="text-sm text-slateish-300">{listing.decided} of {listing.of} decided</p>
      </div>
      <p data-testid="v2-code-reason" className="text-sm text-slateish-300">{p.reason}</p>
      <p className="text-xs text-slateish-400">
        {listing.final_code ? `Recorded final code: ${listing.final_code_words?.team ?? listing.final_code}. ` : "The final code is not recorded yet. "}
        {listing.code_run_id && (
          <LinkButton tone="action" onClick={() => setOpen((v) => !v)}>
            {listing.final_code ? "Change it" : "Record the code"}
          </LinkButton>
        )}
      </p>
      {open && (
        <div className="flex flex-wrap items-end gap-2 pt-1">
          <label className="text-xs text-slateish-300">Final code
            <select value={code} onChange={(e) => setCode(e.target.value)} className="ml-2 rounded border border-ink-500 bg-ink-800 px-2 py-1 text-sm text-slateish-100">
              <option value="" disabled>Choose a code</option>
              {REVIEW_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          {rule.show && (
            <label className="text-xs text-slateish-300">{reasonLabel(rule, "Why it differs")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} className="ml-2 w-72 rounded border border-ink-500 bg-ink-800 px-2 py-1 text-sm text-slateish-100" />
            </label>
          )}
          <Button variant="primary" size="sm" disabled={saving} onClick={() => void save()}>Record final code</Button>
        </div>
      )}
      {problem && <p role="alert" className="text-xs text-danger-500">{problem}</p>}
    </section>
  );
}
