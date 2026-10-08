/**
 * #441: a CRS draft is requested with POST. It sends a run's findings to
 * Claude and spends from the USD caps, so it must never be a GET that a
 * link or a prefetch could start.
 *
 * MUTATION PROOF (run 2026-10-08): change `{ method: "POST" }` to
 * `undefined` in `reviews.claudeCrsDraft` and this test fails.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { reviews } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("reviews.claudeCrsDraft", () => {
  it("requests the draft with POST on the run's crs-draft path", async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ rows: [], drafted: 0, rejected: 0, counts: {}, complete: true, drafted_by: "u1" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const result = await reviews.claudeCrsDraft("run 1");
    expect(result.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/reviews/runs/run%201/claude/crs-draft");
    expect(init.method).toBe("POST");
  });
});
