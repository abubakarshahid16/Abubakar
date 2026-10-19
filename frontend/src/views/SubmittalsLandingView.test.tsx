/**
 * #967 PR1: the AI Submittal Review landing page decides which run to open
 * - the existing latest run for a reviewed document, or a freshly started
 * one for a document that has never been reviewed.
 *
 * MUTATION PROOF: drop the `existing` branch in `reviewDocument` and the
 * first test below fails (it would start a second run instead of opening
 * the one that exists); drop the `startReviewRun` call and the second
 * test fails.
 */
import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { INBOX_REFRESH_MS, SubmittalsLandingView, loadReadyCounts } from "./SubmittalsLandingView";
import { INBOX_IS_DEFAULT } from "../routing";

const documents = vi.fn();
const reviewRuns = vi.fn();
const startReviewRun = vi.fn();
const reviewRunSummary = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
    reviewRunSummary: (...args: unknown[]) => reviewRunSummary(...args),
  },
}));

// Order 132 item 3: the drop zone is told who the reader is (its own behaviour is NewReviewDropZone.test.tsx's).
vi.mock("../components/review/workspace/NewReviewDropZone", () => ({
  NewReviewDropZone: ({ isAdmin }: { isAdmin?: boolean }) => <p data-testid="drop-zone">{`admin: ${String(isAdmin)}`}</p>,
}));

beforeEach(() => {
  documents.mockReset();
  reviewRuns.mockReset();
  startReviewRun.mockReset();
});

describe("loadReadyCounts (A-1126)", () => {
  it("counts the findings in a comment or needs-you tier, never Met or removed ones", async () => {
    reviewRunSummary.mockResolvedValue({ ok: true, data: { counts: {
      met: 90, not_applicable: 4, another_document: 7, comment: 27, needs_you: 6557, removed: 3, total: 6688,
    } } });
    expect(await loadReadyCounts("run-1")).toEqual({ findings: 6584, needs_you: 6557 });
    expect(reviewRunSummary).toHaveBeenCalledWith("run-1");
  });

  it("is null when the summary cannot be read", async () => {
    reviewRunSummary.mockResolvedValue({ ok: false, error: { code: "internal", message: "no route" } });
    expect(await loadReadyCounts("run-1")).toBeNull();
  });
});

