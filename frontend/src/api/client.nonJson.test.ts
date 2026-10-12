/**
 * A 200 whose body is not JSON becomes the typed failure every caller
 * already handles - it never rejects.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("request(): unreadable success body", () => {
  it("returns ok:false instead of rejecting", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response("<html>proxy page</html>", { status: 200, headers: { "Content-Type": "text/html" } })));
    const result = await api.health();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.disconnected).toBe(false);
      expect(result.error.message).toMatch(/could not be read/);
      // The proxy page must not be echoed to the reader.
      expect(result.error.message).not.toMatch(/proxy page/);
    }
  });

  it("still returns the data for a JSON body", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const result = await api.health();
    expect(result.ok).toBe(true);
  });
});
