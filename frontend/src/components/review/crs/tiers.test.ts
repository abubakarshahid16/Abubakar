/**
 * Order 95 piece 2, spec section 2: the screen-only parts of the tiers on
 * invented findings (groups, counts, runFactsOf, the server's tiers).
 *
 * The tierOf rule cases moved to the shared table both engines run
 * (order 133): contracts/fixtures/review_tier_cases.json, run here by
 * tiers.parity.test.ts and on the server by test_133_one_truth_tiers.py.
 */
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import {
  EMPTY_FACTS, type RunFacts, countTiers, countsOfServer, runFactsOf, serverTiersOf, tierFor, tierOf, tierOfGroup,
} from "./tiers";

function f(over: Partial<ReviewFinding>): ReviewFinding {
  return { id: "x", compliance_status: "NON_COMPLIANT", contractor_page: 2, standard_document_id: "std-1", ...over } as ReviewFinding;
}

const facts: RunFacts = {
  pagesNotRead: [4, 9], readerTimedOutPages: [7], missingStandards: ["API 526"], libraryStandardIds: ["std-1"],
};

describe("tierOf: the screen-only default", () => {
  // Every other tierOf case lives in contracts/fixtures/review_tier_cases.json
  // and runs in tiers.parity.test.ts (and on the server, test_133).
  it("called with no facts, tierOf uses EMPTY_FACTS: only the status decides", () => {
    expect(tierOf(f({ contractor_page: 4 }))).toEqual(tierOf(f({ contractor_page: 4 }), EMPTY_FACTS));
    expect(tierOf(f({ contractor_page: 4 })).tier).toBe("B");
  });
});

describe("tierOfGroup and countTiers", () => {
  it("a group takes its most demanding member: C over B over A", () => {
    expect(tierOfGroup([f({}), f({ compliance_status: "CONDITIONAL" })], facts).tier).toBe("C");
    expect(tierOfGroup([f({ compliance_status: "COMPLIANT" }), f({})], facts).tier).toBe("B");
    expect(tierOfGroup([f({ compliance_status: "COMPLIANT" })], facts).tier).toBe("A");
  });
  it("counts per tier keep Met, Not applicable and Another document apart", () => {
    const results = [
      f({ compliance_status: "COMPLIANT" }), f({ compliance_status: "NOT_IN_DOCUMENT_SCOPE" }), f({ compliance_status: "NOT_APPLICABLE" }),
      f({}), f({}), f({ compliance_status: "CONDITIONAL" }),
    ].map((x) => tierOf(x, facts));
    expect(countTiers(results)).toEqual({ met: 1, notApplicable: 1, anotherDocument: 1, comment: 2, needsYou: 1 });
  });
});

describe("runFactsOf", () => {
  const coverage = { pages_total: 10, fact_pages: [1, 2], pages_not_read_into_fields: [4, 9], not_read_reasons: { "9": "AI reader timed out", "4": null } };
  it("reads the run's own stored fields, the reader record and the standards list", () => {
    const facts2 = runFactsOf(
      {
        page_coverage: coverage,
        requirement_split: {
          checked: 2, applies_not_checked: 0, does_not_apply: 0, total: 2,
          reader: { engine: "ollama", pages: 10, timed_out: [7] },
        },
      } as never,
      [{ standard_document_id: "std-1", included: true }, { standard_document_id: "std-2", included: false }] as never,
      [{ identifier: "API 526", status: "MISSING_LOCALLY" }, { identifier: "ASME VIII", status: "OBTAINED" }],
    );
    expect(facts2).toEqual({ pagesNotRead: [4, 9], readerTimedOutPages: [7], missingStandards: ["API 526"], libraryStandardIds: ["std-1"] });
  });
  it("a page note that says 'timed out' is no time-out without a reader record (order 135, D3)", () => {
    // Page 9 stays a page not read into fields; it is not called timed out on a note's words.
    const facts2 = runFactsOf({ page_coverage: coverage, requirement_split: null }, null, []);
    expect(facts2.pagesNotRead).toEqual([4, 9]);
    expect(facts2.readerTimedOutPages).toEqual([]);
  });
  it("a run without a ledger and a failed standards list claim nothing", () => {
    expect(runFactsOf(null, null, [])).toEqual(EMPTY_FACTS);
  });
});

describe("server tiers (order 95 piece 1, #1111)", () => {
  const server = serverTiersOf([
    { finding_id: "x", tier: "C", label: "Needs you", reason: "value conflict" },
    { finding_id: "y", tier: "B", label: "Comment", reason: null },
  ]);
  it("the server's tier wins over the screen's rules for the finding it names", () => {
    expect(tierOf(f({}), facts).tier).toBe("B");
    expect(tierFor(f({}), facts, server)).toEqual({ tier: "C", label: "Needs you", reason: "value conflict" });
    expect(tierFor(f({ id: "y", compliance_status: "CONDITIONAL" }), facts, server)).toEqual({ tier: "B", label: "Comment", reason: null });
    expect(tierOfGroup([f({ id: "y" }), f({})], facts, server).reason).toBe("value conflict");
  });
  it("a finding the server did not name keeps the screen's tier; no server, no change", () => {
    expect(tierFor(f({ id: "z", compliance_status: "CONDITIONAL" }), facts, server).reason).toBe("condition unsettled");
    expect(tierFor(f({}), facts, null)).toEqual(tierOf(f({}), facts));
  });
  it("a Tier C row without a reason still carries one; A and B never do", () => {
    const odd = serverTiersOf([
      { finding_id: "c", tier: "C", label: "Needs you", reason: null },
      { finding_id: "b", tier: "B", label: "Comment", reason: "value conflict" },
    ]);
    expect(odd.get("c")?.reason).toBe("condition unsettled");
    expect(odd.get("b")?.reason).toBeNull();
  });
  it("the server's counts map to the screen's shape", () => {
    expect(countsOfServer({ met: 1, not_applicable: 2, another_document: 3, comment: 4, needs_you: 5, removed: 6, total: 21 }))
      .toEqual({ met: 1, notApplicable: 2, anotherDocument: 3, comment: 4, needsYou: 5 });
  });
});
