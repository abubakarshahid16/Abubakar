/** #925 item 1: the document's ROLE was not visible on the card. A reader
 *  scanning the Documents list could not tell a contractor submittal from a
 *  company standard without opening each one - and the Dashboard's review
 *  launcher only offers documents with `document_role: CONTRACTOR_SUBMITTAL`.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentCard } from "./DocumentCard";
import type { DocumentClassification, DocumentRecord } from "../types/api";

function makeDoc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc_1111",
    filename: "doc17.pdf",
    sha256: "a".repeat(64),
    size_bytes: 1024,
    page_count: 492,
    pages_done: 492,
    chunk_count: 979,
    chunk_count_total: 1000,
    disciplines: ["IT"],
    embedded_count: 979,
    status: "ready",
    needs_ocr_pages: 0,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    pages_excluded: 0,
    pages_excluded_characters: 0,
    pages_excluded_with_clause_headings: 0,
    uploaded_at: "2026-09-06T00:00:00Z",
    indexed_at: "2026-09-06T00:00:00Z",
    ...over,
  };
}

function makeClassification(
  over: Partial<DocumentClassification> = {},
): DocumentClassification {
  return {
    document_id: "doc_1111",
    doc_type: "Datasheet",
    confirmed: true,
    suggested_by: "rule",
    ...over,
  } as DocumentClassification;
}

const NO_ACTIONS = {
  onExtract: vi.fn(), onChunk: vi.fn(), onEmbed: vi.fn(),
  onDelete: vi.fn(), onInspect: vi.fn(), onExcluded: vi.fn(),
} as never;

describe("the document's role", () => {
  it("shows the role in the words an engineer uses, not the server's constant", () => {
    render(
      <DocumentCard
        doc={makeDoc()}
        classification={makeClassification({ document_role: "CONTRACTOR_SUBMITTAL" })}
        actions={NO_ACTIONS}
      />,
    );
    expect(screen.getByTestId("role-chip")).toHaveTextContent("Contractor submittal");
    expect(screen.queryByText("CONTRACTOR_SUBMITTAL")).toBeNull();
  });

  it("shows a company standard's role too", () => {
    render(
      <DocumentCard
        doc={makeDoc()}
        classification={makeClassification({ document_role: "COMPANY_STANDARD" })}
        actions={NO_ACTIONS}
      />,
    );
    expect(screen.getByTestId("role-chip")).toHaveTextContent("Company standard");
  });

  /** NULL RENDERS AS NOTHING, never a placeholder: a role this system has
   *  not been told is unknown, not "none". */
  it("renders nothing when no role has been set", () => {
    render(
      <DocumentCard
        doc={makeDoc()}
        classification={makeClassification({ document_role: null })}
        actions={NO_ACTIONS}
      />,
    );
    expect(screen.queryByTestId("role-chip")).toBeNull();
  });

  it("renders nothing while classification has not loaded yet", () => {
    render(<DocumentCard doc={makeDoc()} actions={NO_ACTIONS} />);
    expect(screen.queryByTestId("role-chip")).toBeNull();
  });
});
