/**
 * Order 95 piece 2: the rows, the headline, the depth filter and the
 * spot check, on invented findings.
 *
 * MUTATION PROOF: number the Met rows and "comments are numbered, met rows
 * are not" fails; seed the spot check by Math.random and "the spot check is
 * the same on every visit" fails; let Critical show a blank and the depth
 * test fails.
 */
import { describe, expect, it } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { EMPTY_FACTS } from "./tiers";
import { buildCrsRows, crsHeadline, headlineFieldsOf, rowCounts, spotCheckKeys, splitRejected, visibleRows } from "./crsRows";

function f(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: 1, approval_status: "pending", standard_document_id: "std-1",
    standard_clause: "4.1", ...over,
  } as ReviewFinding;
}

const names = new Map([["std-1", "API 520.pdf"]]);

describe("buildCrsRows", () => {
  it("one row per comment in page order, numbered; met rows after, unnumbered", () => {
    const rows = buildCrsRows([
      f("b", { contractor_page: 3 }), f("a", { contractor_page: 1 }),
      f("m", { compliance_status: "COMPLIANT" }), f("c", { compliance_status: "CONDITIONAL", contractor_page: 2 }),
    ], EMPTY_FACTS, names);
    expect(rows.map((r) => [r.commentNo, r.item, r.tier.label])).toEqual([
      [1, "Field a", "Comment"], [2, "Field c", "Needs you"], [3, "Field b", "Comment"], [null, "Field m", "Met"],
    ]);
    expect(rows[0].clauseAndStandard).toBe("API 520.pdf, clause 4.1");
    expect(rows[0].pageOrSection).toBe("p. 1");
    expect(rows[0].requiredAction).toBe("Contractor to fix a.");
    expect(rows[0].status).toBe("Open");
  });
  it("groups the way the card view groups: 13 blanks, one comment", () => {
    const blanks = Array.from({ length: 13 }, (_, i) => f(`k${i}`, {
      compliance_status: "MISSING_INFORMATION", finding: `Field k${i} is blank`, required_action: `Contractor to give Field k${i}.`,
    }));
    const rows = buildCrsRows(blanks, EMPTY_FACTS, names);
    expect(rows).toHaveLength(1);
    expect(rows[0].findings).toHaveLength(13);
    expect(rows[0].observation).toContain("13 blanks, one answer");
    expect(rows[0].item).toBe("Field k0, Field k1 and 11 more");
  });
  it("a group with one unsettled member needs you as a whole", () => {
    const same = { required_action: "Contractor to give the value.", finding: "The value is wrong." };
    const rows = buildCrsRows([f("a", same), f("b", { ...same, contractor_page: 4 })], { ...EMPTY_FACTS, pagesNotRead: [4] }, names);
    expect(rows).toHaveLength(1);
    expect(rows[0].tier).toEqual({ tier: "C", label: "Needs you", reason: "page not read" });
  });
  it("a page-reading note and a chat note are not rows", () => {
    const rows = buildCrsRows([
      f("n", { compliance_status: "NEEDS_ENGINEER_REVIEW", ai_rationale: "UNREAD_PAGES: page 4" }),
      f("chat", { origin: "chat", compliance_status: "COMPLIANT" }),
      f("a"),
    ], EMPTY_FACTS, names);
    expect(rows.map((r) => r.item)).toEqual(["Field a"]);
  });
  it("the engineer's earlier answer on the card view shows in the status column", () => {
    const rows = buildCrsRows([f("a"), f("b", { confirmed_by: "eng", contractor_page: 2 })], EMPTY_FACTS, names);
    expect(rows.map((r) => r.status)).toEqual(["Open", "Kept earlier"]);
  });
  it("a finding the engineer already rejected is not a row, and is counted", () => {
    const all = [f("a", { approval_status: "rejected" }), f("m", { compliance_status: "COMPLIANT", approval_status: "rejected" }), f("b")];
    expect(splitRejected(all)).toEqual({ findings: [all[2]], rejected: 2 });
    expect(buildCrsRows(all, EMPTY_FACTS, names).map((r) => r.item)).toEqual(["Field b"]);
  });
  it("every finding that is not a note is a row: a null status and an unknown status need you", () => {
    const rows = buildCrsRows([
      f("nul", { compliance_status: null }), f("odd", { compliance_status: "SOMETHING_NEW" as never, contractor_page: 2 }),
    ], EMPTY_FACTS, names);
    expect(rows.map((r) => [r.item, r.tier.label, r.tier.reason])).toEqual([
      ["Field nul", "Needs you", "condition unsettled"], ["Field odd", "Needs you", "condition unsettled"],
    ]);
  });
  it("a met value on an unread page is a row that needs you: page not read", () => {
    const rows = buildCrsRows([f("m", { compliance_status: "COMPLIANT", contractor_page: 4 })], { ...EMPTY_FACTS, pagesNotRead: [4] }, names);
    expect(rows).toHaveLength(1);
    expect(rows[0].tier).toEqual({ tier: "C", label: "Needs you", reason: "page not read" });
    expect(rows[0].commentNo).toBe(1);
  });
  it("an unconfirmed safety tick is a Needs-you row", () => {
    const rows = buildCrsRows([f("tick", { compliance_status: "COMPLIANT", show_for_engineer_tick: true })], EMPTY_FACTS, names);
    expect(rows.map((r) => [r.tier.label, r.tier.reason])).toEqual([["Needs you", "safety field"]]);
  });
});

