/**
 * Order 123 item 1: a file dropped on "New review" is marked a contractor
 * submittal before its review starts, and every way that can fail is said.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { prepareSubmittal } from "./newReview";

const setRoleBulk = vi.fn();
vi.mock("../../api/client", () => ({
  classification: { setRoleBulk: (...args: unknown[]) => setRoleBulk(...args) },
}));

const done = (over: Partial<{ documentId: string; duplicateOf: string | null; awaitingGrant: boolean }> = {}) => ({
  phase: "done" as const, documentId: "doc-1", duplicateOf: null, awaitingGrant: false, ...over,
});
const written = (id: string) => ({
  ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: [id], unchanged: [], failed: [] },
});

beforeEach(() => setRoleBulk.mockReset());

describe("prepareSubmittal", () => {
  it("marks the uploaded document a contractor submittal and names it", async () => {
    setRoleBulk.mockResolvedValue(written("doc-1"));
    expect(await prepareSubmittal("pump.pdf", done())).toEqual({ ok: true, documentId: "doc-1" });
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-1"], document_role: "CONTRACTOR_SUBMITTAL" });
  });

  it("uses the stored copy when the same bytes were uploaded before", async () => {
    setRoleBulk.mockResolvedValue(written("doc-old"));
    expect(await prepareSubmittal("pump.pdf", done({ documentId: "", duplicateOf: "doc-old" })))
      .toEqual({ ok: true, documentId: "doc-old" });
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-old"], document_role: "CONTRACTOR_SUBMITTAL" });
  });

  it("stops, without touching the role, when the reader may not see the stored copy", async () => {
    const result = await prepareSubmittal("pump.pdf", done({ awaitingGrant: true }));
    expect(result.ok).toBe(false);
    expect(result.ok ? "" : result.message).toMatch(/administrator must grant access/);
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("says the upload failed, in the server's words", async () => {
    const result = await prepareSubmittal("pump.pdf", { phase: "error", code: "too_large", message: "The file is too large." });
    expect(result).toEqual({ ok: false, message: "pump.pdf was not uploaded: The file is too large." });
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("stops when the role could not be set", async () => {
    setRoleBulk.mockResolvedValue({ ok: false, error: { code: "forbidden", message: "Administrators only." } });
    expect(await prepareSubmittal("pump.pdf", done()))
      .toEqual({ ok: false, message: "pump.pdf could not be marked a contractor submittal: Administrators only." });
  });

  it("reads a 207: the one document in `failed` was not written", async () => {
    setRoleBulk.mockResolvedValue({
      ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: [], unchanged: [],
        failed: [{ document_id: "doc-1", reason: "not_found" }] },
    });
    const result = await prepareSubmittal("pump.pdf", done());
    expect(result.ok).toBe(false);
  });
});
