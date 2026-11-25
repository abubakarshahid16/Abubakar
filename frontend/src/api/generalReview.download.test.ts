/** A download in a background tab says so (first-time user, 19 Nov): the browser may hold the file and nothing seems to happen. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadGeneralSheet, generalReview } from "./generalReview";

function prepare(visibility: "visible" | "hidden") {
  vi.spyOn(generalReview, "sheet").mockResolvedValue({ ok: true, data: { blob: new Blob(["x"]), filename: "a.xlsx" } } as never);
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => "blob:x";
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => undefined;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
}

afterEach(() => { vi.restoreAllMocks(); });

describe("downloadGeneralSheet", () => {
  it("says nothing when the tab is in front", async () => {
    prepare("visible");
    expect(await downloadGeneralSheet("doc1", "g1")).toBeNull();
  });

  it("says the tab is in the background when it is", async () => {
    prepare("hidden");
    expect(await downloadGeneralSheet("doc1", "g1")).toMatch(/background/);
  });
});
