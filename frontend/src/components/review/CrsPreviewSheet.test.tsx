/**
 * Order 139 part 2: the preview prints the file's Priority column (it
 * replaced Severity) from each row's `priority_label`, marks a row whose
 * comment text is missing, and says how many rows the issue copy left out
 * for having no text - never silently. Invented data.
 *
 * MUTATION PROOF: print `row.severity` in the Priority cell and the first
 * test fails; drop the withheld-rows note and the third fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CrsPreview } from "../../types/api";
import { CrsPreviewSheet } from "./CrsPreviewSheet";

function sheet(over: Partial<CrsPreview> = {}): CrsPreview {
  return {
    title: "EXAMPLE COMPANY", subtitle: "COMMENT RESOLUTION SHEET",
    header: [{ label: "Document Title:", value: "Invented sheet.pdf" }],
    columns: ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
      "Contractor's Response", "Final Resolution", "Standard Reference", "Priority"],
    rows: [
      { item_no: 1, row_ref: "RF-1", document_name: "Invented sheet.pdf", page_section: "p.9",
        comment: "The invented rating is below the limit.", comment_by: "AI Review", contractor_response: "",
        final_resolution: "", standard_reference: "STD-INV cl. 4.1", severity: "minor",
        priority: 1, priority_label: "Out of limit" },
      { item_no: 2, row_ref: "RF-2", document_name: "Invented sheet.pdf", page_section: "p.2",
        comment: "Ref: RF-2\nNo comment text was produced for this row.", comment_by: "AI Review",
        contractor_response: "", final_resolution: "", standard_reference: "", severity: "minor",
        priority: null, priority_label: "", comment_missing: true },
    ],
    recommended_code: "", recommended_code_label: "Recommended Review Code:", recommended_code_reason: "",
    ...over,
  } as CrsPreview;
}

describe("CrsPreviewSheet Priority column (order 139 part 2)", () => {
  it("prints the Priority column from priority_label", () => {
    render(<CrsPreviewSheet preview={sheet()} runId="run-1" onChanged={vi.fn()} readOnly />);
    const cells = screen.getAllByTestId("crs-priority").map((c) => c.textContent);
    expect(cells).toEqual(["Out of limit", ""]);
    expect(document.body.textContent).not.toContain("minor");
  });

  it("marks a row whose comment text is missing", () => {
    render(<CrsPreviewSheet preview={sheet()} runId="run-1" onChanged={vi.fn()} readOnly />);
    const marked = document.querySelectorAll("[data-comment-missing='true']");
    expect(marked).toHaveLength(1);
    expect(marked[0].textContent).toContain("No comment text was produced");
  });

  it("says how many rows the issue copy left out for having no text", () => {
    render(<CrsPreviewSheet preview={sheet({ rows_withheld_no_text: 2 })} runId="run-1" onChanged={vi.fn()} readOnly />);
    expect(screen.getByTestId("crs-withheld-no-text")).toHaveTextContent(
      "2 rows were left off this copy because they have no comment text.");
  });

  it("says nothing about withheld rows when none were", () => {
    render(<CrsPreviewSheet preview={sheet({ rows_withheld_no_text: 0 })} runId="run-1" onChanged={vi.fn()} readOnly />);
    expect(screen.queryByTestId("crs-withheld-no-text")).toBeNull();
  });
});
