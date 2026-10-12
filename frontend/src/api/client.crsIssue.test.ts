/**
 * PF5 (#885): the contractor's copy is ISSUED with a POST the server gates
 * and archives; the internal copy is still a plain GET. A refusal carries the
 * server's own words (the blockers), shown to the engineer as they are.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { reviews } from "./client";

afterEach(() => vi.unstubAllGlobals());

function file(disposition: string | null = null) {
  return { ok: true, status: 200, headers: { get: () => disposition },
           blob: async () => new Blob(["x"]) } as unknown as Response;
}

function respond(response: Response) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("exportCrs", () => {
  it("issues the contractor's copy with a POST to the issue route", async () => {
    const fetchMock = respond(file('attachment; filename="CRS_a_issue-to-contractor.xlsx"'));
    const result = await reviews.exportCrs("run-1", "issue");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/reviews\/runs\/run-1\/crs\/issue$/);
    expect(init?.method).toBe("POST");
    expect(result.ok && result.data.filename).toBe("CRS_a_issue-to-contractor.xlsx");
  });

  it("keeps the internal copy a GET", async () => {
    const fetchMock = respond(file());
    await reviews.exportCrs("run-1", "internal");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/reviews\/runs\/run-1\/crs\?copy=internal$/);
    expect(init?.method).toBe("GET");
  });

  it("passes the server's blockers on in its own words", async () => {
    respond(new Response(JSON.stringify({ detail: { code: "crs_not_finished",
      message: "the contractor's copy is not finished: 1 page(s) of the submittal were not read" } }),
      { status: 409, headers: { "Content-Type": "application/json" } }));
    const result = await reviews.exportCrs("run-1", "issue");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("crs_not_finished");
      expect(result.error.message).toContain("1 page(s) of the submittal were not read");
    }
  });
});
