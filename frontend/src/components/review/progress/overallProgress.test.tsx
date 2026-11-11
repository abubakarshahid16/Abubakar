/** The review's overall bar: four named steps, one percentage that never goes back, step 3's own count, the orange state
 *  after 5 minutes without movement, a null count printing nothing. Invented numbers only. */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewProgressDetail } from "../../../types/api";
import { ReviewProgressBlock } from "./ReviewProgressBlock";
import {
  ProgressTracker, overallPercent, rangeLeft, requirementsLine, slowLine, stepName,
} from "./overallProgress";

const d = (o: Partial<ReviewProgressDetail> = {}): ReviewProgressDetail => ({
  step: 1, steps_total: 4, pages_done: 0, pages_total: 10, elapsed_seconds: 60, idle_seconds: 5,
  stall_amber_seconds: 120, stale: false, substep_seconds: 2, ...o,
});
const job = (detail: ReviewProgressDetail) => ({
  id: "j1", state: "running", cancel_requested: false, progress_detail: detail,
});

afterEach(() => vi.useRealTimers());

describe("the overall percentage", () => {
  it("gives each step its share: read 0-40, pages again 40-55, compare 55-90, write 90-100", () => {
    expect(overallPercent(d({ step: 1, pages_done: 0 }))).toBe(0);
    expect(overallPercent(d({ step: 1, pages_done: 10 }))).toBe(40);
    expect(overallPercent(d({ step: 2, pages_done: 0 }))).toBe(40);
    expect(overallPercent(d({ step: 2, pages_done: 10 }))).toBe(55);
    expect(overallPercent(d({ step: 3, pages_done: null, pages_total: null, requirements_done: 0, requirements_total: 100 }))).toBe(55);
    expect(overallPercent(d({ step: 3, requirements_done: 100, requirements_total: 100 }))).toBe(90);
    expect(overallPercent(d({ step: 4, clauses_done: 6, clauses_total: 60 }))).toBe(91);
  });
  it("never goes back across a step change like 73% to 36% (the live review)", () => {
    const t = new ProgressTracker();
    const seen = [
      d({ step: 1, pages_done: 7, pages_total: 10 }),                     // step 1 at 70%
      d({ step: 1, pages_done: 9, pages_total: 10 }),
      d({ step: 2, pages_done: 3, pages_total: 8 }),                      // a new page count: its own share
      d({ step: 2, pages_done: 8, pages_total: 8 }),
      d({ step: 3, pages_done: null, pages_total: null, requirements_done: 10, requirements_total: 1000 }),
    ].map((x, i) => t.update(x, i * 1000).percent as number);
    for (let i = 1; i < seen.length; i++) expect(seen[i]).toBeGreaterThanOrEqual(seen[i - 1]);
    expect(seen[0]).toBe(28);
    expect(seen[2]).toBeGreaterThan(seen[1]);
  });
  it("holds the highest value when a poll briefly says less", () => {
    const t = new ProgressTracker();
    t.update(d({ step: 1, pages_done: 9 }), 0);
    expect(t.update(d({ step: 1, pages_done: 2 }), 1000).percent).toBe(36);
  });
  it("is null, not 0, when the step is unknown", () => {
    expect(overallPercent(d({ step: null }))).toBeNull();
    expect(new ProgressTracker().update(d({ step: null }), 0).percent).toBeNull();
  });
});

describe("the names and counts", () => {
  it("names each step clearly", () => {
    expect(stepName(2)).toBe("Step 2 of 4: reading pages again for the standards they name");
    expect(stepName(3)).toBe("Step 3 of 4: comparing requirements");
  });
  it("step 3 shows its own count with thousands separators", () => {
    expect(requirementsLine(d({ requirements_done: 1240, requirements_total: 5062 })))
      .toBe("1,240 of 5,062 requirements compared");
    render(<ReviewProgressBlock job={job(d({ step: 3, requirements_done: 1240, requirements_total: 5062 }))} />);
    expect(screen.getByTestId("review-progress-detail").textContent).toContain("1,240 of 5,062 requirements compared");
    expect(screen.getByRole("progressbar")).toBeInTheDocument(); // the bar stays in step 3
    expect(screen.getByTestId("review-progress-step").textContent).toBe("Step 3 of 4: comparing requirements");
  });
  it("a null count prints nothing, never 0", () => {
    expect(requirementsLine(d({ requirements_done: null, requirements_total: 5062 }))).toBeNull();
    expect(requirementsLine(d({ requirements_done: 5, requirements_total: null }))).toBeNull();
    render(<ReviewProgressBlock job={job(d({ step: 3, requirements_done: null, requirements_total: null }))} />);
    expect(screen.getByTestId("review-progress-detail").textContent).not.toMatch(/requirements compared|0 of/);
  });
});

describe("time on a slow page and time left", () => {
  it("shows the time spent so far only when the page is slow", () => {
    expect(slowLine(d({ pages_done: 4, substep_seconds: 10 }))).toBeNull();
    expect(slowLine(d({ pages_done: 4, substep_seconds: 40 }))).toBe("page 5, 40 s so far");
    expect(slowLine(d({ pages_done: 4, pages_unit: "part", substep_seconds: 125 }))).toBe("part 5, 2 min 5 s so far");
    expect(slowLine(d({ substep_seconds: null }))).toBeNull();
  });
  it("time left is a range that slow pages widen, and absent with too few pages", () => {
    expect(rangeLeft([10, 11], 5)).toBeNull();
    const [low, high] = rangeLeft([10, 10, 10, 70], 5)!;
    expect(low).toBe(50);
    expect(high).toBeGreaterThan(low * 1.25);
    expect(rangeLeft([10, 10, 10], 0)).toBeNull();
  });
});

describe("no progress for 5 minutes", () => {
  it("turns the bar orange with its own line when nothing moves for 5 minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-03T10:00:00Z"));
    const detail = d({ step: 1, pages_done: 3, substep_seconds: 0 });
    render(<ReviewProgressBlock job={job(detail)} />);
    expect(screen.getByTestId("review-progress-fill")).toHaveAttribute("data-state", "working");
    expect(screen.queryByTestId("review-no-progress")).toBeNull();
    act(() => { vi.advanceTimersByTime(299_000); });
    expect(screen.queryByTestId("review-no-progress")).toBeNull();
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(screen.getByTestId("review-no-progress").textContent).toBe("No progress for 5 minutes.");
    expect(screen.getByTestId("review-progress-fill")).toHaveAttribute("data-state", "no-progress");
    expect(screen.getByTestId("review-progress-fill").className).toContain("bg-warn-500");
    expect(screen.getByTestId("review-progress-fill").className).not.toContain("progress-stripes");
  });
  it("movement resets it, and the stripe runs while the review is working", () => {
    const t = new ProgressTracker();
    expect(t.update(d({ pages_done: 3 }), 0).noProgress).toBe(false);
    expect(t.update(d({ pages_done: 3 }), 290_000).noProgress).toBe(false);
    expect(t.update(d({ pages_done: 4 }), 310_000).noProgress).toBe(false);
    expect(t.update(d({ pages_done: 4 }), 611_000).noProgress).toBe(true);
    render(<ReviewProgressBlock job={job(d({ pages_done: 3 }))} />);
    expect(screen.getByTestId("review-progress-fill").className).toContain("progress-stripes");
  });
  it("trusts the server's own age of the sub-step on first sight", () => {
    expect(new ProgressTracker().update(d({ substep_seconds: 400 }), 0).noProgress).toBe(true);
    expect(new ProgressTracker().update(d({ substep_seconds: null }), 0).noProgress).toBe(false);
  });
});
