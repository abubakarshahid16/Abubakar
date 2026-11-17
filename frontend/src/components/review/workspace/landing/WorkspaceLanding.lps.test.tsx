/**
 * Order 14 LPS: the review list (S1 contract papers and packages in the picker; S2 the "Found by the review" note follows the page's
 * numbers). Invented names and numbers only.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";

const startReviewRun = vi.fn();
const planFor = vi.fn();
const contractPapers = vi.fn();
vi.mock("../../../../api/client", () => ({
  api: {},
  auth: { me: async () => ({ ok: true, data: { required: true, user: { id: "u-1", roles: ["admin"] } } }) },
  classification: {},
  reviews: {
    readiness: async () => ({ ok: true, data: { nothing_changed: false } }),
    cancelJob: async () => ({ ok: true, data: {} }),
    reviewRunCounts: async () => ({ ok: true, data: { counts: {} } }),
    reviewRuns: async () => ({ ok: true, data: { runs: [] } }),
  },
}));
vi.mock("../../../../api/reviewPlan", () => ({
  reviewPlan: {
    plan: (...a: unknown[]) => planFor(...a), start: (...a: unknown[]) => startReviewRun(...a), contractPapers: () => contractPapers(),
  },
}));
vi.mock("../reviewWatch", () => ({ watchRun: () => undefined }));
vi.mock("../NewReviewDropZone", () => ({ NewReviewDropZone: () => <p data-testid="drop-zone" /> }));

import { LANDING_COUNTS_NOTE, LANDING_PAGE_COUNTS_NOTE, WorkspaceLanding } from "./WorkspaceLanding";
import { VIEW_MODE_KEY } from "../useViewMode";

const run = (over: Partial<ReviewRunSummary>) => ({
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Invented pump sheet.pdf", equipment_tags: [],
  status: "completed", created_at: "2026-10-01T08:00:00Z", completed_at: null, standards_in_scope: 1, findings_total: 0, by_status: {},
  recommended_code: null, recommended_reason: null, completeness: null, ...over,
}) as ReviewRunSummary;
const doc = (id: string, filename: string) =>
  ({ id, filename, uploaded_at: "2026-09-01T08:00:00Z", indexed_at: null, document_role: "CONTRACTOR_SUBMITTAL" }) as DocumentRecord;
const DOCS = [doc("doc-1", "Invented pump sheet.pdf")];
const CONTRACTS = {
  boundary: "4 contract papers you may read",
  papers: [
    // the server's order: by file name
    { document_id: "c-1", filename: "Invented agreement.pdf" },
    { document_id: "c-9", filename: "Invented lone memo.pdf" },
    { document_id: "c-2", filename: "Invented schedule P.pdf" },
    { document_id: "c-3", filename: "Invented schedule Q.pdf" },
  ],
  packages: [{ number: "QX-1", papers: ["c-1", "c-2", "c-3"] }],
};
const PAGE = { not_met: 1, questions: 72, met: 1, does_not_apply: 53, to_confirm: 42, points: 169, undecided: 169, runs: { rule_check: null, ai_review: "run-1" } };

beforeEach(() => {
  for (const m of [startReviewRun, planFor, contractPapers]) m.mockReset();
  planFor.mockResolvedValue({ ok: true, data: { choice: "automatic", parts: [], text_leaves: false, refused: null,
    documents: { leaving: [], not_sent: [], not_readable: 0 } } });
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-new", submittal_filename: "Invented schedule P.pdf" } });
  contractPapers.mockResolvedValue({ ok: true, data: CONTRACTS });
  localStorage.clear();
  localStorage.setItem(VIEW_MODE_KEY, "detailed");
});

function renderLanding(loadReadyCounts = vi.fn().mockResolvedValue({ "run-1": null })) {
  const onOpenRun = vi.fn();
  render(
    <WorkspaceLanding documents={DOCS} runs={[run({})]} submittalsTotal={1} onOpenRun={onOpenRun} onReload={vi.fn()}
      loadReadyCounts={loadReadyCounts} isAdmin />,
  );
  return { onOpenRun };
}

describe("LPS S1: contract papers and whole packages can be chosen; each start is the one pre-start step", () => {
  it("offers the submittals, the contract packages and every contract paper, each under its own heading", async () => {
    renderLanding();
    const card = screen.getByTestId("new-review-card");
    const select = within(card).getByLabelText("Choose a submittal");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(7));
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose one of 6", "Invented pump sheet.pdf", "Contract package QX-1: 3 papers",
      "Invented agreement.pdf", "Invented lone memo.pdf", "Invented schedule P.pdf", "Invented schedule Q.pdf",
    ]);
    expect([...select.querySelectorAll("optgroup")].map((g) => g.label)).toEqual([
      "Contractor submittals", "Contract packages (each paper is reviewed on its own)", "Contract papers",
    ]);
    expect(within(card).getByTestId("contract-papers-boundary")).toHaveTextContent("4 contract papers you may read");
  });

  it("a contract paper starts through the pre-start step: the plan first, then the start with the list shown", async () => {
    const { onOpenRun } = renderLanding();
    const card = screen.getByTestId("new-review-card");
    await waitFor(() => expect(within(card).getByRole("option", { name: "Invented lone memo.pdf" })).toBeInTheDocument());
    await userEvent.selectOptions(within(card).getByLabelText("Choose a submittal"), "c-9");
    await userEvent.click(within(card).getByRole("button", { name: "Start review" }));
    expect(await within(card).findByTestId("start-review-step")).toBeInTheDocument();
    expect(planFor).toHaveBeenCalledWith("c-9", "automatic");
    expect(startReviewRun).not.toHaveBeenCalled(); // nothing starts before the list is shown
    await userEvent.click(await within(card).findByRole("button", { name: "Start review" }));
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-new"));
    expect(startReviewRun).toHaveBeenCalledWith("c-9", "automatic", []);
  });

  it("a package lists its papers, each with its own Start review that opens that paper's own pre-start step", async () => {
    renderLanding();
    const card = screen.getByTestId("new-review-card");
    await waitFor(() => expect(within(card).getByRole("option", { name: "Contract package QX-1: 3 papers" })).toBeInTheDocument());
    await userEvent.selectOptions(within(card).getByLabelText("Choose a submittal"), "package:0");
    const box = within(card).getByTestId("package-papers");
    expect(within(box).getAllByRole("listitem").map((li) => li.textContent?.replace("Start review", "").trim())).toEqual([
      "Invented agreement.pdf", "Invented schedule P.pdf", "Invented schedule Q.pdf",
    ]);
    expect(within(card).queryByRole("button", { name: "Start review" })).toBeNull(); // a package id never gets a Start button of its own
    expect(box).toHaveTextContent("Each paper is reviewed on its own");
    expect(box).toHaveTextContent("Automatic keeps a contract on this computer");
    await userEvent.click(within(box).getByRole("button", { name: "Start review of Invented schedule P.pdf" }));
    expect(await within(box).findByTestId("start-review-step")).toBeInTheDocument();
    expect(planFor).toHaveBeenCalledWith("c-2", "automatic");
    expect(planFor).not.toHaveBeenCalledWith("c-1", expect.anything());
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("without contract papers the picker is as before", async () => {
    contractPapers.mockResolvedValue({ ok: true, data: { boundary: "0 contract papers you may read", papers: [], packages: [] } });
    renderLanding();
    await waitFor(() => expect(contractPapers).toHaveBeenCalled());
    const select = within(screen.getByTestId("new-review-card")).getByLabelText("Choose a submittal");
    expect(select.querySelectorAll("optgroup")).toHaveLength(0);
    expect(screen.queryByTestId("contract-papers-boundary")).toBeNull();
  });
});

describe("LPS S2: the review list says what the paper's page shows", () => {
  it("a row says the page's tiles and the note says they are the page's numbers", async () => {
    renderLanding(vi.fn().mockResolvedValue({ "run-1": { findings: 73, needs_you: 72, page: PAGE } }));
    const note = await screen.findByTestId("landing-counts-note");
    expect(note).toHaveTextContent(LANDING_PAGE_COUNTS_NOTE);
    expect(note).not.toHaveTextContent(LANDING_COUNTS_NOTE);
    expect(screen.getByTestId("row-counts")).toHaveTextContent(
      "Found by the review: 1 not met, 72 questions for you (169 points on its review page, 169 not decided yet)",
    );
  });
});
