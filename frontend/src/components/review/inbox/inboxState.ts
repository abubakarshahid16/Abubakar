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
 *   the job or run is queued        -> Queued
 *   the job or run is running       -> Running, step N of M with its name
 *   the run completed               -> Ready
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
  const job = run.job ?? null;
  if (QUEUED.has(status) || (job !== null && QUEUED.has(job.state))) return { kind: "queued" };
  if (status === "running" || job?.state === "running") {
    // `progress_done` is the index of the step now running (0-based), out of
    // `progress_total` named steps; unknown stays unknown, never "step 0".
    const step = isCount(job?.progress_done) ? job!.progress_done! + 1 : null;
    const of = isCount(job?.progress_total) ? job!.progress_total! : null;
    return { kind: "running", step, of, label: job?.progress_label ?? null };
  }
  if (status === "completed") return { kind: "ready" };
  return { kind: "other", status: status || "unknown" };
}

/** The comment counts a Ready run carries once the run summary (order 95
 *  piece 1) is read; null until then, and null renders as nothing. */
export interface ReadyCounts {
  comment: number;
  needs_you: number;
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
      return counts
        ? `Ready: ${counts.comment} comment${counts.comment === 1 ? "" : "s"}, ${counts.needs_you} need${counts.needs_you === 1 ? "s" : ""} you`
        : "Ready";
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
 *  engineer: a finished review not yet signed, a failed one to look at, or a
 *  document nobody has started a review of. */
export function inFilter(state: InboxState, filter: InboxFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "needs_me":
      return state.kind === "ready" || state.kind === "failed" || state.kind === "not_reviewed";
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
