/**
 * The in-app CRS preview: the deliverable, on screen, beside the download.
 *
 * WHY IT EXISTS. The only way to see the Comment Resolution Sheet was to
 * press Export and open the file in Excel - in front of a client, leaving the
 * application to show what the application produces.
 *
 * WHAT THESE TESTS HOLD. That the panel shows the SHEET (its header block,
 * its seven columns, its rows and the recommended review code) rather than a
 * summary of it; that the contractor's two columns are present and empty,
 * because they are the contractor's to fill; and that the download still
 * works exactly as it did - a viewing feature that broke the deliverable
 * would be a bad trade.
 *
 * The backend's `test_the_preview_is_the_workbook_row_for_row` holds the
 * other half: that what this screen renders is what the .xlsx says.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsPreview, ReviewRunSummary } from "../types/api";
import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const list = vi.fn();
const reviewRunStandards = vi.fn();
const previewCrs = vi.fn();
const exportCrs = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    list: (...args: unknown[]) => list(...args),
    reviewRunStandards: (...args: unknown[]) => reviewRunStandards(...args),
    previewCrs: (...args: unknown[]) => previewCrs(...args),
    exportCrs: (...args: unknown[]) => exportCrs(...args),
    startReviewRun: vi.fn(),
    decideCode: vi.fn(),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1",
    submittal_document_id: "doc-sub",
    submittal_filename: "drum.pdf",
    equipment_tags: [],
    status: "completed",
    created_at: "2026-09-20T00:00:00Z",
    completed_at: "2026-09-20T00:01:00Z",
    standards_in_scope: 2,
    findings_total: 1,
    by_status: { NON_COMPLIANT: 1 },
    recommended_code: "Manual Review Required",
    recommended_reason: "the review examined 42 of approximately 385 fields",
    ...over,
  } as ReviewRunSummary;
}

/** A preview body shaped exactly as the route returns one. */
function sheet(over: Partial<CrsPreview> = {}): CrsPreview {
  return {
    title: "AL-KHAFJI JOINT OPERATIONS (KJO)",
    subtitle: "COMMENT RESOLUTION SHEET",
    header: [
      { label: "COMPANY Transmittal No.:", value: "" },
      { label: "CONTRACTOR  Transmittal No.:", value: "" },
      { label: "Document Title:", value: "drum.pdf" },
      { label: "Date Issued:", value: "2026-09-20" },
      { label: "Date Responded", value: "" },
    ],
    columns: ["Item No", "Document Name", "Page No./Section",
              "COMPANY Comments", "Comment By", "Contractor's Response",
              "Final Resolution"],
    rows: [
      {
        item_no: 1,
        document_name: "drum.pdf",
        page_section: "SAES-D-001.pdf clause 6.2.2 p14 / submittal p4",
        comment: "Requirement: The design pressure shall be 6,900 kPa.",
        comment_by: "AI Review",
        contractor_response: "",
        final_resolution: "",
      },
      {
        item_no: 2,
        document_name: "drum.pdf",
        page_section: "References",
        comment: "Referenced standard 32-SAMSS-004 is cited by this submittal "
                 + "but is not in the standards library for this review.",
        comment_by: "AI Review",
        contractor_response: "",
        final_resolution: "",
      },
    ],
    recommended_code: "Manual Review Required",
    recommended_code_reason: "the review examined 42 of approximately 385 fields",
    recommended_code_label: "Recommended Review Code:",
    ...over,
  };
}

async function openThePreview() {
  render(<ReviewRunsView />);
  await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));
  await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
  return screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
}

beforeEach(() => {
  documents.mockReset();
  reviewRuns.mockReset();
  list.mockReset();
  reviewRunStandards.mockReset();
  previewCrs.mockReset();
  exportCrs.mockReset();
  documents.mockResolvedValue({ ok: true, data: [] });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run()] } });
  list.mockResolvedValue({ ok: true, data: { findings: [] } });
  reviewRunStandards.mockResolvedValue({ ok: true, data: { standards: [] } });
  previewCrs.mockResolvedValue({ ok: true, data: sheet() });
});

