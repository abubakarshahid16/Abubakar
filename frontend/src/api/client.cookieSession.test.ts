/**
 * Item G (order 164.2): the browser's login is an HttpOnly cookie the page
 * cannot read. The page holds no token, marks every request as the app's own
 * (the server's CSRF header), logs in by asking for the cookie, and learns it
 * is still signed in after a reload from `GET /auth/me`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { auth, isSignedIn, onSignedOut, reviews, setCookieSession, setToken, signOutOn401 } from "./client";

function lastRequest(spy: ReturnType<typeof vi.fn>) {
  const [url, init] = spy.mock.calls[spy.mock.calls.length - 1] as [string, RequestInit];
  return { url, init, headers: new Headers(init?.headers) };
}

function stubFetch(body: unknown = {}, status = 200) {
  const spy = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  onSignedOut(null);
  setToken(null);
  setCookieSession(false);
  vi.unstubAllGlobals();
});

describe("the page holds no token and marks its requests", () => {
  it("sends the app's own header on a read and on a write, and no Authorization without a bearer token", async () => {
    const spy = stubFetch({ required: true, user: null });
    await auth.me();
    expect(lastRequest(spy).headers.get("X-Requested-With")).toBe("rag-ui");
    expect(lastRequest(spy).headers.get("Authorization")).toBeNull();
    await auth.logout();
    expect(lastRequest(spy).init.method).toBe("POST");
    expect(lastRequest(spy).headers.get("X-Requested-With")).toBe("rag-ui");
    expect(lastRequest(spy).headers.get("Authorization")).toBeNull();
  });

  it("still sends a bearer token when a bearer login is held (a tool, a test)", async () => {
    const spy = stubFetch({ required: true, user: null });
    setToken("bearer-token-for-a-tool");
    await auth.me();
    expect(lastRequest(spy).headers.get("Authorization")).toBe("Bearer bearer-token-for-a-tool");
  });

  it("marks a spreadsheet download and a page image the same way", async () => {
    const spy = vi.fn(async () => new Response(new Blob(["x"]), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const { fetchImageObjectUrl } = await import("./client");
    await fetchImageObjectUrl("/api/page-image");
    expect(lastRequest(spy).headers.get("X-Requested-With")).toBe("rag-ui");
  });
});

describe("the browser asks for the cookie and is told it is signed in", () => {
  it("logs in with session cookie, so the server sends no token", async () => {
    const spy = stubFetch({ token: null, user: { id: "u", email: "a@b.test", display_name: "A", roles: [] }, expires_in_seconds: 28800 });
    const r = await auth.login("a@b.test", "a-long-enough-password");
    expect(r.ok).toBe(true);
    expect(JSON.parse(String(lastRequest(spy).init.body))).toEqual({
      email: "a@b.test", password: "a-long-enough-password", session: "cookie",
    });
  });

  it("is signed in by the cookie alone, and a 401 ends that", () => {
    expect(isSignedIn()).toBe(false);
    setCookieSession(true);
    expect(isSignedIn()).toBe(true);
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    signOutOn401(401);
    expect(isSignedIn()).toBe(false);
    expect(signedOut).toHaveBeenCalledTimes(1);
  });

  it("marks the contractor copy's POST (the review module's own fetch) as the app's own", async () => {
    const spy = vi.fn(async () => new Response(new Blob(["x"]), { status: 200, headers: { "Content-Disposition": 'attachment; filename="a.xlsx"' } }));
    vi.stubGlobal("fetch", spy);
    await reviews.exportCrs("run-1", "issue");
    expect(lastRequest(spy).init.method).toBe("POST");
    expect(lastRequest(spy).headers.get("X-Requested-With")).toBe("rag-ui");
  });
});
