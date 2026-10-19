/**
 * Order 127: the footer's pages line is the run's one list of unread pages
 * (the same the header names and "Before you sign" asks ticks for), counted
 * against the page total. Made-up runs only.
 *
 * MUTATION PROOF: read `page_coverage.pages_not_read_into_fields` again and
 * "an AI reader that read nothing" fails (5 pages, not 11); say "none" for a
 * run without the list and "not recorded" fails.
 */
import { cleanup, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { CrsFooter } from "./CrsFooter";

const counts = { comment: 1, needsYou: 0, met: 0, notApplicable: 0, anotherDocument: 0 };

function runOf(over: Partial<ReviewRunSummary>): ReviewRunSummary {
  return {
    review_run_id: "run-made-up", created_at: null, completed_at: null, requirement_split: null,
    page_coverage: { pages_total: 11, fact_pages: [4, 6, 7, 8, 9, 10], pages_not_read_into_fields: [1, 2, 3, 5, 11], not_read_reasons: {} },
    ...over,
  } as unknown as ReviewRunSummary;
}

function pagesText(run: ReviewRunSummary): string {
  cleanup();
  const { getByTestId } = render(<CrsFooter run={run} counts={counts} standards={null} missing={[]} standardsError={null} rejected={0} />);
  const line = [...getByTestId("crs-footer").querySelectorAll("p")].map((p) => p.textContent ?? "")
    .find((t) => t.startsWith("Pages"));
  return line ?? "";
}

describe("CrsFooter pages line (order 127)", () => {
  it("an AI reader that read nothing: every page of 11 is not read, not only the code readers' five", () => {
    expect(pagesText(runOf({ unread_pages: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] }))).toBe("Pages not read: 11 of 11 (1-11).");
  });
  it("names the pages of the one list against the total", () => {
    expect(pagesText(runOf({ unread_pages: [9, 4] }))).toBe("Pages not read: 2 of 11 (4, 9).");
  });
  it("none unread is said as none of the total, never a bare 0", () => {
    expect(pagesText(runOf({ unread_pages: [] }))).toBe("Pages not read: none of 11.");
  });
  it("a run that does not hold the list says so; it does not fall back to the code readers' list", () => {
    expect(pagesText(runOf({ unread_pages: null }))).toBe("Pages not read: not recorded on this run.");
    expect(pagesText(runOf({}))).toBe("Pages not read: not recorded on this run.");
  });
  it("no coverage and no total keep their own words", () => {
    expect(pagesText(runOf({ page_coverage: null, unread_pages: [4] }))).toBe("Pages read: not recorded on this run.");
    expect(pagesText(runOf({
      page_coverage: { pages_total: null, fact_pages: [], pages_not_read_into_fields: [], not_read_reasons: {} } as never, unread_pages: [],
    }))).toBe("Pages: none accounted for.");
  });
});
