/**
 * "How it was reviewed" names where a number comes from in plain words; the stored field path stays in the tooltip (U5).
 * MUTATION PROOF: print `fact.source` raw in HowPrimitives and the render test fails.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { PagesSection } from "./PagesSection";
import { plainSource } from "./sourceWords";

const CODE = /page_coverage|requirement_split|standards_change|coverage_pair|clause_coverage|\b[a-z]+_[a-z_]+\b/;

describe("plainSource", () => {
  it("turns a stored field path into words and leaves ordinary text alone", () => {
    expect(plainSource("page_coverage.pages_total")).toBe("the page record: pages in the document");
    expect(plainSource("requirement_split.reader.pages_read")).toBe("the reader's page count");
    expect(plainSource("completed_at - created_at")).toBe("the time the review finished - the time the review started");
    expect(plainSource("recommended_code")).toBe("recommended code");
    expect(plainSource("page_coverage.ocr.pending + page_coverage.ocr.failed")).toBe("the page record: ocr pending + the page record: ocr failed");
    expect(plainSource("(OCR done on 4, e.g. scans) pages 1, 2")).toBe("(OCR done on 4, e.g. scans) pages 1, 2");
  });
  it("every path in a sentence is replaced", () => {
    const out = plainSource("The run stored the reading as complete for all 9 pages (page_coverage.reading.status).");
    expect(out).toBe("The run stored the reading as complete for all 9 pages (the page record: reading status).");
  });
});

describe("the pages section on screen", () => {
  afterEach(cleanup);
  it("prints no field path, keeps it in the tooltip, and keeps the numbers", () => {
    const run = { review_run_id: "r", page_coverage: { pages_total: 9, fact_pages: [1, 2], pages_not_read_into_fields: [3], not_read_reasons: { "3": "x" },
      reading: { status: "complete", pages_total: 9, incomplete_pages: [], reasons: {} } } } as unknown as ReviewRunSummary;
    const { container } = render(<PagesSection run={run} />);
    expect(screen.getByTestId("pages-total")).toHaveTextContent("9");
    expect(screen.getByTestId("pages-total")).toHaveTextContent("from the page record: pages in the document");
    expect(screen.getByTestId("pages-total").querySelector("[title]")?.getAttribute("title")).toBe("page_coverage.pages_total");
    const visible = (container.textContent ?? "");
    expect(visible).not.toMatch(CODE);
  });
});
