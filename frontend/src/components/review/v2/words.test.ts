/** Piece H: the plan's cost line (item 1) and what will not run (item 3). Invented values only. */
import { describe, expect, it } from "vitest";

import type { ReviewPlan } from "../../../api/reviewPoints";
import { costWords, wontRunWords } from "./words";

const plan = (over: Record<string, unknown> = {}) => ({
  parts: [
    { name: "rule_check", engine: "not_run", why: "the earlier rule check is switched off" },
    { name: "ai_review", engine: "claude", why: "" },
  ],
  wont_run: [], cost: { at_most_usd: 15, last_review_usd: null, last_review_note: null }, method: "general", ...over,
}) as unknown as ReviewPlan;

describe("costWords", () => {
  it("says the last review's cost only when the server read it", () => {
    expect(costWords(plan({ cost: { at_most_usd: 15, last_review_usd: 2.05, last_review_note: "read from the ledger" } }))).toBe("Cost: about USD 2.05, limit USD 15");
  });
  it("says the cost was not read, never a partial sum or a 0", () => {
    const words = costWords(plan({ cost: { at_most_usd: 15, last_review_usd: null, last_review_note: "the cost of the last review of this paper was not read from the spend ledger" } }));
    expect(words).toBe("Cost: limit USD 15; the cost of the last review of this paper was not read from the spend ledger");
    expect(words).not.toMatch(/about|USD 0\b/);
  });
  it("is the limit alone when there was no earlier review, and nothing when nothing is sent", () => {
    expect(costWords(plan())).toBe("Cost: limit USD 15");
    expect(costWords(plan({ cost: { at_most_usd: null, last_review_usd: null, last_review_note: null } }))).toBeNull();
  });
});

describe("wontRunWords", () => {
  it("under the general review says nothing about the earlier rule check", () => {
    expect(wontRunWords(plan())).toEqual([]);
  });
  it("with the earlier engine still says it", () => {
    expect(wontRunWords(plan({ method: "earlier" }))).toEqual(["The rule check will not run: the earlier rule check is switched off."]);
  });
  it("under the general review still says why the AI review will not run", () => {
    const refused = plan({ parts: [
      { name: "rule_check", engine: "not_run", why: "the earlier rule check is switched off" },
      { name: "ai_review", engine: "not_run", why: "the general review does not run on the local model" },
    ] });
    expect(wontRunWords(refused)).toEqual(["The AI review will not run: the general review does not run on the local model."]);
  });
});
