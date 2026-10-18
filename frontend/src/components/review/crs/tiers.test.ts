/**
 * Order 95 piece 2, spec section 2: every tier rule on invented findings.
 *
 * MUTATION PROOF: swap Tier B and C for MISSING_INFORMATION and "a blank on
 * a read page with the standard in the library" fails; drop the page check
 * and "a met value on an unread page still needs you" fails.
 */
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { EMPTY_FACTS, type RunFacts, countTiers, runFactsOf, tierOf, tierOfGroup } from "./tiers";

function f(over: Partial<ReviewFinding>): ReviewFinding {
  return { id: "x", compliance_status: "NON_COMPLIANT", contractor_page: 2, standard_document_id: "std-1", ...over } as ReviewFinding;
}

const facts: RunFacts = {
  pagesNotRead: [4, 9], readerTimedOutPages: [7], missingStandards: ["API 526"], libraryStandardIds: ["std-1"],
};

describe("tierOf: Tier A", () => {
  it("COMPLIANT is Met", () => {
    expect(tierOf(f({ compliance_status: "COMPLIANT" }), facts)).toEqual({ tier: "A", label: "Met", reason: null });
  });
  it("NOT_IN_DOCUMENT_SCOPE is Another document", () => {
    expect(tierOf(f({ compliance_status: "NOT_IN_DOCUMENT_SCOPE" }), facts)).toEqual({ tier: "A", label: "Another document", reason: null });
  });
  it("NOT_APPLICABLE (does not apply) is Not applicable", () => {
    expect(tierOf(f({ compliance_status: "NOT_APPLICABLE" }), facts).label).toBe("Not applicable");
  });
});

describe("tierOf: Tier B", () => {
  it("NON_COMPLIANT is a Comment", () => {
    expect(tierOf(f({}), facts)).toEqual({ tier: "B", label: "Comment", reason: null });
  });
  it("a blank on a read page with the standard in the library is a Comment", () => {
    expect(tierOf(f({ compliance_status: "MISSING_INFORMATION" }), facts).tier).toBe("B");
  });
  it("a blank when the standards list could not be loaded is still a Comment (a failed list is not an empty one)", () => {
    expect(tierOf(f({ compliance_status: "MISSING_INFORMATION" }), { ...facts, libraryStandardIds: null }).tier).toBe("B");
  });
});

describe("tierOf: Tier C", () => {
  it("NEEDS_ENGINEER_REVIEW needs you: condition unsettled", () => {
    expect(tierOf(f({ compliance_status: "NEEDS_ENGINEER_REVIEW" }), facts)).toEqual({ tier: "C", label: "Needs you", reason: "condition unsettled" });
  });
  it("CONDITIONAL needs you: condition unsettled", () => {
    expect(tierOf(f({ compliance_status: "CONDITIONAL" }), facts).reason).toBe("condition unsettled");
  });
  it("a page in pages_not_read_into_fields: page not read, whatever the status", () => {
    expect(tierOf(f({ contractor_page: 4 }), facts)).toEqual({ tier: "C", label: "Needs you", reason: "page not read" });
    expect(tierOf(f({ contractor_page: 9, compliance_status: "MISSING_INFORMATION" }), facts).reason).toBe("page not read");
  });
  it("a met value on an unread page still needs you", () => {
    expect(tierOf(f({ contractor_page: 4, compliance_status: "COMPLIANT" }), facts).tier).toBe("C");
  });
  it("a page the reader timed out on: page not read", () => {
    expect(tierOf(f({ contractor_page: 7 }), facts).reason).toBe("page not read");
  });
  it("a finding citing a standard in MISSING_LOCALLY: standard not in library", () => {
    const cites = f({ standard_document_id: null, governing_sources: ["API 526 clause 4.1"] });
    expect(tierOf(cites, facts)).toEqual({ tier: "C", label: "Needs you", reason: "standard not in library" });
    const inWhy = f({ ai_rationale: "Could not check: API-526 is not held locally" });
    expect(tierOf(inWhy, facts).reason).toBe("standard not in library");
  });
  it("a blank whose standard is not in the library: standard not in library", () => {
    expect(tierOf(f({ compliance_status: "MISSING_INFORMATION", standard_document_id: "std-gone" }), facts).reason).toBe("standard not in library");
    expect(tierOf(f({ compliance_status: "MISSING_INFORMATION", standard_document_id: null }), facts).reason).toBe("standard not in library");
  });
  it("a value conflict and an unknown unit carry their own words", () => {
    expect(tierOf(f({ ai_rationale: "VALUE CONFLICT: page 3 also states 32 bar" }), facts).reason).toBe("value conflict");
    expect(tierOf(f({ ai_rationale: "Unit unknown for 25 (bar or barg?)" }), facts).reason).toBe("unit unknown");
  });
  it("the page comes before the missing standard in the reason", () => {
    expect(tierOf(f({ contractor_page: 9, standard_document_id: null, governing_sources: ["API 526"] }), facts).reason).toBe("page not read");
  });
  it("a status this table does not know is never swept quietly", () => {
    expect(tierOf(f({ compliance_status: "SOMETHING_NEW" as never }), facts).tier).toBe("C");
    expect(tierOf(f({ compliance_status: null }), facts).tier).toBe("C");
  });
  it("with no facts at all, only the status decides", () => {
    expect(tierOf(f({ contractor_page: 4 }), EMPTY_FACTS).tier).toBe("B");
    expect(tierOf(f({ contractor_page: 4 })).tier).toBe("B");
  });
});

