/**
 * Order 95 piece 4 (absorbs 94a): comment-driven navigation for long
 * documents, the one-line comparison and the history, on invented findings.
 *
 * MUTATION PROOF: drop the first/last pages from the strip and the 100-page
 * case fails; let stepRow wrap and "an end is an end" fails; let a missing
 * value show as "0" and the comparison case fails.
 */
import { describe, expect, it } from "vitest";

import type { CrsIssueDecision, ReviewFinding } from "../../../types/api";
import type { CrsRow } from "./crsRows";
import { commentPages, comparisonLine, firstRowOnPage, historyOf, pagerStrip, parsePage, stepPage, stepRow } from "./evidenceNav";

function row(key: string, page: number | null, tier: "A" | "B" | "C" = "B"): CrsRow {
  return { key, page, tier: { tier, label: tier === "A" ? "Met" : tier === "B" ? "Comment" : "Needs you", reason: null } } as CrsRow;
}

function f(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return { id: "x", created_at: "2026-10-15T08:00:00Z", approval_status: "pending", requirement: "", ...over } as ReviewFinding;
}

describe("the pager strip", () => {
  it.each([
    [7, [3, 5], [1, 3, 5, 7]],
    [11, [1, 6, 11], [1, 6, 11]],
    [100, [2, 47, 48, 90], [1, 2, 47, 48, 90, 100]],
  ])("a %i-page document shows the comment pages plus first and last", (count, pages, strip) => {
    expect(pagerStrip(pages, count)).toEqual(strip);
  });
  it("without a page count it invents no last page", () => {
    expect(pagerStrip([4, 2], null)).toEqual([2, 4]);
  });
  it("a page beyond the document is not offered", () => {
    expect(pagerStrip([3, 12], 7)).toEqual([1, 3, 7]);
  });
});

describe("moving", () => {
  const rows = [row("a", 1), row("met", 2, "A"), row("b", 3), row("c", 3, "C"), row("d", 90)];
  it("comment pages skip Met rows and repeat no page", () => {
    expect(commentPages(rows)).toEqual([1, 3, 90]);
  });
  it("stepRow moves one row; an end is an end", () => {
    expect(stepRow(rows, "a", 1)?.key).toBe("met");
    expect(stepRow(rows, "d", -1)?.key).toBe("c");
    expect(stepRow(rows, "a", -1)).toBeNull();
    expect(stepRow(rows, "d", 1)).toBeNull();
    expect(stepRow(rows, "gone", 1)).toBeNull();
  });
  it("PageDown / PageUp go to the next / previous comment page, over the empty ones", () => {
    expect(stepPage([1, 3, 90], 3, 1)).toBe(90);
    expect(stepPage([1, 3, 90], 50, -1)).toBe(3);
    expect(stepPage([1, 3, 90], 90, 1)).toBeNull();
    expect(stepPage([1, 3, 90], 1, -1)).toBeNull();
    expect(stepPage([1, 3, 90], null, 1)).toBe(1);
  });
  it("a page opens its first comment, or nothing", () => {
    expect(firstRowOnPage(rows, 3)?.key).toBe("b");
    expect(firstRowOnPage(rows, 50)).toBeNull();
  });
  it("the jump box takes a whole page of this document only", () => {
    expect(parsePage(" 47 ", 100)).toBe(47);
    expect(parsePage("0", 100)).toBeNull();
    expect(parsePage("101", 100)).toBeNull();
    expect(parsePage("4.5", 100)).toBeNull();
    expect(parsePage("abc", 100)).toBeNull();
    expect(parsePage("250", null)).toBe(250);
  });
});

describe("the one-line comparison", () => {
  it("says what the datasheet says, what the rule asks, and the result", () => {
    expect(comparisonLine(f({ matched_phrase: "Set pressure", contractor_evidence_text: "12 barg",
      requirement_source_text: "Set pressure shall not exceed 10 barg.", compliance_status: "NON_COMPLIANT" })))
      .toBe('Set pressure: the datasheet says "12 barg"; the rule asks: Set pressure shall not exceed 10 barg. - Non-compliant');
  });
  it("a value not on the datasheet is said so, never shown as 0", () => {
    const line = comparisonLine(f({ matched_phrase: "Orifice", requirement: "Orifice letter shall be stated.", compliance_status: "MISSING_INFORMATION" }));
    expect(line).toContain("Orifice: not found on the datasheet");
    expect(line).not.toMatch(/\b0\b/);
  });
  it("nothing recorded gives an empty line (the drawer then shows none)", () => {
    expect(comparisonLine(f({ compliance_status: null }))).toBe("");
  });
});

describe("the history", () => {
  it("lists what happened, oldest first; a time not recorded goes last, blank", () => {
    const h = historyOf([f({ confirmed_by: "Ali", confirmed_at: "2026-10-16T09:00:00Z", approval_status: "rejected",
      approved_by: "Ali", approved_at: "2026-10-17T09:00:00Z", engineer_comment: "Reworded." })]);
    expect(h.map((e) => e.what)).toEqual(["Found by the review", "Confirmed by Ali", "Comment removed by Ali",
      "Wording edited by an engineer"]);
    expect(h[3].when).toBe("");
  });
  it("two findings in one row found at the same time say it once", () => {
    expect(historyOf([f({ id: "1" }), f({ id: "2" })]).map((e) => e.what)).toEqual(["Found by the review"]);
  });
});

describe("the history from the decision record", () => {
  function d(over: Partial<CrsIssueDecision> = {}): CrsIssueDecision {
    return { id: "d", review_run_id: "r", kind: "finding", subject: "x", decision: "reject",
      reason: "same point as comment 3", decided_by: "Ali", decided_at: "2026-10-17T09:00:00Z", reason_code: null, ...over };
  }
  it("shows each recorded decision with its reason words and why, earlier ones kept", () => {
    const h = historyOf([f({ approval_status: "rejected", approved_by: "Ali", approved_at: "2026-10-17T09:00:00Z" })], [
      d({ id: "2", reason_code: "duplicate" }),
      d({ id: "1", decision: "accept", reason: "breach confirmed by eye", decided_at: "2026-10-16T09:00:00Z" }),
    ]);
    expect(h.map((e) => e.what)).toEqual([
      "Found by the review",
      "Comment accepted by Ali: breach confirmed by eye",
      "Comment removed by Ali (Duplicate): same point as comment 3",
    ]);
  });
  it("a decision on another finding, or on a page, is not this row's", () => {
    const h = historyOf([f()], [d({ subject: "other" }), d({ kind: "page", subject: "x" })]);
    expect(h.map((e) => e.what)).toEqual(["Found by the review"]);
  });
  it("without the record, the finding's own fields still tell it", () => {
    const h = historyOf([f({ approval_status: "rejected", approved_by: "Ali" })], null);
    expect(h.map((e) => e.what)).toEqual(["Found by the review", "Comment removed by Ali"]);
  });
  it("a code the screen does not know is shown as stored, never dropped", () => {
    expect(historyOf([f()], [d({ reason_code: "new_code", reason: "" })]).map((e) => e.what))
      .toContain("Comment removed by Ali (new_code)");
  });
});
