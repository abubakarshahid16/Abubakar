/** The one-line plain summary on top of a query (owner's E5, 26 Nov 2026). Invented queries. */
import { describe, expect, it } from "vitest";

import { querySummary } from "./technicalQuerySummary";

describe("querySummary", () => {
  it("says where a query stands and what is missing, in plain words", () => {
    expect(querySummary({ status: "drafting", proposed_question: "Invented?", evidence: [{ evidence_state: "proposed" }, { evidence_state: "verified" }], drafts: [] }, "2026-11-26"))
      .toBe("Being answered: the question is proposed, not confirmed yet; 1 of 2 quotes found kept as evidence; no answer written yet.");
  });
  it("says late only past the due date, and the date", () => {
    const base = { status: "awaiting_review", confirmed_question: "Invented?", evidence: [], drafts: [{}] };
    expect(querySummary({ ...base, due_at: "2026-11-20" }, "2026-11-26")).toMatch(/late: it was due on 2026-11-20\.$/);
    expect(querySummary({ ...base, due_at: "2026-11-30" }, "2026-11-26")).toMatch(/due on 2026-11-30\.$/);
    expect(querySummary(base, "2026-11-26")).toBe("Answer waiting for an engineer's approval: no evidence found yet; an answer is written.");
  });
  it("a closed query says only that it is closed, never late", () => {
    expect(querySummary({ status: "resolved", due_at: "2026-01-01" }, "2026-11-26")).toBe("Closed: answered and confirmed.");
  });
});
