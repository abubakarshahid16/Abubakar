/** #1494: the numbers behind the running review's progress block. Pure, so the
 *  thresholds are tested without a clock. Every figure comes from the job's
 *  `progress_detail` (server clock); nothing here invents a denominator. */
import type { ReviewProgressDetail } from "../../../types/api";

/** Pages that must be finished before a time-left estimate is shown. */
export const ESTIMATE_MIN_PAGES = 3;

/** Clauses that must be finished before a clause-step estimate is shown. */
export const ESTIMATE_MIN_CLAUSES = 3;

export interface Shown {
  percent: number | null;
  pagesLine: string | null;
  clausesLine: string | null;
  elapsed: string | null;
  estimate: string | null;
  stall: { level: "amber" | "red"; text: string } | null;
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

function minutes(seconds: number): string {
  return `${Math.max(1, Math.floor(seconds / 60))} min`;
}

/** `extra` is whole seconds passed since the detail was received. */
export function shown(d: ReviewProgressDetail, extra = 0): Shown {
  const done = d.pages_done, total = d.pages_total;
  // A Word file has no pages: the server reads it in parts (the live review).
  const unit = d.pages_unit === "part" ? "part" : "page";
  const hasPages = typeof done === "number" && typeof total === "number" && total > 0;
  const cDone = d.clauses_done, cTotal = d.clauses_total;
  const hasClauses = typeof cDone === "number" && typeof cTotal === "number" && cTotal > 0;
  const cElapsed = typeof d.clauses_elapsed_seconds === "number" ? d.clauses_elapsed_seconds + extra : null;
  const elapsedS = typeof d.elapsed_seconds === "number" ? d.elapsed_seconds + extra : null;
  let estimate: string | null = null;
  if (hasPages && elapsedS !== null && elapsedS > 0 && done >= ESTIMATE_MIN_PAGES && done < total) {
    const left = (elapsedS / done) * (total - done);
    estimate = `about ${minutes(left)} left reading ${unit}s (estimate, from the ${unit}s done so far)`;
  }
  // The clause step's own clock (server: since its first clause). Unknown -> hidden.
  if (hasClauses && cElapsed !== null && cElapsed > 0 && cDone >= ESTIMATE_MIN_CLAUSES && cDone < cTotal) {
    const left = (cElapsed / cDone) * (cTotal - cDone);
    estimate = `about ${minutes(left)} left checking clauses (estimate, from the clauses done so far)`;
  }
  const idle = typeof d.idle_seconds === "number" ? d.idle_seconds + extra : null;
  let stall: Shown["stall"] = null;
  if (d.stale) stall = { level: "red", text: "The run may be stuck; see System Health." };
  else if (idle !== null && idle >= d.stall_amber_seconds) {
    // The threshold is the server's, per step (a model page may take minutes);
    // the line names the sub-step it waits on (the live review: one slow page).
    const still = d.waiting_on ? ` Still ${d.waiting_on}.` : "";
    stall = { level: "amber", text: `No progress for ${minutes(idle)}.${still}` };
  }
  return {
    percent: hasPages
      ? Math.round((done / total) * 100)
      : hasClauses ? Math.round((cDone / cTotal) * 100) : null,
    pagesLine: hasPages ? `${done} of ${total} ${unit}s read` : null,
    clausesLine: hasClauses ? `${cDone} of ${cTotal} clauses checked` : null,
    elapsed: elapsedS !== null ? `Elapsed ${clock(elapsedS)}` : null,
    estimate,
    stall,
  };
}
