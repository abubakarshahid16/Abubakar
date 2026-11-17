/**
 * Order 14 LPS S2: with the redesigned page on, the review list's "Found by the review" number has ONE home, the paper's page
 * (`GET /api/reviews/page-counts`, the same `found_of` the page reads). A run's own finding count (0 for an AI review) is never
 * shown then, not even when the page numbers fail. Invented ids and numbers.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { foundLine, pageFoundLine } from "../../inbox/inboxState";
import { loadReadyCounts } from "./readyCounts";

const sw = vi.fn();
const pageCounts = vi.fn();
const reviewRunCounts = vi.fn();
vi.mock("../../../../api/reviewPoints", () => ({
  pageV2Switch: () => sw(),
  reviewPoints: { pageCounts: (...a: unknown[]) => pageCounts(...a) },
}));
vi.mock("../../../../api/client", () => ({ reviews: { reviewRunCounts: (...a: unknown[]) => reviewRunCounts(...a) } }));

const PAGE = { not_met: 1, questions: 72, met: 1, does_not_apply: 53, to_confirm: 42, points: 169, undecided: 169, runs: { rule_check: "rc-1", ai_review: "ai-1" } };

beforeEach(() => {
  for (const m of [sw, pageCounts, reviewRunCounts]) m.mockReset();
  // the run's own count: an AI review's run holds no rule-check findings, so it says 0
  reviewRunCounts.mockResolvedValue({ ok: true, data: { counts: { "ai-1": { comment: 0, needs_you: 0 } } } });
});

describe("LPS S2: the review list says what the paper's page shows", () => {
  it("with the page on, says the page's tiles with their boundary, never the run's 0", async () => {
    sw.mockResolvedValue(true);
    pageCounts.mockResolvedValue({ ok: true, data: { boundary: "b", found: { "ai-1": PAGE } } });
    const got = await loadReadyCounts(["ai-1", "old-1"]);
    expect(reviewRunCounts).not.toHaveBeenCalled();
    expect(got["old-1"]).toBeNull(); // an older run: the page shows the newest, so nothing is said for it
    const line = foundLine(got["ai-1"]);
    expect(line).toBe("Found by the review: 1 not met, 72 questions for you (169 points on its review page, 169 not decided yet)");
    expect(line).not.toMatch(/\b0 findings\b/);
  });

  it("with the page on and its numbers unreadable, says nothing (null), never the run's 0", async () => {
    sw.mockResolvedValue(true);
    pageCounts.mockResolvedValue({ ok: false, error: { message: "x" } });
    expect(await loadReadyCounts(["ai-1"])).toEqual({ "ai-1": null });
    pageCounts.mockRejectedValue(new Error("down"));
    expect(await loadReadyCounts(["ai-1"])).toEqual({ "ai-1": null });
    expect(reviewRunCounts).not.toHaveBeenCalled();
  });

  it("with the page off, the run counts stay as before", async () => {
    sw.mockResolvedValue(false);
    reviewRunCounts.mockResolvedValue({ ok: true, data: { counts: { "rc-1": { comment: 3, needs_you: 1 } } } });
    const got = await loadReadyCounts(["rc-1"]);
    expect(pageCounts).not.toHaveBeenCalled();
    expect(foundLine(got["rc-1"])).toBe("Found by the review: 4 findings, 1 needing your judgement");
  });

  it("open points are always said: zero tiles with lines still to decide name them; all decided says so", () => {
    expect(pageFoundLine({ ...PAGE, not_met: 0, questions: 0, points: 42, undecided: 42 }))
      .toBe("Found by the review: 0 not met, 0 questions for you (42 points on its review page, 42 not decided yet)");
    expect(pageFoundLine({ ...PAGE, not_met: 0, questions: 1, points: 1, undecided: 0 }))
      .toBe("Found by the review: 0 not met, 1 question for you (1 point on its review page, all decided)");
  });
});
