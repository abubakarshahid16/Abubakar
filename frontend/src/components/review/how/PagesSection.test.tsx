/**
 * #1550: with the page-read switch, "How this was reviewed" says "not read" of
 * the pages no reading came back for, with their own reasons; the pages no
 * datasheet field was taken from are a separate line. Made-up run.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { PagesSection } from "./PagesSection";

const NO_FIELD = "no field was read from this page";
const coverage = {
  pages_total: 3, fact_pages: [], pages_not_read_into_fields: [1, 2, 3],
  not_read_reasons: { "1": NO_FIELD, "2": NO_FIELD, "3": NO_FIELD },
};
const on = {
  ...coverage, pages_read: [1, 3], pages_not_read: [2],
  pages_not_read_why: { "2": "excluded from the index on purpose (rule page_classified_toc)" },
};

function show(pc: object) {
  cleanup();
  render(<PagesSection run={{ review_run_id: "r", page_coverage: pc } as unknown as ReviewRunSummary} />);
}

describe("PagesSection, one meaning of 'not read' (#1550)", () => {
  afterEach(cleanup);
  it("switch on: 'Not read' is page 2 with its own reason; the fields list is said apart", () => {
    show(on);
    const row = screen.getByTestId("pages-not-read").textContent ?? "";
    expect(row).toContain("Not read");
    expect(row).not.toContain("into fields");
    expect(row).toContain("pages 2");
    expect(screen.getByTestId("pages-not-read-reasons").textContent).toBe(
      "Page 2: excluded from the index on purpose (rule page_classified_toc)");
    // an unread page is never also counted as no field taken
    const noField = screen.getByTestId("pages-no-field-taken").textContent ?? "";
    expect(noField).toContain("(pages 1, 3)");
    expect(noField).toContain("2");
    expect(noField).not.toContain("pages 1-3");
  });
  it("switch off: unchanged", () => {
    show(coverage);
    expect(screen.getByTestId("pages-not-read").textContent).toContain("Not read into fields");
    expect(screen.queryByTestId("pages-no-field-taken")).toBeNull();
    expect(screen.getByTestId("pages-not-read-reasons").textContent).toContain(`Page 1: ${NO_FIELD}`);
  });
  const reading = { status: "incomplete", pages_total: 3, incomplete_pages: [1, 2, 3], reasons: {} };
  it("switch on: the incomplete reading says 'not read' only of page 2", () => {
    show({ ...on, reading });
    const row = screen.getByTestId("pages-reading").textContent ?? "";
    expect(row).toContain("page 2 not read; pages 1, 3 no datasheet field taken");
    expect(row).not.toContain("not read in full");
    const meaning = screen.getByTestId("pages-meaning").textContent ?? "";
    expect(meaning).toContain("incomplete: page 2 not read; pages 1, 3 no datasheet field taken (of 3 pages)");
  });
  it("switch off: the incomplete reading's words are unchanged", () => {
    show({ ...coverage, reading });
    expect(screen.getByTestId("pages-reading").textContent).toContain("(pages 1-3 not read in full, from");
    expect(screen.getByTestId("pages-meaning").textContent).toContain("3 of 3 pages were not read in full (pages 1-3)");
  });
});
