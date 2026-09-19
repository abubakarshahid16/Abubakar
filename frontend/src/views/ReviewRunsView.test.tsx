import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../types/api";
import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const list = vi.fn();
const reviewRunStandards = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    list: (...args: unknown[]) => list(...args),
    reviewRunStandards: (...args: unknown[]) => reviewRunStandards(...args),
    startReviewRun: vi.fn(),
    exportCrs: vi.fn(),
    decideCode: vi.fn(),
  },
}));

const NOMINAL_REASON =
  "The review used a NOMINAL ESTIMATE denominator because field count is unknown.";

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1",
    submittal_document_id: "doc-sub",
    submittal_filename: "drum.pdf",
    equipment_tags: ["V-101"],
    status: "completed",
    created_at: "2026-09-20T00:00:00Z",
    completed_at: "2026-09-20T00:01:00Z",
    standards_in_scope: 2,
    findings_total: 1,
    by_status: { MISSING_INFORMATION: 1 },
    recommended_code: "Manual Review Required",
    recommended_reason: NOMINAL_REASON,
    completeness: {
      fields_read: 4,
      fields_estimated: 35,
      pages: 1,
      sufficient: false,
    },
    ...over,
  } as ReviewRunSummary;
}

beforeEach(() => {
  documents.mockReset();
  reviewRuns.mockReset();
  list.mockReset();
  reviewRunStandards.mockReset();
  documents.mockResolvedValue({ ok: true, data: [] });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run()] } });
  list.mockResolvedValue({ ok: true, data: { findings: [] } });
  reviewRunStandards.mockResolvedValue({ ok: true, data: { standards: [] } });
});

describe("selected review run placement", () => {
  it("renders the selected findings section before the runs list in DOM order", async () => {
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    const runsHeading = screen.getByRole("heading", { name: "1 run" });
    expect(runButton).toBeInTheDocument();
    expect(runsHeading).toBeInTheDocument();

    await userEvent.click(runButton);

    const findingsHeading = await screen.findByRole(
      "heading", { name: "drum.pdf", level: 2 });
    const findingsSection = findingsHeading.closest("section");
    const runsSection = runsHeading.closest("section");
    expect(findingsSection).not.toBeNull();
    expect(runsSection).not.toBeNull();
    expect(findingsSection!.compareDocumentPosition(runsSection!))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});

describe("nominal-estimate reason on a run card", () => {
  it("renders the existing NOMINAL ESTIMATE sentence exactly once", async () => {
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    const card = within(runButton);
    // Positive branch proofs: the card and its recommendation rendered, so
    // the absence below is an absence FROM something that exists.
    expect(card.getByText("Manual Review Required")).toBeInTheDocument();
    expect(card.getByText(/The review used a NOMINAL ESTIMATE denominator/))
      .toBeInTheDocument();
    expect(card.getAllByText(/NOMINAL ESTIMATE/i)).toHaveLength(1);
    // THE COMPLETENESS LINE'S OWN WORDS, which `completenessLine` emits as
    // "4 of approximately 35 fields (a NOMINAL estimate: ...)".
    //
    // This asserted `queryByText(/fields read/i)` and was VACUOUS: with
    // `fields_estimated` set, that line never says "fields read" - it says
    // "of approximately" - so the assertion held whether or not the branch
    // rendered. The test below renders the branch, which is what makes this
    // absence mean something.
    expect(card.queryByText(/of approximately/i)).toBeNull();
  });

  it("still shows the completeness line when the reason does NOT state the denominator", async () => {
    // THE POSITIVE CONTROL FOR THE ABSENCE ABOVE. Same component, same
    // completeness input, one field changed: the denominator is never
    // dropped, only never repeated. Without this, "the line is absent" could
    // mean the line does not exist at all.
    reviewRuns.mockResolvedValue({
      ok: true,
      data: { runs: [run({ recommended_reason: "Not enough was read to recommend a code." })] },
    });
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    const card = within(runButton);

    expect(card.getByText(/of approximately 35 fields/i)).toBeInTheDocument();
    expect(card.getAllByText(/NOMINAL/i)).toHaveLength(1);
  });
});
