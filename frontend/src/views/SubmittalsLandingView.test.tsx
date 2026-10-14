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
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubmittalsLandingView } from "./SubmittalsLandingView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const startReviewRun = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
  },
}));

beforeEach(() => {
  documents.mockReset();
  reviewRuns.mockReset();
  startReviewRun.mockReset();
});

describe("SubmittalsLandingView", () => {
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

  it("shows the error when the run list cannot be loaded", async () => {
    documents.mockResolvedValue({ ok: true, data: [] });
    reviewRuns.mockResolvedValue({ ok: false, error: { message: "offline" } });
    render(<SubmittalsLandingView onOpenRun={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  });
});
