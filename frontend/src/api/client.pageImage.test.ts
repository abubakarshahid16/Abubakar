import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchImageObjectUrl } from "./client";

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