describe("tierOf: a met value nobody has confirmed yet needs you", () => {
  it("a safety tick (show_for_engineer_tick, COMPLIANT, no confirmed_by): safety field", () => {
    expect(tierOf(f({ compliance_status: "COMPLIANT", show_for_engineer_tick: true }), facts))
      .toEqual({ tier: "C", label: "Needs you", reason: "safety field" });
  });
  it("a safety tick the engineer confirmed is Met", () => {
    expect(tierOf(f({ compliance_status: "COMPLIANT", show_for_engineer_tick: true, confirmed_by: "eng" }), facts).label).toBe("Met");
  });
  it("mirrors _pairing_unconfirmed: a field paired by name is an AI guess, whatever the status", () => {
    expect(tierOf(f({ compliance_status: "COMPLIANT", match_method: "field_name" }), facts))
      .toEqual({ tier: "C", label: "Needs you", reason: "AI guess" });
    expect(tierOf(f({ match_method: "field_name" }), facts).reason).toBe("AI guess");
  });
  it("mirrors _pairing_unconfirmed: a model pairing held for review is an AI guess; a model pairing that met is not", () => {
    expect(tierOf(f({ compliance_status: "NEEDS_ENGINEER_REVIEW", match_method: "model" }), facts))
      .toEqual({ tier: "C", label: "Needs you", reason: "AI guess" });
    expect(tierOf(f({ compliance_status: "COMPLIANT", match_method: "model" }), facts).label).toBe("Met");
  });
  it("a rule not yet proven (trust_label UNPROVEN): rule not proven", () => {
    expect(tierOf(f({ compliance_status: "COMPLIANT", trust_label: "UNPROVEN" }), facts))
      .toEqual({ tier: "C", label: "Needs you", reason: "rule not proven" });
    expect(tierOf(f({ compliance_status: "COMPLIANT", trust_label: "AUTO_PROVEN" }), facts).label).toBe("Met");
  });
  it("the unread page still comes first in the reason", () => {
    expect(tierOf(f({ contractor_page: 4, compliance_status: "COMPLIANT", match_method: "field_name" }), facts).reason).toBe("page not read");
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
  it("reads the run's own stored fields and the standards list", () => {
    const facts2 = runFactsOf(
      { page_coverage: { pages_total: 10, fact_pages: [1, 2], pages_not_read_into_fields: [4, 9], not_read_reasons: { "9": "AI reader timed out", "4": null } } },
      [{ standard_document_id: "std-1", included: true }, { standard_document_id: "std-2", included: false }] as never,
      [{ identifier: "API 526", status: "MISSING_LOCALLY" }, { identifier: "ASME VIII", status: "OBTAINED" }],
    );
    expect(facts2).toEqual({ pagesNotRead: [4, 9], readerTimedOutPages: [9], missingStandards: ["API 526"], libraryStandardIds: ["std-1"] });
  });
  it("a run without a ledger and a failed standards list claim nothing", () => {
    expect(runFactsOf(null, null, [])).toEqual(EMPTY_FACTS);
  });
});
