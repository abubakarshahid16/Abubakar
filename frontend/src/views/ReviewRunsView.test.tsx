import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../types/api";
import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const list = vi.fn();
const reviewRunStandards = vi.fn();

const documentApi = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    documents: (...args: unknown[]) => documents(...args),
    document: (...args: unknown[]) => documentApi(...args),
  },
  reviews: {
    // Section 3's readiness strip; not what these tests are about.
    readiness: async () => ({ ok: false, error: { message: "not in this test" } }),
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    list: (...args: unknown[]) => list(...args),
    reviewRunStandards: (...args: unknown[]) => reviewRunStandards(...args),
    reviewRunStandardsAll: (...args: unknown[]) => reviewRunStandards(...args),
    overrideRunStandard: vi.fn(),
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
  documentApi.mockReset();
  documentApi.mockResolvedValue({ ok: false, error: { message: "not in this test" } });
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

describe("2g: a run card speaks plain words", () => {
  it("shows the plain reason and no developer word", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({
      recommended_reason: "Checked 4 datasheet fields. That is not enough of the datasheet to suggest a review code yet.",
      recommended_details: NOMINAL_REASON,
    })] } });
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    const card = within(runButton);
    expect(card.getByText("Manual Review Required")).toBeInTheDocument();
    expect(card.getByText(/Checked 4 datasheet fields/)).toBeInTheDocument();
    expect(card.getAllByText(/Checked 4 datasheet fields/)).toHaveLength(1);
    expect(card.queryByText(/NOMINAL|denominator|MISSING_LOCALLY/i)).toBeNull();
  });

  it("still states the fields checked when the reason does not", async () => {
    reviewRuns.mockResolvedValue({
      ok: true,
      data: { runs: [run({ recommended_reason: "Not enough was read to recommend a code." })] },
    });
    render(<ReviewRunsView />);

    const card = within(await screen.findByRole("button", { name: /drum\.pdf/i }));
    expect(card.getByText("Checked 4 datasheet fields.")).toBeInTheDocument();
    expect(card.queryByText(/NOMINAL/i)).toBeNull();
  });
});

describe("B3: the pages a run read into fields", () => {
  it("shows on the run card which pages were not read, with the denominator", async () => {
    reviewRuns.mockResolvedValue({
      ok: true,
      data: { runs: [run({ page_coverage: {
        pages_total: 11, fact_pages: [4, 5],
        pages_not_read_into_fields: [1, 2, 3, 6, 7, 8, 9, 10, 11],
        not_read_reasons: {},
      } })] },
    });
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    const line = within(runButton).getByTestId("page-coverage");
    expect(line).toHaveTextContent("Fields read from 2 of 11 pages (pages 4-5)");
    expect(line).toHaveTextContent("pages 1-3, 6-11 not read into fields");
  });

  it("shows nothing for a run made before the page ledger existed", async () => {
    render(<ReviewRunsView />);

    const runButton = await screen.findByRole("button", { name: /drum\.pdf/i });
    expect(within(runButton).queryByTestId("page-coverage")).toBeNull();
  });
});

describe("#598: table values that were not compared", () => {
  it("shows one expandable line per standard, never dropping them silently", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({
      table_values_not_compared: [{
        standard_document_id: "std-1", standard_name: "NACE-X.pdf", count: 57,
        table_count: 2,
        line: "57 table values in 2 tables of NACE-X.pdf not compared: no matching field on this submittal",
        tables: [{ page: 4, count: 30, examples: ["UNS S32205"] },
                 { page: 9, count: 27, examples: [] }],
      }],
    })] } });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));

    const block = await screen.findByTestId("table-values-not-compared");
    expect(within(block).getByText(/57 table values in 2 tables of NACE-X\.pdf not compared/))
      .toBeInTheDocument();
    expect(within(block).getByText(/30 on page 4, for example UNS S32205/)).toBeInTheDocument();
  });

  it("shows nothing for a run with no unmatched table values", async () => {
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
    await screen.findByRole("heading", { name: "drum.pdf", level: 2 });
    expect(screen.queryByTestId("table-values-not-compared")).toBeNull();
  });
});