describe("visibleRows and the spot check", () => {
  const rows = buildCrsRows([
    f("nc"), f("blank", { compliance_status: "MISSING_INFORMATION", contractor_page: 2 }),
    f("cond", { compliance_status: "CONDITIONAL", contractor_page: 3 }),
    ...Array.from({ length: 40 }, (_, i) => f(`met${i}`, { compliance_status: "COMPLIANT", contractor_page: 5 + i })),
    f("scope", { compliance_status: "NOT_IN_DOCUMENT_SCOPE" }),
  ], EMPTY_FACTS, names);

  it("Standard shows Comment and Needs you; Critical drops the blank; Everything adds Met", () => {
    const none = new Set<string>();
    expect(visibleRows(rows, "standard", false, none).map((r) => r.item)).toEqual(["Field nc", "Field blank", "Field cond"]);
    expect(visibleRows(rows, "critical", false, none).map((r) => r.item)).toEqual(["Field nc", "Field cond"]);
    expect(visibleRows(rows, "everything", false, none)).toHaveLength(rows.length);
    expect(visibleRows(rows, "standard", true, none)).toHaveLength(rows.length);
  });
  it("the spot check is 5% of the Met rows, at least one, and the same on every visit", () => {
    const a = spotCheckKeys(rows, "run-1");
    const b = spotCheckKeys(rows, "run-1");
    expect(a.size).toBe(2);
    expect([...a]).toEqual([...b]);
    for (const key of a) expect(rows.find((r) => r.key === key)?.tier.label).toBe("Met");
    expect(visibleRows(rows, "standard", false, a)).toHaveLength(5);
    expect(visibleRows(rows, "critical", false, a)).toHaveLength(2);
    expect(spotCheckKeys(rows.filter((r) => r.tier.tier !== "A"), "run-1").size).toBe(0);
  });
  it("a confirmed safety tick is Met and always in the spot check", () => {
    const withTick = buildCrsRows([
      f("tick", { compliance_status: "COMPLIANT", show_for_engineer_tick: true, confirmed_by: "eng" }),
      ...Array.from({ length: 10 }, (_, i) => f(`met${i}`, { compliance_status: "COMPLIANT" })),
    ], EMPTY_FACTS, names);
    const spot = spotCheckKeys(withTick, "run-2");
    expect([...spot].some((k) => withTick.find((r) => r.key === k)?.tick)).toBe(true);
  });
  it("counts per tier", () => {
    expect(rowCounts(rows)).toEqual({ met: 40, notApplicable: 0, anotherDocument: 1, comment: 2, needsYou: 1 });
  });
});

describe("crsHeadline", () => {
  const run = {
    by_status: { COMPLIANT: 94, NON_COMPLIANT: 17 }, requirement_split: { does_not_apply: 4362 },
    created_at: "2026-10-15T08:00:00Z", completed_at: "2026-10-15T08:18:00Z",
    page_coverage: { pages_total: 12, fact_pages: [1, 2, 3], pages_not_read_into_fields: [4, 9], not_read_reasons: {} },
  } as unknown as ReviewRunSummary;
  it("is the spec's one line; the met count is the rows' own, not the run's by_status", () => {
    expect(crsHeadline(run, { comment: 17, needsYou: 6, met: 94, notApplicable: 0, anotherDocument: 0 })).toBe(
      "23 comments, 6 need your judgement. 94 values met, 4,362 clauses not applicable (hidden). Read in 18 min; the reader gave up on pages 4 and 9.",
    );
  });
  it("a field the run does not hold renders as nothing, never 0", () => {
    const bare = { by_status: {}, created_at: null, completed_at: null } as unknown as ReviewRunSummary;
    expect(crsHeadline(bare, { comment: 1, needsYou: 0, met: 0, notApplicable: 0, anotherDocument: 0 })).toBe("1 comment.");
    expect(crsHeadline({ ...run, page_coverage: null }, { comment: 0, needsYou: 1, met: 90, notApplicable: 0, anotherDocument: 0 }))
      .toBe("1 comment, 1 needs your judgement. 90 values met, 4,362 clauses not applicable (hidden). Read in 18 min.");
  });
});

describe("headlineFieldsOf", () => {
  const run = {
    requirement_split: { does_not_apply: 4362 },
    page_coverage: { pages_total: 12, fact_pages: [], pages_not_read_into_fields: [4, 9], not_read_reasons: {} },
  } as unknown as ReviewRunSummary;
  it("reads the run's stored fields when there is no server summary", () => {
    expect(headlineFieldsOf(run)).toEqual({ doesNotApply: 4362, unreadPages: [4, 9] });
  });
  it("reads the server's record when it sent one: unread plus timed-out pages, once each, in order", () => {
    expect(headlineFieldsOf(run, {
      requirement_split: { does_not_apply: 12 } as never,
      page_coverage: { pages_total: 12, fact_pages: [], pages_not_read_into_fields: [9, 4], not_read_reasons: {} },
      timed_out_pages: [7, 4],
    })).toEqual({ doesNotApply: 12, unreadPages: [4, 7, 9] });
  });
  it("a field the server does not hold is nothing, not the runs list's copy and never 0", () => {
    expect(headlineFieldsOf(run, { requirement_split: null, page_coverage: null, timed_out_pages: null }))
      .toEqual({ doesNotApply: null, unreadPages: [] });
  });
});
