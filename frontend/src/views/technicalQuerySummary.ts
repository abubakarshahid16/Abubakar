/**
 * THE ONE-LINE PLAIN SUMMARY OF A QUERY (owner, 26 Nov 2026, E5: "a one-line plain summary on every result"): where the query stands
 * and the next thing to do, in everyday words, from the query's own fields. Never a claim the fields do not hold: no draft is "no
 * answer written yet", a quote not kept is "found", not "evidence".
 */
export interface QueryForSummary {
  status: string;
  confirmed_question?: string | null;
  proposed_question?: string | null;
  drafts?: unknown[] | null;
  evidence?: { evidence_state?: string | null; for_current_question?: boolean | null }[] | null;
  due_at?: string | null;
}

const STAGE: Record<string, string> = {
  received: "New",
  triage: "Being sorted",
  drafting: "Being answered",
  awaiting_review: "Answer waiting for an engineer's approval",
  changes_requested: "Answer sent back for changes",
  approved: "Answer approved, not sent yet",
  send_pending: "Answer being sent",
  sent: "Answer sent",
  awaiting_confirmation: "Answer sent, waiting for the contractor to confirm",
  resolved: "Closed: answered and confirmed",
  duplicate: "Closed as a duplicate",
  cancelled: "Cancelled",
  failed: "Stopped by an error",
};

const CLOSED = new Set(["resolved", "duplicate", "cancelled"]);

export function querySummary(q: QueryForSummary, today: string = new Date().toISOString().slice(0, 10)): string {
  const parts = [STAGE[q.status] ?? q.status.replaceAll("_", " ")];
  if (!CLOSED.has(q.status)) {
    // the sources for the current wording only (ones found for an earlier wording are folded apart: builder A)
    const current = (q.evidence ?? []).filter((e) => e.for_current_question !== false);
    const kept = current.filter((e) => e.evidence_state === "verified").length;
    const found = current.length;
    if (!q.confirmed_question) parts.push(q.proposed_question ? "the question is proposed, not confirmed yet" : "no question yet");
    parts.push(found ? `${kept} of ${found} quote${found === 1 ? "" : "s"} found kept as evidence` : "no evidence found yet");
    parts.push(q.drafts?.length ? "an answer is written" : "no answer written yet");
    const due = (q.due_at ?? "").slice(0, 10);
    if (due) parts.push(due < today ? `late: it was due on ${due}` : `due on ${due}`);
  }
  return `${parts[0]}${parts.length > 1 ? `: ${parts.slice(1).join("; ")}` : ""}.`;
}
