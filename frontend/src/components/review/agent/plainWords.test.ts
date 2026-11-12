/**
 * The one mapping of the AI review's plain words (U2). MUTATION PROOF: drop a
 * row of KNOWN and its old -> new test fails; let a raw reason through and the
 * banned-word test fails; name a line by its id and the lineName test fails.
 */
import { describe, expect, it } from "vitest";

import type { AgentLine } from "../../../types/api";
import {
  UNKNOWN_WHY, aiHeadline, classCountsSentence, countsSentence, hasBannedWord, humanizeCode, lineName, openPoints, plainReason,
} from "./plainWords";

const L = (over: Partial<AgentLine>): AgentLine => ({
  item_id: "S-EQ-04", verdict_class: "Query for the engineer", word: "Query", page: 1, clause: "4.2", rule_book: "Book A",
  reason: "", rule_tier: null, ...over,
});

describe("plainReason: what the code saw, in words", () => {
  const table: [string, string][] = [
    ["second opinion model is the same or unknown; first verdict GREEN",
      "The second check could not be shown to come from a different model, so this stays an opinion."],
    ["second opinion disagreed; first verdict RED", "The second AI reader disagreed with the first."],
    ["no second opinion; first verdict GREEN", "No second AI reader checked this, so it stays an opinion."],
    ["the AI did not give pass or fail", "The AI did not decide."],
    ["no figure with its unit inside both quotes", "The value and its unit were not found together in the quoted text."],
    ["the paper is silent on this; a missing statement is not a failure",
      "The AI found no line for this on the pages it read; a program cannot show that this is missing."],
    ["AI call failed: boom claude-sonnet-x", "The AI gave no answer."],
    ["paper quote not verified by code (not on the page)", "Code could not match the quoted text to the page."],
    ["code could not compare the figures (units differ)", "Code could not compare the figures."],
  ];
  it.each(table)("%s", (old, plain) => expect(plainReason(old)).toBe(plain));

  it("never lets first verdict, a colour, an id or a model name through", () => {
    for (const [old] of table) expect(hasBannedWord(plainReason(old))).toBe(false);
    expect(plainReason("odd_code_word here")).toBe("Reason not shown in plain words. Open the trace.");
    expect(plainReason("odd_code_word here")).toBe(UNKNOWN_WHY);
    expect(plainReason("sweep finding, first verdict RED: left to the engineer")).not.toMatch(/RED|first verdict/);
  });
  it("a sentence of the AI's own with no code word is kept; an empty reason stays empty", () => {
    expect(plainReason("The datasheet gives 12 bar, the rule asks 15 bar")).toBe("The datasheet gives 12 bar, the rule asks 15 bar.");
    expect(plainReason(null)).toBe("");
  });
});

describe("lineName: what a line is, not its id", () => {
  it("a checklist point and a rule", () => {
    expect(lineName(L({}))).toEqual({ title: "Checklist point 4 (Book A 4.2)", id: "S-EQ-04" });
    expect(lineName(L({ item_id: "R-614e60d6-1111-2222-3333-444455556666" })).title).toBe("Rule: Book A 4.2");
    expect(lineName(L({ item_id: "X9", rule_book: "", clause: "" })).title).toBe("Point");
  });
  it("the title is never the id", () => {
    for (const id of ["S-EQ-04", "R-614e60d6-1111-2222-3333-444455556666", "S-12"]) expect(hasBannedWord(lineName(L({ item_id: id })).title)).toBe(false);
  });
});

describe("humanizeCode and the counts", () => {
  it("an internal equipment word becomes words", () => {
    expect(humanizeCode("another equipment type: 4 rules not asked (pressure_relief 2, static 2)"))
      .toBe("another equipment type: 4 rules not asked (pressure relief 2, static 2)");
  });
  it("says every count in plain words, over this review's lines, and always says proven by code", () => {
    const lines = [
      ...Array.from({ length: 7 }, () => L({ verdict_class: "AI opinion, engineer to confirm", word: "AI thinks: not met" })),
      ...Array.from({ length: 13 }, () => L({})),
      ...Array.from({ length: 4 }, () => L({ verdict_class: "Not applicable", word: "Not applicable" })),
    ];
    expect(countsSentence(lines, true)).toBe(
      "7 points the AI says are not met, 13 questions for the engineer, 4 rules that do not apply, 0 proven by code",
    );
    // the proven class is said only when the summary carries it
    expect(countsSentence(lines)).not.toMatch(/proven by code/);
  });
  it("open points are everything but Pass and not applicable", () => {
    expect(openPoints([
      L({ verdict_class: "Proven by code", word: "Pass" }), L({ verdict_class: "Proven by code", word: "Fail" }),
      L({ verdict_class: "Not applicable", word: "Not applicable" }), L({}),
    ])).toBe(2);
  });
  it("the class-count fallback splits no opinion", () => {
    expect(classCountsSentence({ "AI opinion, engineer to confirm": 2, "Query for the engineer": 1 }))
      .toBe("2 AI opinions, you confirm, 1 question for the engineer");
    expect(classCountsSentence({ "Proven by code": 0, "Query for the engineer": 1 })).toBe("1 question for the engineer, 0 proven by code");
  });
  it("the headline says the number and the next step", () => {
    expect(aiHeadline(20).headline).toBe("AI review: 20 points are still open.");
    expect(aiHeadline(null).headline).toMatch(/could not be counted/);
  });
});
