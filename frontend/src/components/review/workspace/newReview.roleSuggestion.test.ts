/** Order 14 lane E, switch on: a new upload on the review page is NOT marked silently; once read in, its suggested role is
 *  shown ("suggested, confirm or change") and the administrator confirms through the existing mark-and-review step. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const uploadOne = vi.fn();
const setRoleBulk = vi.fn();
const ofDocument = vi.fn();
vi.mock("../../../api/client", () => ({
  api: {
    uploadDisciplines: vi.fn().mockResolvedValue({ ok: true, data: { required: true, choices: ["Mechanical"], default: ["Mechanical"] } }),
    document: vi.fn().mockResolvedValue({ ok: true, data: { id: "doc-1", status: "ready", document_role: null } }),
  },
  auth: { me: vi.fn().mockResolvedValue({ ok: true, data: { required: true, user: { id: "u-1", email: "a@example.test", roles: ["admin"] } } }) },
  classification: {
    setRoleBulk: (...a: unknown[]) => setRoleBulk(...a),
    ofDocument: (...a: unknown[]) => ofDocument(...a),
  },
  reviews: { reviewRuns: vi.fn().mockResolvedValue({ ok: true, data: { runs: [] } }), readiness: vi.fn() },
}));
vi.mock("../../Uploader", () => ({ uploadOne: (...a: unknown[]) => uploadOne(...a) }));
vi.mock("./reviewWatch", () => ({ watchRun: vi.fn(), watchGeneration: () => 0 }));
vi.mock("../../../api/roleSuggestion", async (orig) => ({
  ...(await orig<typeof import("../../../api/roleSuggestion")>()),
  roleSuggestionSwitch: () => Promise.resolve({ enabled: true, review_roles: ["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"] }),
}));

import { startNewReview } from "./newReview";

const file = new File(["%PDF-1.7"], "Agreement.pdf", { type: "application/pdf" });

beforeEach(() => {
  uploadOne.mockReset().mockResolvedValue({ phase: "done", documentId: "doc-1", duplicateOf: null, awaitingGrant: false });
  setRoleBulk.mockReset();
  ofDocument.mockReset().mockResolvedValue({ ok: true, data: { document_id: "doc-1", document_role: null,
    document_kind_evidence: { role_suggestion: { role: "CONTRACTOR_SUBMITTAL", basis: "page", page: "review", kind: "contract", kind_says: "CONTRACT_DOCUMENT" } } } });
});

describe("new review with the suggested role on", () => {
  it("uploads with the page, marks nothing, and offers the suggestion to confirm or change", async () => {
    const phases: string[] = [];
    const got = await startNewReview(file, (p) => phases.push(p.kind), { sleep: async () => {}, pollMs: 1, capMs: 1000 });
    expect(uploadOne.mock.calls[0][3]).toBe("review");
    expect(setRoleBulk).not.toHaveBeenCalled();
    expect(got.ok).toBe(false);
    if (!got.ok && "offerMark" in got) {
      expect(got.offerMark.suggestion?.role).toBe("CONTRACTOR_SUBMITTAL");
      expect(got.message).toContain("Suggested, confirm or change.");
      expect(got.message).toContain("its contents read as a contract document");
    } else {
      throw new Error("no offer");
    }
    expect(phases).not.toContain("marking");
  });
});
