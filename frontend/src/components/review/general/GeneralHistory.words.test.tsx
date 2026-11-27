/** H's review of the owner's real file (27 Nov 2026), R6: the history in words. Invented values. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../api/generalReview", () => ({
  generalReview: {
    history: () => Promise.resolve({ ok: true, data: { boundary: "reviews you may open", runs: [
      { run_id: "r3", version: "general", part: "general review", status: "stopped", finished_at: "2026-11-26T09:00:00Z", points: 0 },
      { run_id: "r2", version: "general", part: "general review", status: "completed", finished_at: "2026-11-18T09:00:00Z", points: 39 },
      { run_id: "r1", version: "earlier", part: "rule check", status: "done", finished_at: "2026-11-17T09:00:00Z", points: null },
    ] } }),
  },
}));

import { GeneralHistory } from "./GeneralHistory";

describe("the history in words (R6)", () => {
  it("names the newest review, says each state and date in words, and never the internal part name", async () => {
    render(<GeneralHistory documentId="d1" />);
    const items = (await screen.findAllByRole("listitem")).map((li) => li.textContent);
    expect(items).toEqual([
      "Latest review of 26 Nov 2026 (stopped early, 0 points)",
      "Review of 18 Nov 2026 (complete, 39 points)",
      "Older kind of review of 17 Nov 2026 (rule check, complete)",
    ]);
  });
});
