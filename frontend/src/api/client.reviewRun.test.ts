/**
 * Order 109: a screen showing one review asks for that review only
 * (`GET /api/reviews/runs/{id}`), never for every run. The server's 404 -
 * for a run that is not there and for one the caller may not read alike - is
 * data null, so the screen keeps its own "not found" line.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { reviews } from "./client";

function answer(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("reviews.reviewRun", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for the one run by its id, not the whole list", async () => {
    const fetchMock = answer(200, { review_run_id: "run 1", status: "completed" });
    const r = await reviews.reviewRun("run 1");
    expect(r).toMatchObject({ ok: true, data: { review_run_id: "run 1" } });
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe("/api/reviews/runs/run%201");
  });

  it("a 404 not_found is no run (null), not an error", async () => {
    answer(404, { detail: { code: "not_found", message: "no review run with that id" } });
    expect(await reviews.reviewRun("gone")).toEqual({ ok: true, data: null });
  });

  it("any other failure stays a failure", async () => {
    answer(500, { detail: { code: "internal", message: "boom" } });
    const r = await reviews.reviewRun("x");
    expect(r.ok).toBe(false);
  });
});
