/** G4: the general review's running screen has ONE step line (the screen's own, from the job's five named steps) and a stall light
 *  that does not read the earlier engine's clock. The earlier engine's block is unchanged. Invented numbers only. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReviewProgressDetail } from "../../../types/api";
import { ReviewProgressBlock } from "./ReviewProgressBlock";
import { GENERAL_STEPS, isGeneralJob } from "./reviewProgress";

// What the server builds for a general job on its checklist step: the earlier engine's counting reads it as "step 3 of 4",
// and 200 s without a row update is past the earlier engine's amber line.
const detail = (o: Partial<ReviewProgressDetail> = {}): ReviewProgressDetail => ({
  steps_total: 4, step: 3, pages_done: null, pages_total: null, elapsed_seconds: 560, idle_seconds: 200, substep_seconds: 196,
  stall_amber_seconds: 120, stale: false, ...o,
});
const general = (label: string, done: number, d: ReviewProgressDetail) => ({
  id: "j", state: "running", cancel_requested: false, progress_done: done, progress_total: 5, progress_label: label, progress_detail: d,
});

describe("isGeneralJob", () => {
  it("is the five named steps, or a queued job of five", () => {
    for (const [i, name] of GENERAL_STEPS.entries()) expect(isGeneralJob({ progress_total: 5, progress_label: name })).toBe(true);
    expect(isGeneralJob({ progress_total: 5, progress_label: "queued" })).toBe(true);
  });
  it("is not the earlier engine's job", () => {
    expect(isGeneralJob({ progress_total: 3, progress_label: "reading page 2 of 9" })).toBe(false);
    expect(isGeneralJob({ progress_total: 5, progress_label: "reading page 2 of 9" })).toBe(false);
    expect(isGeneralJob(null)).toBe(false);
  });
});

describe("the general review's block", () => {
  it("draws no step line of its own (the screen's line is the only one) and no 'of 4'", () => {
    const { container } = render(<ReviewProgressBlock job={general("checklist", 2, detail())} />);
    expect(screen.queryByTestId("review-progress-step")).toBeNull();
    expect(container.textContent).not.toMatch(/Step \d of 4|reading pages again|comparing requirements|% overall/);
  });

  it("says no 'No progress' while the checklist step is working (the old clock reads 200 s)", () => {
    render(<ReviewProgressBlock job={general("checklist", 2, detail())} />);
    expect(screen.queryByTestId("review-stall")).toBeNull();
    expect(screen.queryByTestId("review-no-progress")).toBeNull();
    // what it does say: elapsed and how long this step has run, as facts
    expect(screen.getByTestId("review-progress-detail").textContent).toBe("Elapsed 9:20 · this step, 3 min 16 s so far");
  });

  it("the bar counts the job's own steps, out of five", () => {
    render(<ReviewProgressBlock job={general("judge", 3, detail({ step: 4 }))} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "5");
    expect(bar).toHaveAttribute("aria-label", "3 of 5 steps finished");
  });

  it("still lights red when the server says the worker is gone", () => {
    render(<ReviewProgressBlock job={general("checklist", 2, detail({ stale: true }))} />);
    expect(screen.getByTestId("review-stall")).toHaveAttribute("data-level", "red");
  });
});

describe("the earlier engine's block is unchanged", () => {
  it("keeps its step line and its amber light", () => {
    render(<ReviewProgressBlock job={{ id: "j", state: "running", cancel_requested: false, progress_done: 1, progress_total: 3,
      progress_label: "reading page 2 of 9", progress_detail: detail({ pages_done: 1, pages_total: 9, step: 2 }) }} />);
    expect(screen.getByTestId("review-progress-step")).toHaveTextContent("Step 2 of 4: reading pages again for the standards they name");
    expect(screen.getByTestId("review-stall")).toHaveTextContent(/No progress for 3 min/);
  });
});