describe("B5: the standards in scope carry their evidence and the missing ones", () => {
  it("shows the citation line and the cited standards not held", async () => {
    reviewRunStandards.mockResolvedValue({
      ok: true,
      data: {
        standards: [{
          standard_document_id: "std-610", filename: "API-610.pdf",
          selection_method: "referenced",
          selection_reason: "named in the submittal as API 610 (page 1)",
          confidence: 0.9, included: true, exclusion_reason: null,
          evidence_page: 1, evidence_quote: "Pump shall comply with API 610 and API 682.",
          scope_decision: null,
        }],
        missing_references: [{ identifier: "API 682", status: "MISSING_LOCALLY" }],
      },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
    await userEvent.click(await screen.findByRole("button", { name: /standards in scope — why\?/i }));

    // Positive first: the applied standard and its reason rendered.
    expect(await screen.findByText("API-610.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Evidence, page 1: “Pump shall comply with API 610 and API 682\.”/))
      .toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(within(note).getByText(/not held locally - not checked \(1\)/)).toBeInTheDocument();
    expect(within(note).getByText("API 682")).toBeInTheDocument();
  });

  it("names the missing standards even when nothing was selected", async () => {
    reviewRunStandards.mockResolvedValue({
      ok: true,
      data: { standards: [], missing_references: [{ identifier: "API 682", status: "MISSING_LOCALLY" }] },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
    await userEvent.click(await screen.findByRole("button", { name: /standards in scope — why\?/i }));

    expect(await screen.findByText("No standards were selected for this run.")).toBeInTheDocument();
    expect(within(screen.getByRole("note")).getByText("API 682")).toBeInTheDocument();
  });
});

describe("2g: the picker and the panel always name the same document", () => {
  const docs = [
    { id: "doc-sub", filename: "drum.pdf", document_role: "CONTRACTOR_SUBMITTAL" },
    { id: "doc-pump", filename: "pump.pdf", document_role: "CONTRACTOR_SUBMITTAL" },
    { id: "doc-new", filename: "new.pdf", document_role: "CONTRACTOR_SUBMITTAL" },
  ];

  beforeEach(() => {
    documents.mockImplementation(async (params: { document_role?: string[] }) => ({
      ok: true,
      data: params?.document_role?.includes("CONTRACTOR_SUBMITTAL") ? docs : [],
    }));
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [
      run(),
      run({ review_run_id: "run-2", submittal_document_id: "doc-pump",
            submittal_filename: "pump.pdf", created_at: "2026-09-21T00:00:00Z" }),
    ] } });
  });

  it("opening a run sets the picker to its submittal", async () => {
    render(<ReviewRunsView />);
    await screen.findByRole("option", { name: "pump.pdf" });
    await userEvent.click(await screen.findByRole("button", { name: /pump\.pdf/i }));
    expect(await screen.findByRole("heading", { name: "pump.pdf", level: 2 })).toBeInTheDocument();
    expect(screen.getByLabelText("Submittal")).toHaveValue("doc-pump");
  });

  it("choosing a submittal opens its latest run, and one with no run closes the panel", async () => {
    render(<ReviewRunsView />);
    await screen.findByRole("option", { name: "drum.pdf" });
    await userEvent.click(await screen.findByRole("button", { name: /pump\.pdf/i }));
    await screen.findByRole("heading", { name: "pump.pdf", level: 2 });

    await userEvent.selectOptions(screen.getByLabelText("Submittal"), "doc-sub");
    expect(await screen.findByRole("heading", { name: "drum.pdf", level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "pump.pdf", level: 2 })).toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("Submittal"), "doc-new");
    expect(screen.queryByRole("heading", { name: "drum.pdf", level: 2 })).toBeNull();
    expect(screen.getByLabelText("Submittal")).toHaveValue("doc-new");
  });
});

describe("UX GROUP (2026-09-27): the finding detail panel", () => {
  // jsdom implements no scrollIntoView; installed per-test so this test
  // cannot pass on some other test's leftover spy, and removed after so it
  // cannot leave one behind either.
  afterEach(() => {
    delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
  });

  it("scrolls into view when a finding is selected, wherever the table put it", async () => {
    list.mockResolvedValue({
      ok: true,
      data: { findings: [{ id: "f1", document_id: "doc-sub", finding: "x",
        compliance_status: "NON_COMPLIANT", requirement: "A requirement." }] },
    });
    const spy = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      value: spy, writable: true, configurable: true,
    });

    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
    await userEvent.click(await screen.findByText("A requirement."));

    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ block: "nearest" }));
  });
});

describe("audit 2026-09-30: the review screen does not turn a failure into an empty answer", () => {
  it("says the standards could not be loaded, not that none were selected", async () => {
    reviewRunStandards.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "internal_error", message: "the standards list failed" },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
    await userEvent.click(await screen.findByRole("button", { name: /standards in scope — why\?/i }));

    const alert = await screen.findByText(/The standards for this run could not be loaded/);
    expect(alert).toHaveTextContent("the standards list failed");
    expect(screen.queryByText("No standards were selected for this run.")).toBeNull();
    expect(screen.queryByText(/Loading standards/)).toBeNull();
  });

  it("labels the run card's code as the AI's and unconfirmed", async () => {
    render(<ReviewRunsView />);
    const card = await screen.findByRole("button", { name: /drum\.pdf/i });
    const line = within(card).getByTestId("run-card-recommended");
    expect(line).toHaveTextContent(/AI recommended: Manual Review Required/);
    expect(line).toHaveTextContent("Not confirmed by an engineer yet.");
    expect(within(card).queryByTestId("run-card-final")).toBeNull();
  });

  it("shows the engineer's final code beside the AI's, never instead", async () => {
    reviewRuns.mockResolvedValue({
      ok: true, data: { runs: [run({ engineer_final_code: "Approved with Comments" })] },
    });
    render(<ReviewRunsView />);
    const card = await screen.findByRole("button", { name: /drum\.pdf/i });
    expect(within(card).getByTestId("run-card-recommended"))
      .toHaveTextContent(/AI recommended: Manual Review Required/);
    expect(within(card).getByTestId("run-card-recommended"))
      .not.toHaveTextContent("Not confirmed");
    expect(within(card).getByTestId("run-card-final"))
      .toHaveTextContent("Engineer's final code: Approved with Comments");
  });

  it("shows the run's status in plain words, not the database value", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "cancelled" })] } });
    render(<ReviewRunsView />);
    const card = await screen.findByRole("button", { name: /drum\.pdf/i });
    expect(card).toHaveTextContent("standards in scope · Cancelled");
    expect(card).not.toHaveTextContent(/status cancelled/);
  });
});