describe("SubmittalsLandingView", () => {
  it("order 132: passes isAdmin to New review, so a non-admin is refused before any upload", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    const { rerender } = render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin={false} />);
    expect(await screen.findByTestId("drop-zone")).toHaveTextContent("admin: false");
    rerender(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin />);
    expect(screen.getByTestId("drop-zone")).toHaveTextContent("admin: true");
  });

  it("opens the existing latest run for a reviewed document, without starting a new one", async () => {
    documents.mockResolvedValue({
      ok: true, data: [{ id: "doc-1", filename: "psv.pdf", document_role: "CONTRACTOR_SUBMITTAL" }],
    });
    reviewRuns.mockResolvedValue({
      ok: true, data: { runs: [{
        review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "psv.pdf",
        equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
        standards_in_scope: 1, findings_total: 0, by_status: {},
      }] },
    });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("starts a review for a document with no run yet, then opens the new run", async () => {
    documents.mockResolvedValue({
      ok: true, data: [{ id: "doc-2", filename: "vessel.pdf", document_role: "CONTRACTOR_SUBMITTAL" }],
    });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-new" } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(startReviewRun).toHaveBeenCalledWith("doc-2");
    expect(onOpenRun).toHaveBeenCalledWith("run-new");
  });

  it("shows the refusal as the server gave it, and does not navigate", async () => {
    documents.mockResolvedValue({
      ok: true, data: [{ id: "doc-3", filename: "tank.pdf", document_role: "CONTRACTOR_SUBMITTAL" }],
    });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    startReviewRun.mockResolvedValue({ ok: false, error: { message: "a review of this submittal is already running" } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("a review of this submittal is already running");
    expect(onOpenRun).not.toHaveBeenCalled();
  });

  it("order 109: asks for the run list once, even under StrictMode's double effect", async () => {
    documents.mockResolvedValue({ ok: true, data: [{ id: "doc-1", filename: "psv.pdf" }] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    render(<StrictMode><SubmittalsLandingView inbox onOpenRun={vi.fn()} /></StrictMode>);
    expect(await screen.findByText("psv.pdf")).toBeInTheDocument();
    expect(reviewRuns).toHaveBeenCalledTimes(1);
    expect(documents).toHaveBeenCalledTimes(1);
  });

  it("shows the error when the run list cannot be loaded", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: false, error: { message: "offline" } });
    render(<SubmittalsLandingView onOpenRun={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  });
  it("queues a review of every document never reviewed, reports each refusal by name, and opens nothing", async () => {
    documents.mockResolvedValue({ ok: true, data: [
      { id: "a", filename: "a.pdf" }, { id: "b", filename: "b.pdf" }, { id: "c", filename: "c.pdf" },
    ] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [{
      review_run_id: "run-c", submittal_document_id: "c", submittal_filename: "c.pdf",
      equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
      standards_in_scope: 1, findings_total: 0, by_status: {},
    }] } });
    startReviewRun
      .mockResolvedValueOnce({ ok: true, data: { review_run_id: "run-a" } })
      .mockResolvedValueOnce({ ok: false, error: { message: "a review of this submittal is already running" } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView inbox onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review all not reviewed (2)" }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Queued 1 of 2 reviews asked for.");
    expect(status).toHaveTextContent("b.pdf: a review of this submittal is already running");
    expect(startReviewRun.mock.calls.map((call) => call[0])).toEqual(["a", "b"]);
    expect(onOpenRun).not.toHaveBeenCalled();
    expect(reviewRuns).toHaveBeenCalledTimes(2);
  });

  describe("order 104: the inbox is switched off by default", () => {
    it("is off: /review keeps the current list and offers the inbox by a link", async () => {
      expect(INBOX_IS_DEFAULT).toBe(false);
      documents.mockResolvedValue({ ok: true, data: [{ id: "doc-1", filename: "psv.pdf" }] });
      reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
      const onOpenInbox = vi.fn();
      render(<SubmittalsLandingView onOpenRun={vi.fn()} onOpenInbox={onOpenInbox} />);
      expect(await screen.findByText("Not reviewed yet")).toBeInTheDocument();
      expect(screen.queryByRole("group", { name: "Show documents" })).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Try the new inbox" }));
      expect(onOpenInbox).toHaveBeenCalled();
    });

    it("the inbox shows its chips and a way back to the current list", async () => {
      documents.mockResolvedValue({ ok: true, data: [{ id: "doc-1", filename: "psv.pdf" }] });
      reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
      const onOpenList = vi.fn();
      render(<SubmittalsLandingView inbox onOpenRun={vi.fn()} onOpenList={onOpenList} />);
      expect(await screen.findByRole("group", { name: "Show documents" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Back to the current list" }));
      expect(onOpenList).toHaveBeenCalled();
    });
  });

  describe("order 95 piece 3: the list re-reads while a review is moving", () => {
    afterEach(() => { vi.useRealTimers(); });

    function runOf(status: string) {
      return { ok: true, data: { runs: [{
        review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "psv.pdf",
        equipment_tags: [], status, created_at: "2026-10-01T00:00:00Z",
        standards_in_scope: 1, findings_total: 0, by_status: {},
        job: status === "running" ? { id: "j", state: "running", progress_done: 0, progress_total: 3,
          progress_label: "reading the datasheet", cancel_requested: false } : null,
      }] } };
    }

    it("re-reads on the interval while a review is running, and stops once it is not", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      documents.mockResolvedValue({ ok: true, data: [{ id: "doc-1", filename: "psv.pdf" }] });
      reviewRuns.mockResolvedValueOnce(runOf("running")).mockResolvedValue(runOf("completed"));
      render(<SubmittalsLandingView inbox onOpenRun={vi.fn()} />);
      await screen.findByRole("button", { name: "Queued or running (1 of 1)" });
      expect(reviewRuns).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS);
      await screen.findByRole("button", { name: "Needs me (1 of 1)" });
      expect(reviewRuns).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS * 3);
      expect(reviewRuns).toHaveBeenCalledTimes(2);
    });
  });
});
