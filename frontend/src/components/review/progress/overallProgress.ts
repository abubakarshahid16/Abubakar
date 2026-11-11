/** One overall bar for the whole review (owner, 3 Nov, live review: the bar went from step 1 at 73% back to step 2 at
 *  36%, step 2 was also called "reading the document", and in step 3 the bar vanished).
 *
 *  Pure, so every rule is tested without a clock. Each of the four steps owns a share of the bar; inside its share the bar
 *  follows that step's own count; a figure the server did not send is null and prints as nothing, never 0. The percentage
 *  is made monotonic by `ProgressTracker`: whatever a poll says, it never goes back. */
import type { ReviewProgressDetail } from "../../../types/api";

/** The share of the bar each step owns, as [from, to] percent. */
export const BANDS: Record<number, [number, number]> = { 1: [0, 40], 2: [40, 55], 3: [55, 90], 4: [90, 100] };

/** Seconds without any movement before the bar turns orange. */
export const NO_PROGRESS_SECONDS = 300;

/** A sub-step slower than this many seconds shows its time so far. */
export const SLOW_SECONDS = 20;

/** Per-unit durations needed before a time-left range is shown. */
export const RANGE_MIN_SAMPLES = 3;

const NAMES: Record<number, string> = {
  1: "reading the pages",
  2: "reading pages again for the standards they name",
  3: "comparing requirements",
  4: "writing the review sheet",
};

export function stepName(step: number, total = 4): string {
  return `Step ${step} of ${total}: ${NAMES[step] ?? "working"}`;
}

const num = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);

/** How far through ITS OWN step the review is (0 to 1), or null when the step is unknown. A step whose count is not
 *  reported yet is at its start (0): the bar claims no progress it cannot show. */
export function stepFraction(d: ReviewProgressDetail): number | null {
  if (!num(d.step)) return null;
  const frac = (done: number | null | undefined, total: number | null | undefined) =>
    num(done) && num(total) && total > 0 ? Math.min(1, Math.max(0, done / total)) : 0;
  if (d.step === 3) return frac(d.requirements_done, d.requirements_total);
  if (d.step === 4) return frac(d.clauses_done, d.clauses_total);
  return frac(d.pages_done, d.pages_total); // steps 1 and 2 count pages (or parts)
}

/** The overall percent (0 to 100, whole number) from the step and its count; null when the step is unknown. */
export function overallPercent(d: ReviewProgressDetail): number | null {
  const f = stepFraction(d);
  if (f === null || !num(d.step)) return null;
  const band = BANDS[d.step];
  if (!band) return null;
  return Math.round(band[0] + (band[1] - band[0]) * f);
}

/** "1,240 of 5,062 requirements compared", or null when either number is unknown. */
export function requirementsLine(d: ReviewProgressDetail): string | null {
  if (!num(d.requirements_done) || !num(d.requirements_total) || d.requirements_total <= 0) return null;
  const n = (x: number) => x.toLocaleString("en-US");
  return `${n(d.requirements_done)} of ${n(d.requirements_total)} requirements compared`;
}

export function spent(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return s % 60 === 0 ? `${m} min` : `${m} min ${s % 60} s`;
}

/** "page 5, 40 s so far" on a slow sub-step; null when it is not slow or its age is unknown. */
export function slowLine(d: ReviewProgressDetail, extra = 0): string | null {
  if (!num(d.substep_seconds)) return null;
  const secs = d.substep_seconds + extra;
  if (secs < SLOW_SECONDS) return null;
  let what = "this step";
  if ((d.step === 1 || d.step === 2) && num(d.pages_done) && num(d.pages_total)) {
    what = `${d.pages_unit === "part" ? "part" : "page"} ${Math.min(d.pages_done + 1, d.pages_total)}`;
  } else if (d.step === 3 && num(d.requirements_done) && num(d.requirements_total)) {
    what = `requirement ${Math.min(d.requirements_done + 1, d.requirements_total).toLocaleString("en-US")}`;
  }
  return `${what}, ${spent(secs)} so far`;
}

/** Time left in the current step as a range [low, high] seconds, from per-unit durations seen so far. Low uses the
 *  typical (median) unit, high the mean, which the slow units pull up; never a range narrower than 25%. Null with too
 *  few samples or nothing left. */
export function rangeLeft(unitSeconds: number[], remaining: number): [number, number] | null {
  if (unitSeconds.length < RANGE_MIN_SAMPLES || !(remaining > 0)) return null;
  const sorted = [...unitSeconds].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length;
  const low = remaining * Math.min(median, mean);
  const high = Math.max(remaining * Math.max(median, mean), low * 1.25);
  return [low, high];
}

export function rangeText(r: [number, number]): string {
  const min = (s: number) => Math.max(1, Math.round(s / 60));
  const a = min(r[0]), b = min(r[1]);
  return a === b ? `about ${a} min left in this step` : `about ${a} to ${b} min left in this step`;
}

export interface View {
  percent: number | null;
  step: string | null;
  count: string | null;
  slow: string | null;
  range: string | null;
  noProgress: boolean;
}

/** The overall bar over a run of polls. The percentage only moves forward; a signature of the counts says when the
 *  review last moved; per-unit durations (time between two changes over the units gained) feed the time-left range. */
export class ProgressTracker {
  private best: number | null = null;
  private lastSignature = "";
  private lastMove = 0;
  private step: number | null = null;
  private lastDone: number | null = null;
  private lastAt = 0;
  private durations: number[] = [];

  update(d: ReviewProgressDetail, nowMs: number, extra = 0): View {
    const raw = overallPercent(d);
    if (raw !== null) this.best = this.best === null ? raw : Math.max(this.best, raw);
    const signature = [d.step, d.pages_done, d.clauses_done, d.requirements_done].join("|");
    if (signature !== this.lastSignature) {
      this.lastSignature = signature;
      this.lastMove = nowMs;
    }
    this.track(d, nowMs);
    const idleHere = (nowMs - this.lastMove) / 1000;
    const serverIdle = num(d.substep_seconds) ? d.substep_seconds + extra : 0;
    return {
      percent: this.best,
      step: num(d.step) ? stepName(d.step, d.steps_total) : null,
      count: requirementsLine(d),
      slow: slowLine(d, extra),
      range: this.rangeFor(d),
      noProgress: Math.max(idleHere, serverIdle) >= NO_PROGRESS_SECONDS,
    };
  }

  private done(d: ReviewProgressDetail): number | null {
    const v = d.step === 3 ? d.requirements_done : d.step === 4 ? d.clauses_done : d.pages_done;
    return num(v) ? v : null;
  }

  private track(d: ReviewProgressDetail, nowMs: number): void {
    const done = this.done(d);
    if (d.step !== this.step) {
      this.step = num(d.step) ? d.step : null;
      this.durations = [];
      this.lastDone = done;
      this.lastAt = nowMs;
      return;
    }
    if (done !== null && this.lastDone !== null && done > this.lastDone) {
      this.durations.push((nowMs - this.lastAt) / 1000 / (done - this.lastDone));
      if (this.durations.length > 30) this.durations.shift();
    }
    if (done !== this.lastDone) {
      this.lastDone = done;
      this.lastAt = nowMs;
    }
  }

  private rangeFor(d: ReviewProgressDetail): string | null {
    const total = d.step === 3 ? d.requirements_total : d.step === 4 ? d.clauses_total : d.pages_total;
    const done = this.done(d);
    if (done === null || !num(total)) return null;
    const r = rangeLeft(this.durations, total - done);
    return r ? rangeText(r) : null;
  }
}
