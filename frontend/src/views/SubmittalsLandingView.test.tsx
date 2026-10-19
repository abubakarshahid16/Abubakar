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

import { INBOX_REFRESH_MS, RUN_COUNTS_MAX_IDS, SubmittalsLandingView, loadReadyCounts } from "./SubmittalsLandingView";
import { INBOX_IS_DEFAULT } from "../routing";

const documents = vi.fn();
const reviewRuns = vi.fn();
const startReviewRun = vi.fn();
const reviewRunSummary = vi.fn();
const reviewRunCounts = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
    reviewRunSummary: (...args: unknown[]) => reviewRunSummary(...args),
    reviewRunCounts: (...args: unknown[]) => reviewRunCounts(...args),
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
  reviewRunSummary.mockReset();
  reviewRunCounts.mockReset().mockResolvedValue({ ok: true, data: { boundary: "", counts: {} } });
});

const tiers = (comment: number, needs_you: number) => ({
  met: 90, not_applicable: 4, another_document: 7, comment, needs_you, removed: 3, total: 104 + comment + needs_you,
});

describe("loadReadyCounts (A-1126, order 117 item 5)", () => {
  it("counts the findings in a comment or needs-you tier, never Met or removed ones, from ONE counts request", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "your runs", counts: {
      "run-1": tiers(27, 6557), "run-2": tiers(1, 0),
    } } });
    expect(await loadReadyCounts(["run-1", "run-2"])).toEqual({
      "run-1": { findings: 6584, needs_you: 6557 },
      "run-2": { findings: 1, needs_you: 0 },
    });
    expect(reviewRunCounts).toHaveBeenCalledTimes(1);
    expect(reviewRunCounts).toHaveBeenCalledWith(["run-1", "run-2"]);
    expect(reviewRunSummary).not.toHaveBeenCalled();
  });

  it(`splits ${RUN_COUNTS_MAX_IDS + 50} ids into two requests: ${RUN_COUNTS_MAX_IDS} then 50`, async () => {
    const ids = Array.from({ length: 250 }, (_, i) => `run-${i}`);
    const got = await loadReadyCounts(ids);
    expect(RUN_COUNTS_MAX_IDS).toBe(200);
    expect(reviewRunCounts).toHaveBeenCalledTimes(2);
    expect(reviewRunCounts.mock.calls[0][0]).toEqual(ids.slice(0, 200));
    expect(reviewRunCounts.mock.calls[1][0]).toEqual(ids.slice(200));
    expect(Object.keys(got)).toHaveLength(250);
  });

  it("is null, never 0, for a run absent from the answer", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: { "run-1": tiers(2, 1) } } });
    expect(await loadReadyCounts(["run-1", "gone"])).toEqual({
      "run-1": { findings: 3, needs_you: 1 }, gone: null,
    });
  });

  it("is null for every run of a request that failed or threw", async () => {
    reviewRunCounts
      .mockResolvedValueOnce({ ok: false, error: { code: "internal", message: "no route" } });
    expect(await loadReadyCounts(["run-1", "run-2"])).toEqual({ "run-1": null, "run-2": null });
    reviewRunCounts.mockRejectedValueOnce(new Error("network"));
    expect(await loadReadyCounts(["run-3"])).toEqual({ "run-3": null });
  });
});

describe("SubmittalsLandingView", () => {
  it("order 132: passes isAdmin to New review, so a non-admin is refused before any upload", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    // v2.1: a non-admin gets a plain message in place of the New review card;
    // the drop zone is not even drawn, so nothing can be uploaded.
    const { rerender } = render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin={false} />);
    expect(await screen.findByTestId("not-admin-message")).toHaveTextContent("Only an administrator can start a review.");
    expect(screen.queryByTestId("drop-zone")).toBeNull();
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

  it("v2.1 N2: switch on, the load error is said in plain words, the server's words folded under Details", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: false, disconnected: false, error: { code: "internal", message: "sqlite3.OperationalError: locked" } });
    render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace />);
    const alert = await screen.findByTestId("landing-load-error");
    expect(alert.querySelector("p")).toHaveTextContent(/^Could not load the list of reviews\. Try again in a moment\.$/);
    const details = alert.querySelector("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveTextContent("sqlite3.OperationalError: locked");
  });

  it("v2.1: switch on hides the 'Try the new inbox' teaser; switch off keeps it", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    const { unmount } = render(<SubmittalsLandingView onOpenRun={vi.fn()} onOpenInbox={vi.fn()} workspace />);
    await screen.findByTestId("new-review-card");
    expect(screen.queryByRole("button", { name: "Try the new inbox" })).toBeNull();
    expect(screen.queryByText(/stays the default/)).toBeNull();
    unmount();
    render(<SubmittalsLandingView onOpenRun={vi.fn()} onOpenInbox={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Try the new inbox" })).toBeInTheDocument();
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

  it("order 117 item 5: the inbox asks for every Ready row's counts in one request, never the full summary", async () => {
    documents.mockResolvedValue({ ok: true, data: [
      { id: "a", filename: "a.pdf" }, { id: "b", filename: "b.pdf" }, { id: "c", filename: "c.pdf" },
    ] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: ["a", "b", "c"].map((d) => ({
      review_run_id: `run-${d}`, submittal_document_id: d, submittal_filename: `${d}.pdf`,
      equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
      standards_in_scope: 1, findings_total: 0, by_status: {},
    })) } });
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: {
      "run-a": tiers(2, 1), "run-b": tiers(0, 0),
    } } });
    render(<SubmittalsLandingView inbox onOpenRun={vi.fn()} />);
    expect(await screen.findByText(/^Ready: 3 findings to decide, 1 needs you/)).toBeInTheDocument();
    expect(reviewRunCounts).toHaveBeenCalledTimes(1);
    expect([...reviewRunCounts.mock.calls[0][0]].sort()).toEqual(["run-a", "run-b", "run-c"]);
    expect(reviewRunSummary).not.toHaveBeenCalled();
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
