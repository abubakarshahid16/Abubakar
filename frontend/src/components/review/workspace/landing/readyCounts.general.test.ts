/** Order 14: a general review's counts are its OWN numbers, never "0 findings" (the #1899 blocker). Invented ids only. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const reviewRunCounts = vi.fn();
vi.mock("../../../../api/client", () => ({ reviews: { reviewRunCounts: (...a: unknown[]) => reviewRunCounts(...a) } }));

import { foundLine, generalLine } from "../../inbox/inboxState";
import { loadReadyCounts } from "./readyCounts";

beforeEach(() => reviewRunCounts.mockReset());

describe("loadReadyCounts with a general review", () => {
  it("gives a general run its own numbers and no tiers, and an earlier run its tiers", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: { old: { comment: 4, needs_you: 2 } },
      general: { gen: { points: 129, comments: 66, confirmations: 20, stopped: false } } } });
    const got = await loadReadyCounts(["old", "gen"]);
    expect(got.old).toEqual({ findings: 6, needs_you: 2 });
    expect(got.gen).toEqual({ findings: null, needs_you: null, general: { points: 129, comments: 66, confirmations: 20, stopped: false } });
  });

  it("a server that sends no general part (an older server) changes nothing", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: { old: { comment: 1, needs_you: 0 } } } });
    expect(await loadReadyCounts(["old", "gen"])).toEqual({ old: { findings: 1, needs_you: 0 }, gen: null });
  });
});

describe("what a general review's line says", () => {
  it("states the new method's numbers, labelled, never the earlier method's words", () => {
    const line = foundLine({ findings: null, needs_you: null, general: { points: 129, comments: 66, confirmations: 20 } });
    expect(line).toBe("Review: 129 points reviewed, 66 comments sent (20 confirmations not sent)");
    expect(line).not.toMatch(/findings|needing your judgement/);
  });

  it("leaves out a count it does not have, says 0 only when it is 0, and says a run stopped early", () => {
    expect(generalLine({ points: 10, comments: 0 })).toBe("Review: 10 points reviewed, 0 comments sent");
    expect(generalLine({ points: 1, comments: 1, confirmations: 1, stopped: true })).toBe(
      "Review: 1 point reviewed, 1 comment sent (1 confirmation not sent); stopped early");
  });

  it("a count that is not known renders as nothing", () => {
    expect(foundLine({ findings: null, needs_you: null })).toBe("");
  });
});

describe("H8: the earlier AI reviewer's rows", () => {
  it("loadReadyCounts carries the AI lines of a run that has some", async () => {
    reviewRunCounts.mockResolvedValue({ ok: true, data: { boundary: "", counts: { ai: { comment: 0, needs_you: 0 }, plain: { comment: 0, needs_you: 0 } }, ai_lines: { ai: 55 } } });
    const got = await loadReadyCounts(["ai", "plain"]);
    expect(got.ai).toEqual({ findings: 0, needs_you: 0, aiLines: 55 });
    expect(got.plain).toEqual({ findings: 0, needs_you: 0 });
  });

  it("says AI review: N lines (earlier method), never '0 findings', when the findings table has none", () => {
    const line = foundLine({ findings: 0, needs_you: 0, aiLines: 55 });
    expect(line).toBe("AI review: 55 lines (earlier method)");
    expect(line).not.toMatch(/0 findings/);
  });

  it("adds the findings only when the findings table truly has rows", () => {
    expect(foundLine({ findings: 12, needs_you: 3, aiLines: 1 })).toBe(
      "AI review: 1 line (earlier method). Found by the review: 12 findings, 3 needing your judgement");
  });

  it("a run with no AI line keeps its findings line, and 0 is said only where it is truly 0", () => {
    expect(foundLine({ findings: 0, needs_you: 0 })).toBe("Found by the review: 0 findings, 0 needing your judgement");
  });
});
