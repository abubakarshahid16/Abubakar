/**
 * The CRS page behind the Sheet (#967 PR 3): the deliverable on screen
 * beside the download. Ported from the old page's preview tests; the
 * backend's `test_the_preview_is_the_workbook_row_for_row` holds the other
 * half (what this renders is what the .xlsx says).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsPreview, ReviewRunSummary } from "../../../types/api";
import { BehindTheScenes, type BehindTheScenesProps } from "./BehindTheScenes";

const previewCrs = vi.fn();
const exportCrs = vi.fn();
vi.mock("../../../api/client", () => ({
  api: {},
  reviews: {
    previewCrs: (...args: unknown[]) => previewCrs(...args),
    exportCrs: (...args: unknown[]) => exportCrs(...args),
    setCrsTransmittals: vi.fn(), importCrsReply: vi.fn(),
    setCrsCommentStatus: vi.fn(), recordCrsResponse: vi.fn(), crsCommentHistory: vi.fn(),
    // PF5 (#885): the open items before issue.
    crsIssueGate: async () => ({ ok: true, data: {
      review_run_id: "run-1", issuable: false, final_code_recorded: true,
      blockers: ["1 finding(s) on the sheet have no engineer's decision"],
      unread_pages: [], open_findings: [{ finding_id: "f-1", row_kind: null, item: 1 }] } }),
    decideCrsPage: vi.fn(), decideCrsFinding: vi.fn(),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "drum.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-09-20T00:00:00Z",
    completed_at: "2026-09-20T00:01:00Z", standards_in_scope: 2, findings_total: 1,
    by_status: { NON_COMPLIANT: 1 }, recommended_code: "Manual Review Required",
    recommended_reason: "the review examined 42 of approximately 385 fields", ...over,
  } as ReviewRunSummary;
}

/** A preview body shaped exactly as the route returns one. */
function sheet(over: Partial<CrsPreview> = {}): CrsPreview {
  return {
    title: "EXAMPLE OPERATING COMPANY (EOC)",
    subtitle: "COMMENT RESOLUTION SHEET",
    header: [
      { label: "COMPANY Transmittal No.:", value: "" },
      { label: "CONTRACTOR  Transmittal No.:", value: "" },
      { label: "Document Title:", value: "drum.pdf" },
      { label: "Date Issued:", value: "2026-09-20" },
      { label: "Date Responded", value: "" },
    ],
    columns: ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
              "Contractor's Response", "Final Resolution"],
    rows: [
      { item_no: 1, row_ref: "RF-4A2C1B", document_name: "drum.pdf",
        page_section: "SAES-D-001.pdf clause 6.2.2 p14 / submittal p4",
        comment: "Ref: RF-4A2C1B\nRequirement: The design pressure shall be 6,900 kPa.",
        comment_by: "AI Review", contractor_response: "", final_resolution: "" },
      { item_no: 2, row_ref: "RF-9E17D0", document_name: "drum.pdf", page_section: "References",
        comment: "Ref: RF-9E17D0\nReferenced standard 32-SAMSS-004 is cited by "
                 + "this submittal but is not in the standards library for this review.",
        comment_by: "AI Review", contractor_response: "", final_resolution: "" },
    ],
    recommended_code: "Manual Review Required",
    recommended_code_reason: "the review examined 42 of approximately 385 fields",
    recommended_code_label: "Recommended Review Code:",
    ...over,
  };
}

function page(over: Partial<BehindTheScenesProps> = {}) {
  const props: BehindTheScenesProps = {
    panel: "crs", run: run(), findings: [], documents: [],
    standardsState: { standards: [], missing: [], error: null }, focusStatus: null,
    onOpenPanel: vi.fn(), onFocusStatus: vi.fn(), onStandardsChanged: vi.fn(), onChanged: vi.fn(),
    ...over,
  };
  return render(<BehindTheScenes {...props} />);
}

async function openThePreview(over: Partial<BehindTheScenesProps> = {}) {
  page(over);
  await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
  return screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
}

beforeEach(() => {
  previewCrs.mockReset();
  exportCrs.mockReset();
  previewCrs.mockResolvedValue({ ok: true, data: sheet() });
});

