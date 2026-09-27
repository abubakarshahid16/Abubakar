/** P3: a queued or running review shows its progress and can be cancelled.
 *  Mutations M886-M889. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../types/api";
import { ReviewRunsView } from "./ReviewRunsView";

const reviewRuns = vi.fn();
const cancelJob = vi.fn();
const list = vi.fn();
vi.mock("../api/client", () => ({
  api: { documents: () => Promise.resolve({ ok: true, data: [] }) },
  reviews: {
    // Section 3's readiness strip; not what these tests are about.
    readiness: async () => ({ ok: false, error: { message: "not in this test" } }),
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: () => Promise.resolve({ ok: true, data: { standards: [] } }),
    reviewRunStandardsAll: () => Promise.resolve({ ok: true, data: { standards: [] } }),
    cancelJob: (...a: unknown[]) => cancelJob(...a),
    startReviewRun: vi.fn(), previewCrs: vi.fn(), exportCrs: vi.fn(), decideCode: vi.fn(),
  },
}));

function run(over: Partial<ReviewRunSummary>): ReviewRunSummary {
  return { review_run_id: "run-1", submittal_document_id: "d", submittal_filename: "pump.pdf",
    equipment_tags: [], status: "queued", created_at: "2026-09-26T00:00:00Z", completed_at: null,
    standards_in_scope: 0, findings_total: 0, by_status: {}, recommended_code: null,
    recommended_reason: null,
    job: { id: "job-1", state: "queued", progress_done: 0, progress_total: 3,
      progress_label: "queued", cancel_requested: false }, ...over } as ReviewRunSummary;
}

beforeEach(() => {
  reviewRuns.mockReset(); cancelJob.mockReset();
  list.mockReset(); list.mockResolvedValue({ ok: true, data: { findings: [] } });
});
afterEach(() => { vi.useRealTimers(); });

describe("a review on the queue", () => {
  it("says a queued review is waiting and cancels it on request", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({})] } });
    cancelJob.mockResolvedValue({ ok: true, data: {} });
    render(<ReviewRunsView />);
    expect(await screen.findByTestId("review-progress")).toHaveTextContent("Waiting to start");
    await userEvent.click(screen.getByRole("button", { name: "Cancel this review" }));
    expect(cancelJob).toHaveBeenCalledWith("job-1");
    expect(reviewRuns.mock.calls.length).toBeGreaterThan(1);
  });

  it("names the step a running review is on", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 1, progress_total: 3,
        progress_label: "selecting the applicable standards", cancel_requested: false } })] } });
    render(<ReviewRunsView />);
    expect(await screen.findByTestId("review-progress"))
      .toHaveTextContent("Step 2 of 3: selecting the applicable standards");
  });

  it("says a cancellation is pending instead of offering a second one", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 2, progress_total: 3,
        progress_label: "comparing", cancel_requested: true } })] } });
    render(<ReviewRunsView />);
    expect(await screen.findByTestId("review-progress")).toHaveTextContent("stopping at the next step");
    expect(screen.queryByRole("button", { name: "Cancel this review" })).toBeNull();
  });

  it("shows the server's refusal", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({})] } });
    cancelJob.mockResolvedValue({ ok: false, error: { message: "this job can no longer be cancelled; it is done" } });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel this review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer be cancelled");
  });

  it("offers nothing for a finished review", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "completed",
      job: { id: "job-1", state: "done", progress_done: 3, progress_total: 3, progress_label: "done",
        cancel_requested: false } })] } });
    render(<ReviewRunsView />);
    await screen.findByText("pump.pdf");
    expect(screen.queryByTestId("review-progress")).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel this review" })).toBeNull();
  });
});

describe("the open run's findings, once its job finishes", () => {
  it("BUG GROUP (2026-09-27): reload automatically - no second click on the run card", async () => {
    // "Run AI review" opens ITS OWN run immediately (`start`, ReviewRunsView.tsx)
    // while it is still queued/running, with no findings yet - the job has
    // written none. The 3s poll below already refreshes the run CARD's own
    // status and progress; before this fix nothing told the OPEN FINDINGS
    // PANEL to look again once the job actually finished, so an engineer
    // watching the screen saw it sit empty until they clicked the run card
    // themselves. Opening the run here (one click) stands in for `start()`'s
    // own auto-open; the fix is proven by the SECOND `list` call happening
    // with no second click at all.
    vi.useFakeTimers();
    let status: "running" | "completed" = "running";
    reviewRuns.mockImplementation(() => Promise.resolve({
      ok: true,
      data: { runs: [run({ status,
        job: { id: "job-1", state: status === "completed" ? "done" : "running",
              progress_done: status === "completed" ? 3 : 1, progress_total: 3,
              progress_label: status === "completed" ? "done" : "comparing",
              cancel_requested: false } })] },
    }));

    render(<ReviewRunsView />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    fireEvent.click(screen.getByText("pump.pdf"));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenLastCalledWith({ review_run_id: "run-1" });

    // The job finishes in the background; nothing here clicks anything.
    status = "completed";
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(list).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenLastCalledWith({ review_run_id: "run-1" });
  });

  it("does not reload findings on every poll tick while still running", async () => {
    vi.useFakeTimers();
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 1, progress_total: 3,
            progress_label: "comparing", cancel_requested: false } })] } });

    render(<ReviewRunsView />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fireEvent.click(screen.getByText("pump.pdf"));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(list).toHaveBeenCalledTimes(1);

    // Several poll ticks, status never leaves "running".
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(list).toHaveBeenCalledTimes(1);
  });
});
