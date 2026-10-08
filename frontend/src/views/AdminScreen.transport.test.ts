/**
 * The admin transport shares the app's sign-out-on-401 and survives a body
 * that is not JSON.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { isSignedIn, onSignedOut, setToken } from "../api/client";
import { makeAdminClient } from "./AdminScreen";

afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

describe("makeAdminClient transport", () => {
  it("a 401 signs the app out, once", async () => {
    setToken("t");
    const seen = vi.fn();
    onSignedOut(seen);
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "unauthenticated", message: "x" } }), {
        status: 401, headers: { "Content-Type": "application/json" },
      })));
    const result = await makeAdminClient(() => "t").users();
    expect(result.ok).toBe(false);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(isSignedIn()).toBe(false);
    onSignedOut(null);
  });

  it("a non-JSON 200 is a failure result, not a rejection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response("<html>proxy</html>", { status: 200, headers: { "Content-Type": "text/html" } })));
    const result = await makeAdminClient(() => "t").users();
    expect(result.ok).toBe(false);
  });
});
