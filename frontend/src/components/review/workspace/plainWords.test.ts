/**
 * Builder C: the one plain-words table.
 *
 * MUTATION PROOF (checked by hand once): change one word in reviewFormat's
 * STATUS_LABEL or in REASON_WORDS and "keeps every existing word" fails;
 * let plainWords return the code as its own words for an unknown code and
 * "humanises an unknown code" fails; drop the prefix rewrite in plainText
 * and "rewrites codes inside free text" fails; let plainRow touch findings
 * and "plainRow returns a copy" fails.
 */
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { REMOVAL_REASON_WORDS } from "../crs/evidenceNav";
import type { CrsRow } from "../crs/crsRows";
import { tierOf } from "../crs/tiers";
import { RUN_STATUS_LABEL, STATUS_LABEL, TRUST_WORDS } from "../reviewFormat";
import { PLAIN_KINDS } from "./contract";
import { CODE_WORDS, LOOKUP_ORDER, PLAIN_WORDS, REASON_WORDS, codesIn, plainRow, plainText, plainWords } from "./plainWords";

/** The words as they stood in CrsEvidenceDrawer and DecisionCard before they
 *  moved into the table, copied byte for byte from the earlier commit. */
const OLD_REASON_WORDS: Record<string, string> = {
  "page not read": "The reader did not read this page into fields, so the value may still be on the page. Read the page yourself.",
  "standard not in library": "The standard this comment rests on is not in the library, so the clause could not be checked. Upload it, or decide from the datasheet.",
  "AI guess": "The datasheet field was paired with this clause by an AI guess that nobody has confirmed. Check that the field is the one the clause means.",
  "rule not proven": "The rule behind this row has not been proven yet, so its answer is not trusted on its own. Check it against the standard.",
  "safety field": "This is a safety field. It meets the standard, but it is shown for your own tick before it goes on the record.",
  "condition unsettled": "The rule has a condition the computer could not settle. Decide whether it applies here.",
  "value conflict": "The datasheet gives two values for this field. Decide which one counts.",
  "unit unknown": "The unit of the value could not be read, so it was not compared. Check the unit on the page.",
};
const OLD_CODE_WORDS: Record<string, string> = {
  "Approved": "Everything checked meets the standard; the contractor may go ahead.",
  "Approved with Comments": "The contractor may go ahead and must answer our comments.",
  "Rejected / Revise and Resubmit": "The contractor must fix the comments and send it again.",
  "Manual Review Required": "Not decided here; it needs a fuller engineering review.",
};

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return { id: "f-1", compliance_status: "NON_COMPLIANT", finding: "x", ...over } as ReviewFinding;
}

describe("PLAIN_WORDS keeps every existing word", () => {
  const sources: [keyof typeof PLAIN_WORDS, Record<string, string>][] = [
    ["reason", OLD_REASON_WORDS],
    ["code", OLD_CODE_WORDS],
    ["removal", REMOVAL_REASON_WORDS],
    ["trust", TRUST_WORDS],
    ["status", STATUS_LABEL],
    ["runStatus", RUN_STATUS_LABEL],
  ];
  it.each(sources)("%s: every entry has identical words", (kind, source) => {
    expect(Object.keys(source).length).toBeGreaterThan(0);
    expect(PLAIN_WORDS[kind]).toEqual(source);
    for (const [code, words] of Object.entries(source)) {
      expect(plainWords(code, kind).words).toBe(words);
    }
  });

  it("the moved maps are the ones the old screens read", () => {
    expect(REASON_WORDS).toBe(PLAIN_WORDS.reason);
    expect(CODE_WORDS).toBe(PLAIN_WORDS.code);
  });

  it("tier: every label tiers.ts gives is listed as itself, with no Details", () => {
    const statuses = ["COMPLIANT", "NOT_APPLICABLE", "NOT_IN_DOCUMENT_SCOPE", "NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW"];
    const labels = new Set(statuses.map((s) => tierOf(finding({ compliance_status: s as ReviewFinding["compliance_status"] })).label));
    expect(labels).toEqual(new Set(["Met", "Not applicable", "Another document", "Comment", "Needs you"]));
    for (const label of labels) expect(plainWords(label, "tier")).toEqual({ words: label, detail: null });
  });

  it("engine and rule tables cover the codes shown today", () => {
    expect(PLAIN_WORDS.engine).toHaveProperty("no_field_matched");
    expect(PLAIN_WORDS.engine).toHaveProperty("ambiguous_match");
    expect(plainWords("p4", "rule").words).toBe("Review rule 4");
  });

  it("looks tables up in the contract's order", () => {
    expect([...LOOKUP_ORDER]).toEqual([...PLAIN_KINDS]);
  });
});

