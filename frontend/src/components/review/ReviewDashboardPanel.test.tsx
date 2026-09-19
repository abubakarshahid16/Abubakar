/**
 * The Dashboard's AI Submittal Review block.
 *
 * CLAUDE.md RULE 10 NAMES ITS CONTENTS: four cards, one button, one compact
 * Recent Reviews table. Rule 4 says every figure carries its population, so
 * "0 awaiting" is not an answer and "0 of 2 awaiting review" is.
 *
 * AND IT MUST NOT TAKE THE PAGE WITH IT. A body of the wrong shape once
 * reached the cards as `ok` and `.toLocaleString()` threw on the missing
 * count, blanking the WHOLE Dashboard over one panel. The client shape-checks
 * the response now; this file asserts the panel's half of that - a result it
 * cannot use renders nothing rather than crashing.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDashboardPanel } from "./ReviewDashboardPanel";
import type { ReviewDashboard, ReviewRunSummary } from "../../types/api";

const dashboard = vi.fn();
const documents = vi.fn();
const startReviewRun = vi.fn();
vi.mock("../../api/client", () => ({
  api: { documents: (...a: unknown[]) => documents(...a) },
  reviews: {
    dashboard: () => dashboard(),
    startReviewRun: (...a: unknown[]) => startReviewRun(...a),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc_sub",
    submittal_filename: "drum.pdf", equipment_tags: ["2003-47-V-0001A/B"],
    status: "completed", created_at: "2026-09-19T11:00:00Z", completed_at: null,
    standards_in_scope: 10, findings_total: 1580,
    by_status: { NON_COMPLIANT: 2 },
    recommended_code: "Manual Review Required",
    recommended_reason: "not enough of the submittal was read",
    completeness: null,
    ...over,
  } as ReviewRunSummary;
}

function data(over: Partial<ReviewDashboard> = {}): ReviewDashboard {
  return {
    submittals_total: 2, submittals_awaiting_review: 1,
    standards_available: 272,
    standards_referenced_total: 21, standards_referenced_missing: 21,
    reviews_running: 0, reviews_awaiting_decision: 8, reviews_total: 10,
    needs_attention: 9,
    needs_attention_reasons: {
      "not enough was read to recommend a code": 8, "the run failed": 1,
    },
    recent: [run()],
    ...over,
  } as ReviewDashboard;
}

beforeEach(() => {
  dashboard.mockReset();
  documents.mockReset();
  startReviewRun.mockReset();
  dashboard.mockResolvedValue({ ok: true, data: data() });
  documents.mockResolvedValue({
    ok: true, data: [{ id: "doc_sub", filename: "drum.pdf" }],
  });
});

function panel(onOpenReview = vi.fn(), onOpenDocuments = vi.fn()) {
  render(
    <ReviewDashboardPanel
      onOpenReview={onOpenReview} onOpenDocuments={onOpenDocuments}
    />,
  );
  return { onOpenReview, onOpenDocuments };
}

describe("four cards, each with its population", () => {
  it("states the denominator on every count rule 4 covers", async () => {
    panel();

    expect(await screen.findByText("1 of 2 awaiting review")).toBeInTheDocument();
    expect(screen.getByText(
      "21 of 21 cited standards are not in the library")).toBeInTheDocument();
    expect(screen.getByText(
      "0 running · 8 awaiting an engineer's code")).toBeInTheDocument();
  });

  it("says WHY anything needs attention, never a bare number", async () => {
    panel();

    // The 9 on its own is a figure a reader can only trust. The breakdown is
    // what makes it checkable, and it is the tile's own detail line.
    const tile = (await screen.findByText("Needs attention")).parentElement!;
    expect(within(tile).getByText("9")).toBeInTheDocument();
    expect(within(tile).getByText(
      /8 not enough was read to recommend a code · 1 the run failed/,
    )).toBeInTheDocument();
  });

  it("says nothing rather than nothing-is-wrong when nothing is", async () => {
    dashboard.mockResolvedValue({
      ok: true,
      data: data({ needs_attention: 0, needs_attention_reasons: {} }),
    });
    panel();

    const tile = (await screen.findByText("Needs attention")).parentElement!;
    expect(within(tile).getByText("nothing")).toBeInTheDocument();
  });
});

describe("the one button", () => {
  it("runs a review on a loaded submittal and goes straight to it", async () => {
    startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-9" } });
    const { onOpenReview } = panel();

    await userEvent.click(
      await screen.findByRole("button", { name: /Upload Datasheet and Run AI Review/ }));
    await userEvent.selectOptions(
      screen.getByLabelText(/already loaded/i), "doc_sub");
    await userEvent.click(screen.getByRole("button", { name: /^Run AI review$/ }));

    expect(startReviewRun).toHaveBeenCalledWith("doc_sub");
    // THE READER PRESSED A BUTTON THAT SAYS IT RUNS A REVIEW. Landing them
    // back on the dashboard would make them go looking for what they asked for.
    expect(onOpenReview).toHaveBeenCalledWith("run-9");
  });

  it("shows the server's refusal instead of a button that does nothing", async () => {
    startReviewRun.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "invalid_parameter", message: "a review of this submittal is already running" },
    });
    const { onOpenReview } = panel();

    await userEvent.click(
      await screen.findByRole("button", { name: /Upload Datasheet and Run AI Review/ }));
    await userEvent.selectOptions(
      screen.getByLabelText(/already loaded/i), "doc_sub");
    await userEvent.click(screen.getByRole("button", { name: /^Run AI review$/ }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "a review of this submittal is already running");
    expect(onOpenReview).not.toHaveBeenCalled();
  });

  it("sends a new datasheet to where upload progress actually lives", async () => {
    const { onOpenDocuments } = panel();

    await userEvent.click(
      await screen.findByRole("button", { name: /Upload Datasheet and Run AI Review/ }));
    await userEvent.click(
      screen.getByRole("button", { name: /Upload it on the Documents page/ }));

    expect(onOpenDocuments).toHaveBeenCalled();
  });
});

describe("the recent reviews table", () => {
  it("shows the engineer's code beside the recommendation, never instead", async () => {
    dashboard.mockResolvedValue({
      ok: true,
      data: data({ recent: [run({ engineer_final_code: "Approved with Comments" })] }),
    });
    panel();

    const row = (await screen.findByText("drum.pdf")).closest("tr")!;
    expect(within(row).getByText("Manual Review Required")).toBeInTheDocument();
    expect(within(row).getByText(/engineer: Approved with Comments/)).toBeInTheDocument();
  });

  it("says no reviews have been run rather than showing an empty table", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ recent: [] }) });
    panel();

    expect(await screen.findByText("No reviews have been run yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("a result it cannot use", () => {
  it("renders nothing rather than taking the Dashboard down with it", async () => {
    // What the client returns for a body that failed its shape check - and
    // what it used to return as `ok`, which threw inside the first card.
    dashboard.mockResolvedValue({
      ok: false, disconnected: true, error: { code: "disconnected", message: "offline" },
    });
    const { container } = render(
      <ReviewDashboardPanel onOpenReview={vi.fn()} onOpenDocuments={vi.fn()} />,
    );

    await Promise.resolve();
    expect(container).toBeEmptyDOMElement();
  });
});
