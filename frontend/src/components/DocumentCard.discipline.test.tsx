/**
 * The document's CATEGORY on the card.
 *
 * The category is the access grant - the plan makes discipline the grant
 * rather than a tag - so these tests drive the same `disciplines` field the
 * API reads out of the grant tables. Nothing here infers a category from a
 * filename, and a test that did would pass while the screen lied.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentCard } from "./DocumentCard";
import type { DocumentRecord } from "../types/api";

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

const NO_ACTIONS = {
  onExtract: vi.fn(), onChunk: vi.fn(), onEmbed: vi.fn(),
  onDelete: vi.fn(), onInspect: vi.fn(), onExcluded: vi.fn(),
} as never;

describe("the document's category", () => {
  it("shows the discipline the document is granted to", () => {
    render(<DocumentCard doc={makeDoc({ disciplines: ["Civil Engineering"] })} actions={NO_ACTIONS} />);
    expect(screen.getByText("Civil Engineering")).toBeInTheDocument();
  });

  it("shows every discipline when a document is held by more than one", () => {
    render(<DocumentCard doc={makeDoc({ disciplines: ["Civil Engineering", "Mechanical"] })} actions={NO_ACTIONS} />);
    expect(screen.getByText("Civil Engineering")).toBeInTheDocument();
    expect(screen.getByText("Mechanical")).toBeInTheDocument();
  });

  /** THE CASE THAT WOULD ROT SILENTLY. An empty `disciplines` is a real state
   *  - no discipline holds the document and only an administrator can read it
   *  - and rendering nothing for it would leave a card that looks identical to
   *  one whose category simply failed to load. It is labelled, not blank. */
  it("says Admin only when no discipline holds the document, rather than nothing", () => {
    render(<DocumentCard doc={makeDoc({ disciplines: [] })} actions={NO_ACTIONS} />);
    const badge = screen.getByTestId("discipline");
    expect(badge).toHaveTextContent("Admin only");
    expect(badge.textContent?.trim()).not.toBe("");
  });

  it("never invents a category from the filename", () => {
    render(<DocumentCard doc={makeDoc({ filename: "civil-Design-and-Construction.pdf", disciplines: [] })} actions={NO_ACTIONS} />);
    expect(screen.queryByText("Civil Engineering")).toBeNull();
    expect(screen.getByTestId("discipline")).toHaveTextContent("Admin only");
  });
});
