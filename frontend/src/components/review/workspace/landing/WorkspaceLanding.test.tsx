/**
 * v2.1: the Submittals first page with the switch on (L1-L9, W5).
 * Made-up sample data only.
 *
 * MUTATION PROOF (checked by hand once): take <StartReviewBar> out of the
 * New review card, or make "Start review" open the latest run instead of
 * starting, and "L1: Start review ALWAYS starts a fresh review" fails; drop
 * the `watchRun` call in `reviewAll` and "L7" fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";

const startReviewRun = vi.fn();
const readiness = vi.fn();
const cancelJob = vi.fn();
const reviewRunCounts = vi.fn();
const watchRun = vi.fn();

vi.mock("../../../../api/client", () => ({
  api: {},
  auth: { me: async () => ({ ok: true, data: { required: true, user: { id: "u-1", roles: ["admin"] } } }) },
  classification: {},
  reviews: {
    startReviewRun: (...a: unknown[]) => startReviewRun(...a),
    readiness: (...a: unknown[]) => readiness(...a),
    cancelJob: (...a: unknown[]) => cancelJob(...a),
    reviewRunCounts: (...a: unknown[]) => reviewRunCounts(...a),
    reviewRuns: async () => ({ ok: true, data: { runs: [] } }),
  },
}));
vi.mock("../reviewWatch", () => ({ watchRun: (...a: unknown[]) => watchRun(...a) }));
vi.mock("../NewReviewDropZone", () => ({
  NewReviewDropZone: ({ isAdmin }: { isAdmin?: boolean }) => <p data-testid="drop-zone">{`admin: ${String(isAdmin)}`}</p>,
}));

import { NOT_ADMIN_LANDING_MESSAGE, WorkspaceLanding } from "./WorkspaceLanding";

function run(over: Partial<ReviewRunSummary>): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T08:00:00Z", completed_at: null,
    standards_in_scope: 1, findings_total: 0, by_status: {}, recommended_code: null, recommended_reason: null, completeness: null,
    ...over,
  } as ReviewRunSummary;
}
const doc = (id: string, filename: string, uploaded_at = "2026-09-01T08:00:00Z") =>
  ({ id, filename, uploaded_at, indexed_at: null, document_role: "CONTRACTOR_SUBMITTAL" }) as DocumentRecord;

const DOCS = [
  doc("doc-1", "Pump datasheet rev B.pdf"),
  doc("doc-2", "Valve list.pdf"),
  doc("doc-3", "Motor sheet.pdf"),
  doc("doc-4", "Heat exchanger sheet.pdf"),
];
const RUNS = [
  run({ review_run_id: "run-1", submittal_document_id: "doc-1", created_at: "2026-10-01T08:00:00Z" }),
  run({ review_run_id: "run-0", submittal_document_id: "doc-1", created_at: "2026-09-20T08:00:00Z", crs_issued_at: "2026-09-21T08:00:00Z" }),
  run({ review_run_id: "run-2", submittal_document_id: "doc-2", created_at: "2026-10-05T08:00:00Z", status: "failed", failure_reason: "The file could not be opened." }),
  run({
    review_run_id: "run-3", submittal_document_id: "doc-3", created_at: "2026-10-07T08:00:00Z", status: "running",
    job: { id: "job-3", state: "running", progress_done: 2, progress_total: 5, progress_label: "Comparing with the standards", cancel_requested: false },
  }),
];

const loadCounts = vi.fn();

beforeEach(() => {
  for (const m of [startReviewRun, readiness, cancelJob, reviewRunCounts, watchRun, loadCounts]) m.mockReset();
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-new", submittal_filename: "Pump datasheet rev B.pdf" } });
  readiness.mockResolvedValue({ ok: true, data: { nothing_changed: false } });
  cancelJob.mockResolvedValue({ ok: true, data: {} });
  loadCounts.mockResolvedValue({ "run-1": { findings: 12, needs_you: 3 } });
});

function renderLanding(over: Partial<Parameters<typeof WorkspaceLanding>[0]> = {}) {
  const onOpenRun = vi.fn();
  const onReload = vi.fn();
  render(
    <WorkspaceLanding
      documents={DOCS} runs={RUNS} submittalsTotal={4} onOpenRun={onOpenRun} onReload={onReload}
      loadReadyCounts={loadCounts} isAdmin {...over}
    />,
  );
  return { onOpenRun, onReload };
}

const rowOf = (name: string) => screen.getAllByTestId("landing-row").find((r) => r.textContent?.includes(name))!;

describe("WorkspaceLanding: the New review card (L1)", () => {
  it("holds the searchable list of every contractor submittal and the drop zone", async () => {
    renderLanding();
    const card = screen.getByTestId("new-review-card");
    expect(within(card).getByTestId("drop-zone")).toHaveTextContent("admin: true");
    const select = within(card).getByLabelText("Choose a submittal");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose one of 4", "Heat exchanger sheet.pdf", "Motor sheet.pdf", "Pump datasheet rev B.pdf", "Valve list.pdf",
    ]);
    await userEvent.type(within(card).getByLabelText("Find a submittal by file name"), "valve");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose one of 1", "Valve list.pdf"]);
    expect(within(card).getByRole("button", { name: "Start review" })).toBeDisabled();
  });

  it("L1: Start review ALWAYS starts a fresh review (even of a reviewed document), watches it and opens it", async () => {
    const { onOpenRun } = renderLanding();
    const card = screen.getByTestId("new-review-card");
    await userEvent.selectOptions(within(card).getByLabelText("Choose a submittal"), "doc-1");
    await userEvent.click(within(card).getByRole("button", { name: "Start review" }));
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-new"));
    expect(startReviewRun).toHaveBeenCalledWith("doc-1");
    expect(onOpenRun).not.toHaveBeenCalledWith("run-1");
    expect(watchRun).toHaveBeenCalledWith("run-new", "Pump datasheet rev B.pdf"); // L6
  });

  it("asks first when nothing changed since the latest review; Cancel starts nothing", async () => {
    readiness.mockResolvedValue({ ok: true, data: { nothing_changed: true } });
    renderLanding();
    const card = screen.getByTestId("new-review-card");
    await userEvent.selectOptions(within(card).getByLabelText("Choose a submittal"), "doc-1");
    await userEvent.click(within(card).getByRole("button", { name: "Start review" }));
    expect(await within(card).findByText(/Nothing has changed since the latest review/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Cancel" }));
    expect(startReviewRun).not.toHaveBeenCalled();
  });
});

describe("WorkspaceLanding: the rows (L2, L3, L4, L9)", () => {
  it("L4: rows are newest activity first, and the search filters by file name", async () => {
    renderLanding();
    expect(screen.getAllByTestId("landing-row").map((r) => r.querySelector("p")?.textContent)).toEqual([
      "Motor sheet.pdf", "Valve list.pdf", "Pump datasheet rev B.pdf", "Heat exchanger sheet.pdf",
    ]);
    await userEvent.type(screen.getByLabelText("Search by file name"), "PUMP");
    expect(screen.getAllByTestId("landing-row")).toHaveLength(1);
    await userEvent.clear(screen.getByLabelText("Search by file name"));
    await userEvent.type(screen.getByLabelText("Search by file name"), "nothing like this");
    expect(screen.getByTestId("landing-no-match")).toBeInTheDocument();
  });

  it("L3: plain chips with counts from one counts request; unknown counts show no number", async () => {
    renderLanding();
    await waitFor(() => expect(within(rowOf("Pump")).getByTestId("status-chip")).toHaveTextContent("3 need you"));
    expect(loadCounts).toHaveBeenCalledTimes(1);
    expect(loadCounts).toHaveBeenCalledWith(["run-1"]);
    expect(within(rowOf("Pump")).getByTestId("row-counts")).toHaveTextContent("12 findings to decide");
    expect(within(rowOf("Heat exchanger")).getByTestId("status-chip")).toHaveTextContent("Not reviewed");
  });

  it("L3: a Ready row whose counts failed says Ready, never 0", async () => {
    loadCounts.mockResolvedValue({ "run-1": null });
    renderLanding();
    await waitFor(() => expect(loadCounts).toHaveBeenCalled());
    expect(within(rowOf("Pump")).getByTestId("status-chip")).toHaveTextContent(/^Ready$/);
    expect(within(rowOf("Pump")).queryByTestId("row-counts")).toBeNull();
  });

  it("L2: Open opens the latest review; New review starts a fresh one", async () => {
    const { onOpenRun } = renderLanding();
    await userEvent.click(within(rowOf("Pump")).getByRole("button", { name: "Open the latest review of Pump datasheet rev B.pdf" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
    expect(startReviewRun).not.toHaveBeenCalled();
    await userEvent.click(within(rowOf("Pump")).getByRole("button", { name: "New review of Pump datasheet rev B.pdf" }));
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-new"));
    expect(watchRun).toHaveBeenCalledWith("run-new", "Pump datasheet rev B.pdf");
  });

  it("L2: New review asks first when the latest review carries a final code", async () => {
    const coded = [run({ review_run_id: "run-1", submittal_document_id: "doc-1", engineer_final_code: "Approved with Comments" })];
    renderLanding({ runs: coded });
    await userEvent.click(within(rowOf("Pump")).getByRole("button", { name: "New review of Pump datasheet rev B.pdf" }));
    expect(await within(rowOf("Pump")).findByText(/final code "Approved with Comments"/)).toBeInTheDocument();
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("L9: a failed row says why; a running row says its step and offers Cancel", async () => {
    const { onReload } = renderLanding();
    expect(within(rowOf("Valve")).getByTestId("status-chip")).toHaveTextContent("Failed: The file could not be opened.");
    const running = rowOf("Motor");
    expect(within(running).getByTestId("status-chip")).toHaveTextContent("Running (step 3 of 5)");
    expect(within(running).getByTestId("row-step")).toHaveTextContent("Comparing with the standards");
    expect(within(running).queryByRole("button", { name: /New review/ })).toBeNull();
    await userEvent.click(within(running).getByRole("button", { name: "Cancel this review" }));
    expect(cancelJob).toHaveBeenCalledWith("job-3");
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });

  it("W5: Past reviews (N) folds out under a reviewed row", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: { "run-1": { comment: 4, needs_you: 2 } } } });
    renderLanding();
    await userEvent.click(within(rowOf("Pump")).getByRole("button", { name: "Past reviews (2)" }));
    const list = within(rowOf("Pump")).getByRole("list", { name: "Past reviews" });
    expect(await within(list).findByText("6 findings, 2 need you")).toBeInTheDocument();
    expect(within(list).getByText("Signed")).toBeInTheDocument();
  });
});

describe("WorkspaceLanding: All reviews and Review all (L5, L7)", () => {
  it("L5: All reviews (N) shows every review, newest first, each with Open", async () => {
    const { onOpenRun } = renderLanding();
    await userEvent.click(screen.getByRole("button", { name: "All reviews (4)" }));
    const list = screen.getByRole("list", { name: "All reviews" });
    const rows = within(list).getAllByTestId("all-reviews-row");
    expect(rows.map((r) => r.querySelector("p")?.textContent)).toEqual([
      "Motor sheet.pdf", "Valve list.pdf", "Pump datasheet rev B.pdf", "Pump datasheet rev B.pdf",
    ]);
    expect(within(rows[3]).getByTestId("status-chip")).toHaveTextContent("Signed");
    await userEvent.click(within(rows[3]).getByRole("button", { name: /^Open the review of Pump datasheet rev B.pdf/ }));
    expect(onOpenRun).toHaveBeenCalledWith("run-0");
  });

  it("L7: Review all not reviewed queues each, watches each, reports refusals, and re-reads the list", async () => {
    const docs = [...DOCS, doc("doc-5", "Compressor sheet.pdf")];
    startReviewRun.mockImplementation(async (id: string) => (id === "doc-5"
      ? { ok: false, disconnected: false, error: { code: "conflict", message: "A review is already queued or running (run-x)." } }
      : { ok: true, data: { review_run_id: `run-${id}`, submittal_filename: null } }));
    const { onReload, onOpenRun } = renderLanding({ documents: docs });
    await userEvent.click(screen.getByRole("button", { name: "Review all not reviewed (2)" }));
    expect(await screen.findByText("Queued 1 of 2 reviews asked for.")).toBeInTheDocument();
    expect(screen.getByText(/Compressor sheet.pdf: A review of this document is already running./)).toBeInTheDocument();
    expect(watchRun).toHaveBeenCalledTimes(1);
    expect(watchRun).toHaveBeenCalledWith("run-doc-4", "Heat exchanger sheet.pdf");
    expect(onReload).toHaveBeenCalled();
    expect(onOpenRun).not.toHaveBeenCalled();
  });
});

describe("WorkspaceLanding: who may start (admin only) and the empty page (L8)", () => {
  it("a non-administrator sees a plain message and no start, upload or cancel; Open still works", () => {
    const { onOpenRun } = renderLanding({ isAdmin: false });
    expect(screen.getByTestId("not-admin-message")).toHaveTextContent(NOT_ADMIN_LANDING_MESSAGE);
    expect(screen.queryByTestId("drop-zone")).toBeNull();
    expect(screen.queryByTestId("start-review-bar")).toBeNull();
    expect(screen.queryByRole("button", { name: /New review of/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Review all not reviewed/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel this review" })).toBeNull();
    within(rowOf("Pump")).getByRole("button", { name: "Open the latest review of Pump datasheet rev B.pdf" }).click();
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
  });

  it("L8: with nothing yet, the page points to the New review card, not the Documents page", () => {
    renderLanding({ documents: [], runs: [] });
    expect(screen.getByTestId("landing-empty")).toHaveTextContent("Start one with the New review card above");
    expect(screen.getByTestId("landing-empty")).not.toHaveTextContent("Documents page");
  });
});