describe("the CRS preview", () => {
  it("is not fetched until the reader asks for it", async () => {
    page();
    expect(previewCrs).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i })).toBeNull();
  });

  it("renders the header block the workbook prints, labels and all", async () => {
    const panel = within(await openThePreview());
    expect(previewCrs).toHaveBeenCalledWith("run-1");
    expect(panel.getByText(/EXAMPLE OPERATING COMPANY/)).toBeInTheDocument();
    expect(panel.getByText("COMMENT RESOLUTION SHEET")).toBeInTheDocument();
    expect(panel.getByText("Document Title:").nextElementSibling).toHaveTextContent("drum.pdf");
    expect(panel.getByText("Date Issued:").nextElementSibling).toHaveTextContent("2026-09-20");
    // BLANK IS BLANK: no invented transmittal number.
    expect(panel.getByText("COMPANY Transmittal No.:").nextElementSibling).toBeEmptyDOMElement();
    expect(panel.queryByText(/N\/A|TBD|pending/i)).toBeNull();
  });

  it("renders the seven columns of the client's template, in order", async () => {
    const panel = within(await openThePreview());
    expect(panel.getAllByRole("columnheader").map((th) => th.textContent))
      .toEqual(["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
                "Contractor's Response", "Final Resolution"]);
  });

  it("renders one row per comment, with its citation and its text", async () => {
    const panel = within(await openThePreview());
    const rows = panel.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const first = within(rows[0]);
    expect(first.getByText("1")).toBeInTheDocument();
    expect(first.getByText(/SAES-D-001\.pdf clause 6\.2\.2 p14/)).toBeInTheDocument();
    expect(first.getByText(/The design pressure shall be 6,900 kPa\./)).toBeInTheDocument();
    expect(first.getByText("AI Review")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/32-SAMSS-004/)).toBeInTheDocument();
  });

  it("shows each row's reasoning when the internal copy carries the column (R30)", async () => {
    const base = sheet();
    previewCrs.mockResolvedValue({ ok: true, data: sheet({
      // order 139 part 2: the server prints "Priority" where it printed "Severity"
      columns: [...base.columns, "Standard Reference", "Priority", "AI Review Comments", "Reasoning (internal)"],
      rows: base.rows.map((r, i) => ({ ...r, reasoning: i === 0
        ? "Read: Design pressure = 5,000 kPa (p.4). Clause: SAES-D-001 cl. 6.2.2. Result: does not meet." : "" })),
    }) });
    const panel = within(await openThePreview());
    const cells = panel.getAllByTestId("crs-reasoning");
    expect(cells).toHaveLength(2);
    expect(cells[0].textContent).toContain("Result: does not meet");
  });

  it("gives the rule-trust column a cell on every row, so the columns line up (#947)", async () => {
    const base = sheet();
    previewCrs.mockResolvedValue({ ok: true, data: sheet({
      // order 139 part 2: the server prints "Priority" where it printed "Severity"
      columns: [...base.columns, "Standard Reference", "Priority", "AI Review Comments",
                "Reasoning (internal)", "Rule trust (internal)"],
      rows: base.rows.map((r, i) => ({ ...r, rule_trust: i === 0 ? "automatic rule not yet proven" : "" })),
    }) });
    const panel = within(await openThePreview());
    const cells = panel.getAllByTestId("crs-rule-trust");
    expect(cells).toHaveLength(2);
    expect(cells[0].textContent).toBe("automatic rule not yet proven");
    for (const row of panel.getAllByRole("row").slice(1)) {
      expect(within(row).getAllByRole("cell")).toHaveLength(12);
    }
  });

  it("shows the AI-suggests column beside the row, a cell on every row (order 305.4)", async () => {
    const base = sheet();
    previewCrs.mockResolvedValue({ ok: true, data: sheet({
      columns: [...base.columns, "Standard Reference", "Priority", "AI Review Comments",
                "Reasoning (internal)", "Rule trust (internal)", "AI suggests (internal)"],
      rows: base.rows.map((r, i) => ({ ...r, ai_suggests: i === 0 ? "Fail (sheet: Set pressure = 12 barg) - suggestion only" : "" })),
    }) });
    const panel = within(await openThePreview());
    const cells = panel.getAllByTestId("crs-ai-suggests");
    expect(cells).toHaveLength(2);
    expect(cells[0].textContent).toContain("suggestion only");
    expect(cells[1].textContent).toBe("");
    for (const row of panel.getAllByRole("row").slice(1)) {
      expect(within(row).getAllByRole("cell")).toHaveLength(13);
    }
  });

  it("shows no reasoning column when the copy does not carry it", async () => {
    const panel = within(await openThePreview());
    expect(panel.queryAllByTestId("crs-reasoning")).toHaveLength(0);
  });

  it("leaves the contractor's two columns present and empty", async () => {
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

  it("says when the code is still only the AI's recommendation (B10)", async () => {
    previewCrs.mockResolvedValue({ ok: true, data: sheet({ recommended_code_status: "AI recommendation - NOT yet decided by an engineer." }) });
    const panel = within(await openThePreview());
    expect(panel.getByTestId("crs-code-status")).toHaveTextContent(/NOT yet decided by an engineer/);
  });

  it("shows no code line at all when the run has no recommendation", async () => {
    previewCrs.mockResolvedValue({ ok: true, data: sheet({ recommended_code: "", recommended_code_reason: "" }) });
    const panel = within(await openThePreview());
    expect(panel.queryByText("Recommended Review Code:")).toBeNull();
  });

  it("hides the sheet again when the control is pressed a second time", async () => {
    await openThePreview();
    await userEvent.click(screen.getByRole("button", { name: "Hide CRS preview" }));
    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i })).toBeNull();
  });

  it("shows the API's own words when the preview cannot be read", async () => {
    previewCrs.mockResolvedValue({ ok: false, disconnected: false,
      error: { code: "not_found", message: "No review run with that id." } });
    page();
    await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No review run with that id.");
    expect(screen.queryByRole("region", { name: /Comment Resolution Sheet preview/i })).toBeNull();
  });
});

