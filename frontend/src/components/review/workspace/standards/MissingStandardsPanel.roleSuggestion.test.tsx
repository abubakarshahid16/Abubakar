/** Order 14 lane E, switch on: a missing standard uploaded here is SUGGESTED as a company standard, never marked here. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const uploadOne = vi.fn();
const setRoleBulk = vi.fn();
vi.mock("../../../../api/client", () => ({
  api: { uploadDisciplines: vi.fn().mockResolvedValue({ ok: true, data: { required: true, choices: ["Mechanical"], default: ["Mechanical"] } }) },
  auth: { me: vi.fn().mockResolvedValue({ ok: true, data: { required: true, user: { id: "u-1", email: "a@example.test", roles: ["admin"] } } }) },
  classification: { setRoleBulk: (...a: unknown[]) => setRoleBulk(...a) },
}));
vi.mock("../../../Uploader", () => ({ uploadOne: (...a: unknown[]) => uploadOne(...a) }));
vi.mock("../../../../api/roleSuggestion", () => ({
  roleSuggestionSwitch: () => Promise.resolve({ enabled: true, review_roles: [] }),
}));

import { SUGGESTED_STANDARD_MESSAGE, uploadMissingStandard } from "./MissingStandardsPanel";

beforeEach(() => {
  uploadOne.mockReset().mockResolvedValue({ phase: "done", documentId: "doc-9", duplicateOf: null, awaitingGrant: false });
  setRoleBulk.mockReset();
});

describe("upload a missing standard, suggested role on", () => {
  it("sends the page, marks nothing and says suggested, confirm or change", async () => {
    const got = await uploadMissingStandard(new File(["x"], "std.pdf"), () => {});
    expect(uploadOne.mock.calls[0][3]).toBe("standards");
    expect(setRoleBulk).not.toHaveBeenCalled();
    expect(got).toEqual({ ok: true, message: SUGGESTED_STANDARD_MESSAGE });
    expect(SUGGESTED_STANDARD_MESSAGE).toContain("Suggested, confirm or change");
  });
});