describe("plainWords", () => {
  it("a known code: plain words, the code as detail", () => {
    const e = plainWords("no_field_matched", "engine");
    expect(e.detail).toBe("no_field_matched");
    expect(e.words).not.toMatch(/_/);
    expect(e.words.length).toBeGreaterThan(0);
    expect(plainWords("NON_COMPLIANT")).toEqual({ words: "Non-compliant", detail: "NON_COMPLIANT" });
    expect(plainWords("p4")).toEqual({ words: "Review rule 4", detail: "p4" });
  });

  it("humanises an unknown code, keeping the code as detail", () => {
    expect(plainWords("value_conflict_x", "engine")).toEqual({ words: "Value conflict x", detail: "value_conflict_x" });
    expect(plainWords("brand_new_reason")).toEqual({ words: "Brand new reason", detail: "brand_new_reason" });
    expect(plainWords("DS-Z9", "rule")).toEqual({ words: "Datasheet check", detail: "DS-Z9" });
  });

  it("already plain words come back with no Details", () => {
    expect(plainWords("Met")).toEqual({ words: "Met", detail: null });
    expect(plainWords("Pump casing material")).toEqual({ words: "Pump casing material", detail: null });
  });

  it("never returns empty words for a non-empty code", () => {
    for (const code of ["___", "-", "_x_", "p0", "DS-", "A_", "Z", "UNKNOWN_THING", "queued"]) {
      for (const kind of [...PLAIN_KINDS, "any"] as const) {
        expect(plainWords(code, kind).words, `${code} / ${kind}`).not.toBe("");
      }
    }
    expect(plainWords("")).toEqual({ words: "", detail: null });
    expect(plainWords(null)).toEqual({ words: "", detail: null });
  });
});

describe("plainText", () => {
  it("rewrites codes inside free text", () => {
    expect(plainText("no_field_matched: no field read from this datasheet names the flange rating (rule p4)."))
      .toBe("No field read from this datasheet names the flange rating (review rule 4).");
    expect(plainText("Marked NON_COMPLIANT by Rule p12")).toBe("Marked non-compliant by Review rule 12");
    expect(plainText("Datasheet check DS-M1: Rated flow is a mandatory field."))
      .toBe("Datasheet check (a required field is missing): Rated flow is a mandatory field.");
    expect(plainText("p4: Seal plan is not stated")).toBe("Review rule 4: Seal plan is not stated");
    expect(plainText("UNREAD_PAGES: the value may be on page 9")).toBe("The value may be on page 9");
  });

  it("leaves text with no code exactly as it was", () => {
    for (const t of ["", "Contractor to state the rated flow.", "See p. 4 of the datasheet", "API 610 clause 6.1"]) {
      expect(plainText(t)).toBe(t);
    }
  });

  it("codesIn names each code once, in order", () => {
    expect(codesIn("no_field_matched: flange (rule p4), NON_COMPLIANT; rule p4 again"))
      .toEqual([
        { code: "no_field_matched", kind: "engine" },
        { code: "p4", kind: "rule" },
        { code: "NON_COMPLIANT", kind: "status" },
      ]);
    expect(codesIn("Plain words only")).toEqual([]);
  });
});

describe("plainRow returns a copy", () => {
  const findings = [finding()];
  const tier = { tier: "B" as const, label: "Comment" as const, reason: null };
  const row: CrsRow = {
    key: "k-1", findings, tier, commentNo: 1, pageOrSection: "p. 4", item: "Flange rating",
    clauseAndStandard: "API 610, clause 6.1", observation: "ambiguous_match: two fields could be the flange rating",
    requiredAction: "Contractor to confirm (rule p4).", status: "Open", priorState: "open", tick: false, page: 4,
  };
  it("with plain observation, required action and status; key, tier and findings untouched", () => {
    const out = plainRow(row);
    expect(out).not.toBe(row);
    expect(out.observation).toBe("Two fields could be the flange rating");
    expect(out.requiredAction).toBe("Contractor to confirm (review rule 4).");
    expect(out.status).toBe("Open");
    expect(out.key).toBe(row.key);
    expect(out.tier).toBe(tier);
    expect(out.findings).toBe(findings);
    expect(row.observation).toBe("ambiguous_match: two fields could be the flange rating");
  });
});