describe("the download the preview sits beside", () => {
  it("still exports the .xlsx, untouched by the preview", async () => {
    exportCrs.mockResolvedValue({ ok: true, data: { blob: new Blob(["x"]), filename: "CRS_drum_2026-09-20.xlsx" } });
    page();
    await userEvent.click(screen.getByRole("button", { name: "Export CRS - internal review copy" }));
    expect(exportCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(previewCrs).not.toHaveBeenCalled();
  });

  it("order 121: the contractor's copy is not issued here; the page links to the comment sheet instead", async () => {
    page({ run: run({ engineer_final_code: "Approved" }) });
    expect(screen.queryByRole("button", { name: "Issue CRS to contractor" })).toBeNull();
    expect(screen.getByText("Sign and export on the comment sheet")).toBeInTheDocument();
    expect(exportCrs).not.toHaveBeenCalledWith("run-1", "issue");
  });
});

describe("2f: the engineer's internal notes are their own table, not comments", () => {
  it("shows the Review notes collapsed under the sheet, never in a comment row", async () => {
    previewCrs.mockResolvedValue({ ok: true, data: sheet({ review_notes: [
      { note: "Requires another document", standard: "STD-A.pdf", count: 12,
        detail: "12 of this run's requirements from STD-A.pdf name their own evidence." },
    ] }) });
    const panel = within(await openThePreview());
    const notes = panel.getByText(/Review notes - internal \(1\)/).closest("details")!;
    expect(within(notes).getByText("Requires another document")).toBeInTheDocument();
    expect(within(notes).getByText("12")).toBeInTheDocument();
    const table = panel.getAllByRole("table")[0];
    expect(within(table).queryByText(/name their own evidence/)).toBeNull();
  });

  it("review notes on screen are collapsed and fetched only when opened", async () => {
    previewCrs.mockResolvedValue({ ok: true, data: { rows: [], review_notes: [
      { note: "Requires another document", standard: "API 999.pdf", count: 12, detail: "name their own evidence" },
    ] } });
    page();
    const notes = screen.getByTestId("review-notes");
    expect(notes).not.toHaveAttribute("open");
    expect(previewCrs).not.toHaveBeenCalled();
    await userEvent.click(within(notes).getByText("Review notes - internal"));
    expect(await within(notes).findByText("Requires another document")).toBeInTheDocument();
    expect(previewCrs).toHaveBeenCalledWith("run-1");
  });

  it("order 121: the old issue gate (one line per raw finding) is no longer on this page", async () => {
    page({ run: run({ engineer_final_code: "Approved" }) });
    expect(await screen.findByText("Sign and export on the comment sheet")).toBeInTheDocument();
    expect(screen.queryByText(/Not ready to issue to the contractor/)).toBeNull();
    expect(screen.queryByText(/has no engineer's decision/)).toBeNull();
  });
});
