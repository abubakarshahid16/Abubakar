/**
 * #967 PR1: the AI Submittal Review landing list - one row per document
 * from a contractor, one Review button.
 *
 * MUTATION PROOF: drop the orphan-run fallback in `rowsFor` and the second
 * test below fails (the run's document would vanish from the list); remove
 * the "Not reviewed yet" branch and the first test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../types/api";
import { DocumentsFromContractors } from "./DocumentsFromContractors";

function doc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc-1", filename: "psv-sheet.pdf", document_role: "CONTRACTOR_SUBMITTAL",
    ...over,
  } as DocumentRecord;
}

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "psv-sheet.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
    standards_in_scope: 1, findings_total: 0, by_status: {},
    ...over,
  } as ReviewRunSummary;
}

describe("DocumentsFromContractors", () => {
  it("says a document has not been reviewed yet, with a Review button that starts one", async () => {
    const onReview = vi.fn();
    render(
      <DocumentsFromContractors
        documents={[doc()]} runs={[]} submittalsTotal={null}
        onReview={onReview} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("psv-sheet.pdf")).toBeInTheDocument();
    expect(screen.getByText("Not reviewed yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onReview).toHaveBeenCalledWith("doc-1");
  });

  it("still lists a run whose document record is missing, under the run's own filename", () => {
    render(
      <DocumentsFromContractors
        documents={[]} runs={[run({ submittal_document_id: "doc-gone", submittal_filename: "orphan.pdf" })]}
        submittalsTotal={null} onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("orphan.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Finished/)).toBeInTheDocument();
  });

  it("shows the latest run's plain status and date for a reviewed document", () => {
    render(
      <DocumentsFromContractors
        documents={[doc()]} runs={[run()]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText(/Finished/)).toBeInTheDocument();
  });

  it("disables the button and says Starting… for the document being started", () => {
    render(
      <DocumentsFromContractors
        documents={[doc()]} runs={[]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId="doc-1"
      />,
    );
    const button = screen.getByRole("button", { name: "Starting…" });
    expect(button).toBeDisabled();
  });

  it("says there are no documents yet when the list is empty", () => {
    render(
      <DocumentsFromContractors
        documents={[]} runs={[]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("No documents from contractors yet")).toBeInTheDocument();
  });
});
