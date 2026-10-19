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
    expect(pagesText(runOf({ unread_pages: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] }))).toBe("Pages not fully read: 11 of 11 (1-11).");
  });
  it("names the pages of the one list against the total", () => {
    expect(pagesText(runOf({ unread_pages: [9, 4] }))).toBe("Pages not fully read: 2 of 11 (4, 9).");
  });
  it("none unread is said as none of the total, never a bare 0", () => {
    expect(pagesText(runOf({ unread_pages: [] }))).toBe("Pages not fully read: none of 11.");
  });
  it("a run that does not hold the list says so; it does not fall back to the code readers' list", () => {
    expect(pagesText(runOf({ unread_pages: null }))).toBe("Pages not fully read: not recorded for this review.");
    expect(pagesText(runOf({}))).toBe("Pages not fully read: not recorded for this review.");
  });
  it("no coverage and no total keep their own words", () => {
    expect(pagesText(runOf({ page_coverage: null, unread_pages: [4] }))).toBe("Pages read: not recorded for this review.");
    expect(pagesText(runOf({
      page_coverage: { pages_total: null, fact_pages: [], pages_not_read_into_fields: [], not_read_reasons: {} } as never, unread_pages: [],
    }))).toBe("Pages: none accounted for.");
  });
});

/** Round 2 item 2. MUTATION PROOF: print "Not signed yet" whatever the run
 *  says (or go back to "Run <id>" / "Rows on this sheet") and this fails. */
describe("CrsFooter plain words and the signed line", () => {
  function footerText(run: ReviewRunSummary, signedAt?: string | null): string {
    cleanup();
    const { getByTestId } = render(
      <CrsFooter run={run} counts={{ comment: 3, needsYou: 1, met: 2, notApplicable: 0, anotherDocument: 1 }}
        standards={null} missing={[]} standardsError={null} rejected={0} signedAt={signedAt} />,
    );
    return getByTestId("crs-footer").textContent ?? "";
  }

  it("a signed review says Signed on <date>, never Not signed yet", () => {
    const at = "2026-10-16T10:00:00Z";
    const text = footerText(runOf({ crs_issued_at: at }));
    expect(text).toContain(`Signed on ${new Date(at).toLocaleString()}.`);
    expect(text).not.toContain("Not signed yet");
    // Given by the caller, it wins.
    expect(footerText(runOf({}), at)).toContain(`Signed on ${new Date(at).toLocaleString()}.`);
  });

  it("an unsigned review still says Not signed yet", () => {
    expect(footerText(runOf({}))).toContain("Not signed yet.");
  });

  it("says the review's date and the counts in plain words, without the run id", () => {
    const at = "2026-10-15T08:18:00Z";
    const text = footerText(runOf({ completed_at: at }));
    expect(text).toContain(`Review of ${new Date(at).toLocaleString()}`);
    expect(text).not.toContain("run-made-up");
    expect(text).toContain("On this sheet: 3 comments, 1 needs your judgement, 2 met the standard, 0 not applicable, 1 for another document");
    expect(text).not.toMatch(/Rows on this sheet|\bRun\b/);
  });
});
