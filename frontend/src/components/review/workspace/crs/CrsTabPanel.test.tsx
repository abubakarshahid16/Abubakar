/**
 * v2.1 gap S3: the CRS page (transmittal numbers, contractor replies
 * import, Open / Closed) is the workspace's "CRS" tab, embedded, and it
 * never sends the reader to the old comment sheet to sign. Made-up data.
 */
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsPreview } from "../../../../types/api";
import { CrsTabPanel } from "./CrsTabPanel";

const previewCrs = vi.fn();
vi.mock("../../../../api/client", () => ({
  api: {},
  reviews: {
    previewCrs: (...a: unknown[]) => previewCrs(...a),
    exportCrs: vi.fn(), setCrsTransmittals: vi.fn(), importCrsReply: vi.fn(),
    setCrsCommentStatus: vi.fn(), recordCrsResponse: vi.fn(), crsCommentHistory: vi.fn(),
  },
}));

function sheet(): CrsPreview {
  return {
    title: "EXAMPLE OPERATING COMPANY", subtitle: "COMMENT RESOLUTION SHEET",
    header: [{ label: "COMPANY Transmittal No.:", value: "" }, { label: "CONTRACTOR  Transmittal No.:", value: "" }],
    columns: ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
      "Contractor's Response", "Final Resolution"],
    rows: [{ item_no: 1, row_ref: "RF-1", document_name: "Pump datasheet rev B.pdf", page_section: "p4",
      comment: "Design pressure is below API 610.", comment_by: "Reviewer", contractor_response: "", final_resolution: "" }],
    recommended_code: "", recommended_code_label: "Recommended Review Code:", recommended_code_reason: "",
  } as unknown as CrsPreview;
}

beforeEach(() => { previewCrs.mockReset().mockResolvedValue({ ok: true, data: sheet() }); });

describe("the CRS tab (S3)", () => {
  it("opens the sheet by itself, with transmittal numbers, the replies import and Open / Closed", async () => {
    render(<CrsTabPanel runId="run-1" />);
    const region = await screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
    expect(previewCrs).toHaveBeenCalledWith("run-1");
    expect(within(region).getByRole("form", { name: "Transmittal numbers" })).toBeInTheDocument();
    expect(within(region).getByLabelText("Import contractor reply")).toBeInTheDocument();
    expect(within(region).getByText("Design pressure is below API 610.")).toBeInTheDocument();
    expect(within(region).getByRole("columnheader", { name: "Final Resolution" })).toBeInTheDocument();
  });

  it("points to the workspace's own Sign and export, never to the old comment sheet", async () => {
    render(<CrsTabPanel runId="run-1" />);
    await screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
    expect(screen.queryByRole("link", { name: "Sign and export on the comment sheet" })).toBeNull();
    expect(screen.getByTestId("crs-tab-sign-hint")).toHaveTextContent("use Sign and export at the top");
    // The internal working copy stays available.
    expect(screen.getByRole("button", { name: /internal review copy/ })).toBeInTheDocument();
  });

  it("a sheet that cannot be loaded says so", async () => {
    previewCrs.mockResolvedValue({ ok: false, error: { message: "server busy" } });
    render(<CrsTabPanel runId="run-1" />);
    expect(await screen.findByText(/The sheet could not be loaded: server busy/)).toBeInTheDocument();
  });
});