describe("the CRS preview", () => {
  it("is not fetched until the reader asks for it", async () => {
    render(<ReviewRunsView />);

    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));

    expect(previewCrs).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i }))
      .toBeNull();
  });

  it("renders the header block the workbook prints, labels and all", async () => {
    const panel = within(await openThePreview());

    expect(previewCrs).toHaveBeenCalledWith("run-1");
    expect(panel.getByText(/AL-KHAFJI JOINT OPERATIONS/)).toBeInTheDocument();
    expect(panel.getByText("COMMENT RESOLUTION SHEET")).toBeInTheDocument();
    // THE VALUE UNDER ITS OWN LABEL. "drum.pdf" is also the Document Name of
    // every row, so a bare text query would pass on a header block that never
    // rendered - it is read off the label's own definition instead.
    expect(panel.getByText("Document Title:").nextElementSibling)
      .toHaveTextContent("drum.pdf");
    expect(panel.getByText("Date Issued:").nextElementSibling)
      .toHaveTextContent("2026-09-20");
    // BLANK IS BLANK. Nobody has issued a transmittal number, and the label
    // stands over an empty value rather than over an invented one.
    expect(panel.getByText("COMPANY Transmittal No.:").nextElementSibling)
      .toBeEmptyDOMElement();
    expect(panel.queryByText(/N\/A|TBD|pending/i)).toBeNull();
  });

  it("renders the seven columns of the client's template, in order", async () => {
    const panel = within(await openThePreview());

    expect(panel.getAllByRole("columnheader").map((th) => th.textContent))
      .toEqual(["Item No", "Document Name", "Page No./Section",
                "COMPANY Comments", "Comment By", "Contractor's Response",
                "Final Resolution"]);
  });

  it("renders one row per comment, with its citation and its text", async () => {
    const panel = within(await openThePreview());

    const rows = panel.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const first = within(rows[0]);
    expect(first.getByText("1")).toBeInTheDocument();
    expect(first.getByText(/SAES-D-001\.pdf clause 6\.2\.2 p14/)).toBeInTheDocument();
    expect(first.getByText(/The design pressure shall be 6,900 kPa\./))
      .toBeInTheDocument();
    expect(first.getByText("AI Review")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/32-SAMSS-004/)).toBeInTheDocument();
  });

  it("leaves the contractor's two columns present and empty", async () => {
    // THEY BELONG TO THE CONTRACTOR. Omitting them would hide the shape of
    // the document they are being asked to answer; writing anything in them
    // would put words in their mouth.
    const panel = within(await openThePreview());

    for (const row of panel.getAllByRole("row").slice(1)) {
      const cells = within(row).getAllByRole("cell");
      expect(cells).toHaveLength(7);
      expect(cells[5].textContent).toBe("");
      expect(cells[6].textContent).toBe("");
    }
  });

  it("shows the recommended review code and its reason", async () => {
    const panel = within(await openThePreview());

    expect(panel.getByText("Recommended Review Code:")).toBeInTheDocument();
    expect(panel.getByText("Manual Review Required")).toBeInTheDocument();
    expect(panel.getByText(/42 of approximately 385 fields/)).toBeInTheDocument();
  });

  it("shows no code line at all when the run has no recommendation", async () => {
    // NULL RENDERS AS NOTHING (CLAUDE.md rule 4), never a placeholder code.
    previewCrs.mockResolvedValue({
      ok: true,
      data: sheet({ recommended_code: "", recommended_code_reason: "" }),
    });

    const panel = within(await openThePreview());

    expect(panel.queryByText("Recommended Review Code:")).toBeNull();
  });

  it("hides the sheet again when the control is pressed a second time", async () => {
    await openThePreview();

    await userEvent.click(screen.getByRole("button", { name: "Hide CRS preview" }));

    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i }))
      .toBeNull();
  });

  it("shows the API's own words when the preview cannot be read", async () => {
    // AS THE API RETURNED IT. A 404 means this caller may not read the
    // submittal, and a friendlier sentence would hide which refusal it was.
    previewCrs.mockResolvedValue({
      ok: false,
      disconnected: false,
      error: { code: "not_found", message: "No review run with that id." },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));

    await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));

    expect(await screen.findByRole("alert"))
      .toHaveTextContent("No review run with that id.");
    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i }))
      .toBeNull();
  });

  it("does not survive a move to another run", async () => {
    // One submittal's comments under another submittal's name is a sheet the
    // reader has no way to tell is stale.
    reviewRuns.mockResolvedValue({
      ok: true,
      data: { runs: [run(), run({ review_run_id: "run-2",
                                  submittal_filename: "pump.pdf" })] },
    });
    await openThePreview();

    await userEvent.click(screen.getByRole("button", { name: /pump\.pdf/i }));

    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i }))
      .toBeNull();
  });
});

describe("the download the preview sits beside", () => {
  it("still exports the .xlsx, untouched by the preview", async () => {
    exportCrs.mockResolvedValue({
      ok: true,
      data: { blob: new Blob(["x"]), filename: "CRS_drum_2026-09-20.xlsx" },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /drum\.pdf/i }));

    await userEvent.click(screen.getByRole("button", { name: "Export CRS (.xlsx)" }));

    expect(exportCrs).toHaveBeenCalledWith("run-1");
    expect(previewCrs).not.toHaveBeenCalled();
  });
});
