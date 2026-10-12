import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchImageObjectUrl, isSignedIn, onSignedOut, reviews, setToken } from "./client";

describe("page image answer-location metadata", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves X-Answer-Located=0 for the evidence view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        headers: { get: (name: string) => (name === "X-Answer-Located" ? "0" : null) },
        blob: async () => new Blob(["image"]),
      })),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-image");

    const result = await fetchImageObjectUrl("/api/page-image");

    expect(result).toMatchObject({ url: "blob:test-image", answerLocated: false });
  });
});

describe("audit 2026-09-30: a 401 on a binary fetch signs out like the JSON path", () => {
  afterEach(() => {
    onSignedOut(null);
    setToken(null);
    vi.unstubAllGlobals();
  });

  function answer401() {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  }

  it("clears the token and tells the app when a page image is refused", async () => {
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    setToken("expired-token");
    answer401();

    const result = await fetchImageObjectUrl("/api/page-image");

    expect(result.url).toBeNull();
    expect(signedOut).toHaveBeenCalledTimes(1);
    expect(isSignedIn()).toBe(false);
  });

  it("clears the token and tells the app when the CRS workbook is refused", async () => {
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    setToken("expired-token");
    answer401();

    const result = await reviews.exportCrs("run-1");

    expect(result.ok).toBe(false);
    expect(signedOut).toHaveBeenCalledTimes(1);
    expect(isSignedIn()).toBe(false);
  });

  it("keeps the session on a page image that is simply missing", async () => {
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    setToken("good-token");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));

    await fetchImageObjectUrl("/api/page-image");

    expect(signedOut).not.toHaveBeenCalled();
    expect(isSignedIn()).toBe(true);
  });
});
