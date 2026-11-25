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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDashboardPanel } from "./ReviewDashboardPanel";
import type { ReviewDashboard, ReviewRunSummary } from "../../types/api";

const dashboard = vi.fn();
const documents = vi.fn();
const planFor = vi.fn();
const startReviewRun = vi.fn(); // the ONE start: POST /reviews/start through reviewPlan.start
vi.mock("../../api/client", () => ({
  api: { documents: (...a: unknown[]) => documents(...a) },
  reviews: { dashboard: () => dashboard() },
}));
vi.mock("../../api/reviewPlan", () => ({
  reviewPlan: { plan: (...a: unknown[]) => planFor(...a), start: (...a: unknown[]) => startReviewRun(...a) },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc_sub",
    submittal_filename: "drum.pdf", equipment_tags: ["9900-99-V-0101A/B"],
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
  planFor.mockReset();
  planFor.mockResolvedValue({ ok: true, data: { choice: "automatic", parts: [], text_leaves: false, refused: null,
    documents: { leaving: [], not_sent: [], not_readable: 0 } } });
  dashboard.mockResolvedValue({ ok: true, data: data() });
  documents.mockResolvedValue({
    ok: true, data: [{ id: "doc_sub", filename: "drum.pdf" }],
  });
});

function panel(
  onOpenReview = vi.fn(), onOpenDocuments = vi.fn(), isAdmin?: boolean,
) {
  render(
    <ReviewDashboardPanel
      onOpenReview={onOpenReview} onOpenDocuments={onOpenDocuments}
      isAdmin={isAdmin}
    />,
  );
  return { onOpenReview, onOpenDocuments };
}

describe("four cards, each with its population", () => {
  it("order 132: the recent table names the computer's code as a suggestion", async () => {
    panel();
    expect(await screen.findByRole("columnheader", { name: "Suggested code" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Recommended" })).toBeNull();
  });

  it("states the denominator on every count rule 4 covers", async () => {
    panel();

    expect(await screen.findByText("1 of 2 awaiting review")).toBeInTheDocument();
    expect(screen.getByText(
      "21 of 21 cited standards are not in the library")).toBeInTheDocument();
    expect(screen.getByText(
      "0 running · 8 waiting for an engineer's sign-off or code")).toBeInTheDocument();
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
      await screen.findByRole("button", { name: /Upload a document and run AI review/ }));
    await userEvent.selectOptions(
      screen.getByLabelText(/already loaded/i), "doc_sub");
    await userEvent.click(screen.getByRole("button", { name: /^Run AI review$/ }));
    // THE ONE START: the pre-start step opens first; nothing has started yet.
    expect(await screen.findByTestId("start-review-step")).toBeInTheDocument();
    expect(startReviewRun).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Start review" }));

    await waitFor(() => expect(startReviewRun).toHaveBeenCalledWith("doc_sub", "automatic", []));
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
      await screen.findByRole("button", { name: /Upload a document and run AI review/ }));
    await userEvent.selectOptions(
      screen.getByLabelText(/already loaded/i), "doc_sub");
    await userEvent.click(screen.getByRole("button", { name: /^Run AI review$/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Start review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already running");
    expect(onOpenReview).not.toHaveBeenCalled();
  });

  it("sends a new datasheet to where upload progress actually lives", async () => {
    const { onOpenDocuments } = panel();

    await userEvent.click(
      await screen.findByRole("button", { name: /Upload a document and run AI review/ }));
    await userEvent.click(
      screen.getByRole("button", { name: /Upload it on the Documents page/ }));

    expect(onOpenDocuments).toHaveBeenCalled();
  });

  it("disables the button and says why for a non-admin, rather than a 404 that reads as a missing submittal (#925)", async () => {
    panel(vi.fn(), vi.fn(), false);

    const launch = await screen.findByRole(
      "button", { name: /Upload a document and run AI review/ });
    expect(launch).toBeDisabled();
    expect(screen.getByText(/Only an administrator can start a review/))
      .toBeInTheDocument();
    expect(startReviewRun).not.toHaveBeenCalled();
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
  it("says the figures failed rather than taking the Dashboard down, and keeps the button", async () => {
    // What the client returns for a body that failed its shape check - and
    // what it used to return as `ok`, which threw inside the first card.
    // Audit 2026-09-30: the panel then returned null, so the Dashboard's
    // one review button vanished with no word why.
    dashboard.mockResolvedValue({
      ok: false, disconnected: true, error: { code: "disconnected", message: "offline" },
    });
    panel();

    expect(await screen.findByText(/The review figures could not be loaded - offline/))
      .toBeInTheDocument();
    expect(screen.getByText(/This is not a count of zero/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Upload a document and run AI review/ }))
      .toBeInTheDocument();
    expect(screen.queryByText("Needs attention")).toBeNull();
  });

  it("says the submittal list failed instead of showing an empty picker", async () => {
    documents.mockResolvedValue({
      ok: false, disconnected: false, error: { code: "internal_error", message: "list broke" },
    });
    panel();

    await userEvent.click(
      await screen.findByRole("button", { name: /Upload a document and run AI review/ }));
    expect(await screen.findByText(/contractor submittals could not be loaded - list broke/))
      .toBeInTheDocument();
  });
});

describe("audit 2026-09-30: what the block counts, in plain words", () => {
  it("states that its counts cover only the documents the reader can open", async () => {
    panel();
    expect(await screen.findByTestId("review-boundary"))
      .toHaveTextContent("These review counts cover only the documents you can open.");
  });

  it("shows a run's status in plain words, not the database value", async () => {
    dashboard.mockResolvedValue({
      ok: true, data: data({ recent: [run({ status: "queued" })] }),
    });
    panel();

    const row = (await screen.findByText("drum.pdf")).closest("tr")!;
    expect(within(row).getByText("Waiting to start")).toBeInTheDocument();
    expect(within(row).queryByText("queued")).toBeNull();
  });
});

describe("V1: the recent table reads plainly", () => {
  it("shows the first equipment tag and 'and N more', with the whole list in the tooltip", async () => {
    const tags = Array.from({ length: 30 }, (_, i) => `TAG-${i}`);
    dashboard.mockResolvedValue({ ok: true, data: data({ recent: [run({ equipment_tags: tags })] }) });
    panel();
    const cell = await screen.findByText("TAG-0 and 29 more");
    expect(cell).toHaveAttribute("title", tags.join(", "));
    expect(screen.queryByText(new RegExp(tags.join(", ")))).toBeNull();
  });

  it("shows 0 for a run that found 0, never a made-up label", async () => {
    dashboard.mockResolvedValue({
      ok: true,
      data: data({ recent: [run({ findings_total: 0, by_status: {}, recommended_code: null, equipment_tags: [] })] }),
    });
    panel();
    const row = (await screen.findByText("drum.pdf")).closest("tr") as HTMLElement;
    expect(within(row).getAllByRole("cell")[2]).toHaveTextContent(/^0$/);
    expect(within(row).queryByText(/No findings table|AI review/)).toBeNull(); // the row never labels a count "AI review"
  });

  it("keeps the count when there are findings", async () => {
    panel();
    expect(await screen.findByText("1,580")).toBeInTheDocument();
      });

  it("writes the run time in the one date format", async () => {
    panel();
    expect(await screen.findByText(/19 Sep 2026, \d{2}:\d{2}/)).toBeInTheDocument();
  });
});


describe("V2: the review cards say whose reviews they count", () => {
  it("adds 'of N papers, latest review each' when the server says how many papers", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ papers_with_a_review: 5, earlier_runs_not_counted: 82 }) });
    panel();
    expect(await screen.findByText(
      "0 running · 8 waiting for an engineer's sign-off or code · of 5 papers, latest review each · 82 earlier reviews not counted"))
      .toBeInTheDocument();
    const tile = screen.getByText("Needs attention").parentElement!;
    expect(within(tile).getByText(/of 5 papers, latest review each · 82 earlier reviews not counted/)).toBeInTheDocument();
  });
  it("says nothing extra from an older server that does not send the count", async () => {
    panel();
    expect(await screen.findByText("0 running · 8 waiting for an engineer's sign-off or code")).toBeInTheDocument();
  });
});

describe("order 14: the general reviews are in the recent table and the in-progress card", () => {
  const general = (over: Record<string, unknown> = {}) => run({
    review_run_id: "g-run-1", submittal_filename: "invented-valve.pdf", method: "general", status: "completed",
    general_counts: { points: 193, comments: 73, confirmations: 6, stopped: false }, general_signoff: "signed",
    findings_total: 0, by_status: {}, recommended_code: null, equipment_tags: [], ...over,
  });

  it("a general review shows its own comments and confirmations and whether an engineer signed it", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ recent: [general()] }) });
    panel();
    const row = (await screen.findByText("invented-valve.pdf")).closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("73 comments sent, 6 confirmations not sent");
    expect(cells[4]).toHaveTextContent("Signed off");
    expect(row).not.toHaveTextContent("earlier version");
  });

  it("not signed, changed since sign-off and stopped early are each said", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ recent: [
      general({ review_run_id: "g1", submittal_filename: "a.pdf", general_signoff: "not_signed" }),
      general({ review_run_id: "g2", submittal_filename: "b.pdf", general_signoff: "changed" }),
      general({ review_run_id: "g3", submittal_filename: "c.pdf", general_signoff: "not_signed", general_counts: { points: 5, comments: 1, stopped: true } }),
    ] }) });
    panel();
    const cell = async (name: string) => within((await screen.findByText(name)).closest("tr") as HTMLElement).getAllByRole("cell")[4];
    expect(await cell("a.pdf")).toHaveTextContent("Not signed off yet");
    expect(await cell("b.pdf")).toHaveTextContent("Changed since sign-off");
    expect(await cell("c.pdf")).toHaveTextContent("Not signed off yet (stopped early)");
  });

  it("an earlier-method row is marked as an earlier version", async () => {
    panel();
    const row = (await screen.findByText("drum.pdf")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("earlier version");
  });

  it("the in-progress card says how many signed reviews are done and keeps its boundary", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ reviews_running: 1, reviews_awaiting_decision: 2, reviews_signed: 3, papers_with_a_review: 6, earlier_runs_not_counted: 4 }) });
    panel();
    expect(await screen.findByText("1 running · 2 waiting for an engineer's sign-off or code · 3 signed off (done) · of 6 papers, latest review each · 4 earlier reviews not counted")).toBeInTheDocument();
  });

  it("the in-progress number counts only the reviews that are running: one that waits for a sign-off is not in progress (planner 19 Nov, item 8)", async () => {
    dashboard.mockResolvedValue({ ok: true, data: data({ reviews_running: 1, reviews_awaiting_decision: 7, reviews_signed: 0 }) });
    panel();
    const card = (await screen.findByText("Reviews in progress")).parentElement as HTMLElement;
    expect(within(card).getByText("1")).toBeInTheDocument();
    expect(within(card).queryByText("8")).toBeNull();
    expect(card).toHaveTextContent("7 waiting for an engineer's sign-off or code");
  });
});

