/**
 * Order 95 piece 3: where each contractor document stands, in one word the
 * engineer can sort by - Not reviewed / Queued / Running / Ready / Signed /
 * Failed - read from the stored run and its job, never guessed.
 *
 * The rules, first match wins:
 *   no run                          -> Not reviewed
 *   a contractor copy was issued    -> Signed (`crs_issued_at`)
 *   the run failed                  -> Failed, with the stored reason
 *   the run was cancelled           -> Cancelled
 *   the run completed               -> Ready (the run's own end state wins
 *                                      over a job row that has not caught up)
 *   the job or run is queued        -> Queued
 *   the job or run is running       -> Running, step N of M with its name
 *   any other status                -> shown as itself, never Ready
 */
import type { ReviewRunSummary } from "../../../types/api";
import { whenLabel } from "../reviewFormat";

export type InboxState =
  | { kind: "not_reviewed" }
  | { kind: "queued" }
  | { kind: "running"; step: number | null; of: number | null; label: string | null }
  | { kind: "ready" }
  | { kind: "signed"; at: string }
  | { kind: "failed"; reason: string | null }
  | { kind: "cancelled" }
  | { kind: "other"; status: string };

export type InboxFilter = "needs_me" | "in_progress" | "signed" | "not_reviewed" | "all";

/** The chips, in order; "Needs me" is the default (order 95). */
export const FILTERS: readonly { id: InboxFilter; label: string }[] = [
  { id: "needs_me", label: "Needs me" },
  { id: "in_progress", label: "Queued or running" },
  { id: "signed", label: "Signed" },
  { id: "not_reviewed", label: "Not reviewed" },
  { id: "all", label: "All" },
];

const QUEUED = new Set(["queued", "pending", "retrying"]);

function isCount(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function inboxStateOf(run: ReviewRunSummary | undefined): InboxState {
  if (!run) return { kind: "not_reviewed" };
  if (run.crs_issued_at) return { kind: "signed", at: run.crs_issued_at };
  const status = run.status || "";
  if (status === "failed") return { kind: "failed", reason: run.failure_reason ?? null };
  if (status === "cancelled") return { kind: "cancelled" };
  if (status === "completed") return { kind: "ready" };
  const job = run.job ?? null;
  if (QUEUED.has(status) || (job !== null && QUEUED.has(job.state))) return { kind: "queued" };
  if (status === "running" || job?.state === "running") {
    // `progress_done` is the index of the step now running (0-based), out of
    // `progress_total` named steps; unknown stays unknown, never "step 0".
    // A job finishing its last step can read done == total for a moment:
    // no "step 4 of 3" - the step is dropped, the label stays.
    const of = isCount(job?.progress_total) ? job!.progress_total! : null;
    const next = isCount(job?.progress_done) ? job!.progress_done! + 1 : null;
    const step = next !== null && (of === null || next <= of) ? next : null;
    return { kind: "running", step, of: step === null ? null : of, label: job?.progress_label ?? null };
  }
  return { kind: "other", status: status || "unknown" };
}

/** What a Ready run asks of the engineer, once the run summary (order 95
 *  piece 1) is read; null until then, and null renders as nothing.
 *
 *  FINDINGS, NOT COMMENTS (A-1126). The summary counts findings, and the
 *  sheet groups many findings into one comment row ("13 blanks, one
 *  comment"), so calling these "comments" said 6,584 where the sheet shows
 *  5 rows. The label names them as what they are. */
export interface ReadyCounts {
  /** Findings in a comment or needs-you tier (not Met, not removed). */
  findings: number;
  /** Of those, the ones that need the engineer's judgement. */
  needs_you: number;
  /** v2.2: comment-sheet rows still waiting for a decision (Keep / Edit /
   *  Remove), counted by the server the same way the sheet counts them.
   *  Absent or null: not known (an older server) - never shown as 0. */
  undecided?: number | null;
}

/** "Found by the review: 12 findings, 3 needing your judgement": the
 *  server's per-run TOTALS, said as what the review found (not what is left
 *  to decide), and as findings (the sheet groups them into fewer comment
 *  lines). Nothing when not known. The inbox and the landing both use it. */
export function foundLine(counts: ReadyCounts | null | undefined): string {
  if (!counts) return "";
  const n = counts.findings;
  const m = counts.needs_you;
  return `Found by the review: ${n.toLocaleString("en-US")} finding${n === 1 ? "" : "s"}, `
    + `${m.toLocaleString("en-US")} needing your judgement`;
}

export function stateLabel(state: InboxState, counts: ReadyCounts | null = null): string {
  switch (state.kind) {
    case "not_reviewed":
      return "Not reviewed";
    case "queued":
      return "Queued";
    case "running": {
      const where = state.step !== null && state.of !== null ? ` · step ${state.step} of ${state.of}` : "";
      return `Running${where}${state.label ? `: ${state.label}` : ""}`;
    }
    case "ready":
      // v2.1 round 2: the server's counts are what the review FOUND, not
      // what is left to decide (only the comment sheet knows that), so they
      // are said exactly as the landing says them (foundLine).
      return counts ? `Ready. ${foundLine(counts)}` : "Ready";
    case "signed":
      return `Signed · ${whenLabel(state.at)}`;
    case "failed":
      return `Failed: ${state.reason || "no reason was recorded"}`;
    case "cancelled":
      return "Cancelled";
    case "other":
      return state.status;
  }
}

/** Does this document belong under the chip? "Needs me" is what waits on the
 *  engineer: a finished review not yet signed, a failed or cancelled one, a
 *  status this table does not know (shown as itself, so never hidden), or a
 *  document nobody has started a review of. Only Signed, Queued and Running
 *  are left out - nothing waits on the engineer there. */
export function inFilter(state: InboxState, filter: InboxFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "needs_me":
      return state.kind !== "signed" && state.kind !== "queued" && state.kind !== "running";
    case "in_progress":
      return state.kind === "queued" || state.kind === "running";
    case "signed":
      return state.kind === "signed";
    case "not_reviewed":
      return state.kind === "not_reviewed";
  }
}

/** True while any document's review is still moving, so the list re-reads. */
export function anyMoving(states: InboxState[]): boolean {
  return states.some((s) => s.kind === "queued" || s.kind === "running");
}
