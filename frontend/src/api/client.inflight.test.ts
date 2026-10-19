/**
 * Order 117 item 6: identical GETs asked for in the same moment share one
 * request. A request still out after that moment is never joined (a hung GET
 * must not hold later ones hostage), nothing is kept (not a cache), a POST, a
 * body or a caller's own abort signal is never shared, and a change of sign-in
 * never reuses a request made under the previous one. Each caller keeps its
 * own shape check.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { hasArrayField, request, setToken } from "./core";

function slowAnswer(body: unknown) {
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => { release = r; });
  const fetchMock = vi.fn(async () => {
    await gate;
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, release };
}

describe("request() shares identical GETs in flight", () => {
  afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

  it("two screens asking at once make one request and both get the answer", async () => {
    const { fetchMock, release } = slowAnswer({ runs: [1] });
    const a = request("/reviews/runs");
    const b = request("/reviews/runs");
    release();
    expect(await a).toMatchObject({ ok: true, data: { runs: [1] } });
    expect(await b).toMatchObject({ ok: true, data: { runs: [1] } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("is not a cache: a request after the first settles goes to the server again", async () => {
    const { fetchMock, release } = slowAnswer({ runs: [] });
    release();
    await request("/reviews/runs");
    await request("/reviews/runs");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a request still out after its moment is never joined, so a hung GET traps nobody", async () => {
    const { fetchMock, release } = slowAnswer({ runs: [] });
    const stuck = request("/reviews/runs");
    await Promise.resolve();
    const later = request("/reviews/runs");
    release();
    await Promise.all([stuck, later]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never shares a POST, a body, extra headers or a caller's own abort signal", async () => {
    const { fetchMock, release } = slowAnswer({});
    const calls = [
      request("/x", { method: "POST" }),
      request("/x", { method: "POST" }),
      request("/x", { signal: new AbortController().signal }),
      request("/x", { signal: new AbortController().signal }),
      request("/x", { headers: { Accept: "application/json" } }),
      request("/x", { headers: { Accept: "application/json" } }),
    ];
    release();
    await Promise.all(calls);
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("a change of sign-in never reuses a request made under the previous one", async () => {
    const { fetchMock, release } = slowAnswer({ runs: [] });
    setToken("first");
    const a = request("/reviews/runs");
    setToken("second");
    const b = request("/reviews/runs");
    release();
    await Promise.all([a, b]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("each caller keeps its own shape check on a shared answer", async () => {
    const { fetchMock, release } = slowAnswer({ runs: [] });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const fine = request("/reviews/runs", undefined, hasArrayField("runs"));
    const wrong = request("/reviews/runs", undefined, hasArrayField("findings"));
    release();
    expect((await fine).ok).toBe(true);
    expect((await wrong).ok).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
