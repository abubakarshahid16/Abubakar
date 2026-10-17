/** P3: a queued or running review shows its progress on the Sheet screen and
 *  can be cancelled; its findings load by themselves once the job finishes.
 *  Ported from the old page's tests (#967 PR 3). Mutations M886-M889, M1135. */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../types/api";
import { ReviewSheetView } from "./ReviewSheetView";

const reviewRuns = vi.fn();
const cancelJob = vi.fn();
const list = vi.fn();
vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "d", filename: "pump.pdf", page_count: 1 } }) },
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    list: (...a: unknown[]) => list(...a),
    crsIssueGate: async () => ({ ok: true, data: { review_run_id: "run-1", issuable: false, final_code_recorded: false, blockers: [], unread_pages: [], open_findings: [] } }),
    reviewRunStandards: async () => ({ ok: true, data: { standards: [] } }),
    readiness: async () => ({ ok: false, error: { message: "not in this test" } }),
    visionReaderStatus: async () => ({ ok: false, error: { message: "n/a" } }),
    cancelJob: (...a: unknown[]) => cancelJob(...a),
    startReviewRun: vi.fn(), exportCrs: vi.fn(), decideCode: vi.fn(), decideCrsFinding: vi.fn(),
  },
}));
vi.mock("../components/review/sheet/SheetPageImage", () => ({ SheetPageImage: () => <p>page</p> }));
vi.mock("../components/review/EvidencePageImage", () => ({ EvidencePageImage: () => <p>page</p> }));
vi.mock("../components/DocumentPreview", () => ({ DocumentPreview: () => <p>preview</p> }));

function run(over: Partial<ReviewRunSummary>): ReviewRunSummary {
  return { review_run_id: "run-1", submittal_document_id: "d", submittal_filename: "pump.pdf",
    equipment_tags: [], status: "queued", created_at: "2026-09-26T00:00:00Z", completed_at: null,
    standards_in_scope: 0, findings_total: 0, by_status: {}, recommended_code: null,
    recommended_reason: null,
    job: { id: "job-1", state: "queued", progress_done: 0, progress_total: 3,
      progress_label: "queued", cancel_requested: false }, ...over } as ReviewRunSummary;
}

const sheet = () => <ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />;

beforeEach(() => {
  reviewRuns.mockReset(); cancelJob.mockReset();
  list.mockReset(); list.mockResolvedValue({ ok: true, data: { findings: [] } });
});
afterEach(() => { vi.useRealTimers(); });

describe("a review on the queue", () => {
  it("says a queued review is waiting and cancels it on request", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({})] } });
    cancelJob.mockResolvedValue({ ok: true, data: {} });
    render(sheet());
    expect(await screen.findByTestId("review-progress")).toHaveTextContent("Waiting to start");
    await userEvent.click(screen.getByRole("button", { name: "Cancel this review" }));
    expect(cancelJob).toHaveBeenCalledWith("job-1");
    expect(reviewRuns.mock.calls.length).toBeGreaterThan(1);
  });

  it("names the step a running review is on", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 1, progress_total: 3,
        progress_label: "selecting the applicable standards", cancel_requested: false } })] } });
    render(sheet());
    expect(await screen.findByTestId("review-progress"))
      .toHaveTextContent("Step 2 of 3: selecting the applicable standards");
  });

  it("says a cancellation is pending instead of offering a second one", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 2, progress_total: 3,
        progress_label: "comparing", cancel_requested: true } })] } });
    render(sheet());
    expect(await screen.findByTestId("review-progress")).toHaveTextContent("stopping at the next step");
    expect(screen.queryByRole("button", { name: "Cancel this review" })).toBeNull();
  });

  it("shows the server's refusal", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({})] } });
    cancelJob.mockResolvedValue({ ok: false, error: { message: "this job can no longer be cancelled; it is done" } });
    render(sheet());
    await userEvent.click(await screen.findByRole("button", { name: "Cancel this review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer be cancelled");
  });

  it("offers nothing for a finished review", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "completed",
      job: { id: "job-1", state: "done", progress_done: 3, progress_total: 3, progress_label: "done",
        cancel_requested: false } })] } });
    render(sheet());
    await screen.findByTestId("sheet-headline");
    expect(screen.queryByTestId("review-progress")).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel this review" })).toBeNull();
  });

  it("shows no 'of N' when the server reported no total", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running",
      job: { id: "job-1", state: "running", progress_done: 1, progress_total: null,
        progress_label: "comparing", cancel_requested: false } })] } });
    render(sheet());
    const line = await screen.findByTestId("review-progress");
    expect(line).toHaveTextContent("Step 2: comparing");
    expect(line.textContent).not.toMatch(/ of \d/);
  });
});

describe("the findings, once the job finishes", () => {
  it("BUG GROUP (2026-09-27): the sheet fills by itself - no click", async () => {
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
    render(sheet());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByTestId("review-progress")).toHaveTextContent("Step 2 of 3: comparing");
    expect(screen.queryByTestId("sheet-headline")).toBeNull();

    // The job finishes in the background; nothing here clicks anything.
    status = "completed";
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByTestId("sheet-headline")).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith({ review_run_id: "run-1" });
  });
});
