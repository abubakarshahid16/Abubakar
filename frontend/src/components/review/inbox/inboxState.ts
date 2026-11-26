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
import { progressLine, whenLabel } from "../reviewFormat";
import { shown } from "../progress/reviewProgress";

export type InboxState =
  | { kind: "not_reviewed" }
  | { kind: "queued" }
  | { kind: "running"; step: number | null; of: number | null; label: string | null; words: string | null }
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
  // ONE rule with the review's own page (`ReviewWorkspace`): only the RUN's status says "waiting"; a running run whose job row still reads
  // queued is shown by the same step line and clock as its page (a list that said "Waiting to start" beside a page on step 3 was the fault).
  if (QUEUED.has(status) || (status !== "running" && job !== null && QUEUED.has(job.state))) return { kind: "queued" };
  if (status === "running" || job?.state === "running") {
    // `progress_done` is the index of the step now running (0-based), out of `progress_total` named steps; unknown stays unknown, never
    // "step 0". The words are the page's own (`progressLine`), the clock the page's own (`shown`): both from the job, never two sources.
    const of = isCount(job?.progress_total) ? job!.progress_total! : null;
    const known = isCount(job?.progress_done) || of !== null || job?.progress_label != null;
    const next = isCount(job?.progress_done) ? job!.progress_done! + 1 : null;
    const step = next !== null ? (of !== null ? Math.min(next, of) : next) : null;
    const clock = job?.progress_detail ? shown(job.progress_detail).elapsed : null;
    const words = known && job ? progressLine(job.progress_done, job.progress_total, job.progress_label) : null;
    return { kind: "running", step, of: step === null ? null : of, label: job?.progress_label ?? null, words: words && clock ? `${words} · ${clock}` : words };
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
  /** Findings in a comment or needs-you tier (not Met, not removed). Null for a general review: it has no tiers. */
  findings: number | null;
  /** Of those, the ones that need the engineer's judgement. Null for a general review. */
  needs_you: number | null;
  /** Order 14: a general review's OWN numbers (the server's `general` counts); present only for a run of that method. */
  general?: GeneralRunCounts;
  /** Order 14: the lines the earlier AI reviewer stored for this run (they are not findings); absent when it stored none. */
  aiLines?: number;
}

/** A general review's numbers: the points it reviewed, the comments it sent, the confirmations held back (absent when not counted). */
export interface GeneralRunCounts {
  points: number;
  comments: number;
  confirmations?: number | null;
  stopped?: boolean;
}

/** "General review: 129 points reviewed, 66 comments sent (20 confirmations not sent)": the new method's own numbers, labelled as
 *  such; a count not known is left out (never 0). */
export function generalLine(g: GeneralRunCounts): string {
  const n = (x: number) => x.toLocaleString("en-US");
  const plural = (x: number, word: string) => `${n(x)} ${word}${x === 1 ? "" : "s"}`;
  const held = typeof g.confirmations === "number" ? ` (${plural(g.confirmations, "confirmation")} not sent)` : "";
  const early = g.stopped ? "; stopped early" : "";
  return `General review: ${plural(g.points, "point")} reviewed, ${plural(g.comments, "comment")} sent${held}${early}`;
}

/** "Found by the review: 12 findings, 3 needing your judgement": the
 *  server's per-run TOTALS, said as what the review found (not what is left
 *  to decide), and as findings (the sheet groups them into fewer comment
 *  lines). Nothing when not known. The inbox and the landing both use it. */
export function foundLine(counts: ReadyCounts | null | undefined): string {
  if (!counts) return "";
  if (counts.general) return generalLine(counts.general);
  const n = counts.findings;
  const m = counts.needs_you;
  const tiers = n == null || m == null ? "" : `Found by the review: ${n.toLocaleString("en-US")} finding${n === 1 ? "" : "s"}, `
    + `${m.toLocaleString("en-US")} needing your judgement`;
  if (counts.aiLines) {
    // the earlier AI reviewer keeps its lines apart from the findings: say them, and the findings only when there are some
    const ai = `AI review: ${counts.aiLines.toLocaleString("en-US")} line${counts.aiLines === 1 ? "" : "s"} (earlier method)`;
    return n && tiers ? `${ai}. ${tiers}` : ai;
  }
  if (n == null || m == null) return ""; // a count not known renders as nothing, never 0
  return `Found by the review: ${n.toLocaleString("en-US")} finding${n === 1 ? "" : "s"}, `
    + `${m.toLocaleString("en-US")} needing your judgement`;
}

export function stateLabel(state: InboxState, counts: ReadyCounts | null = null): string {
  switch (state.kind) {
    case "not_reviewed":
      return "Not reviewed";
    case "queued":
      return "Queued";
    case "running":
      return state.words ? `Running: ${state.words}` : "Running";
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
