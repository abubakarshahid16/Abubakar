/**
 * #791: the five-step panel fetches the run's stored trace and shows a light
 * and a reason per step; a trace that cannot be loaded is said, not hidden.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../types/api";
import { ReviewStepsPanel } from "./ReviewStepsPanel";

const reviewTrace = vi.fn();
vi.mock("../../api/client", () => ({
  reviews: { reviewTrace: (...a: unknown[]) => reviewTrace(...a) },
}));

const RUN = { review_run_id: "run-1", findings_total: 3, engineer_final_code: null,
  ai_numbers: null } as unknown as ReviewRunSummary;

beforeEach(() => reviewTrace.mockReset());

describe("ReviewStepsPanel", () => {
  it("shows five steps with a light and reason from the stored trace", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", document: null,
      source: "stored", ai: {}, steps: [{ step: "READ", summary: "pages 5", status: "ok", warning: null,
        counts: { values: 0 }, items: [], timing: null }] } });
    render(<ReviewStepsPanel run={RUN} />);
    const read = await screen.findByTestId("step-read");
    expect(reviewTrace).toHaveBeenCalledWith("run-1");
    expect(read).toHaveAttribute("data-light", "red");
    expect(read).toHaveTextContent("Red: no value was read from the datasheet");
    expect(screen.getAllByRole("listitem").filter((li) => li.dataset.light)).toHaveLength(5);
  });

  it("a trace that cannot be loaded is said, and each step names the gap", async () => {
    reviewTrace.mockResolvedValue({ ok: false, error: { message: "not found" } });
    render(<ReviewStepsPanel run={RUN} />);
    expect(await screen.findByTestId("review-steps-error")).toHaveTextContent("could not be loaded (not found)");
    expect(screen.getByTestId("step-standards")).toHaveTextContent("Amber: no standards record for this run");
  });

  it("#791: each count of findings opens the findings it counts", async () => {
    reviewTrace.mockResolvedValue({ ok: false, error: { message: "not found" } });
    const onShowStatus = vi.fn();
    const run = { ...RUN, findings_total: 5,
      by_status: { COMPLIANT: 3, NEEDS_ENGINEER_REVIEW: 2 } } as unknown as ReviewRunSummary;
    render(<ReviewStepsPanel run={run} onShowStatus={onShowStatus} />);
    const links = await screen.findByTestId("step-decide-links");
    fireEvent.click(screen.getByRole("button", { name: /^Compliant 3 of 5/ }));
    expect(onShowStatus).toHaveBeenCalledWith("COMPLIANT");
    expect(links).toHaveTextContent("2 of 5");
  });

  it("offers no links when the page cannot show findings", async () => {
    reviewTrace.mockResolvedValue({ ok: false, error: { message: "not found" } });
    render(<ReviewStepsPanel run={{ ...RUN, by_status: { COMPLIANT: 3 } } as unknown as ReviewRunSummary} />);
    await screen.findByTestId("step-decide");
    expect(screen.queryByTestId("step-decide-links")).toBeNull();
  });
});
