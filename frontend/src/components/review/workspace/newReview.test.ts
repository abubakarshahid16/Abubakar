/**
 * Builder D: a new review runs upload -> mark as contractor document ->
 * wait until read in -> start, in that order, and stops (no review) at the
 * first refusal. "Review again" starts and watches, or shows the API's words.
 *
 * MUTATION PROOF (checked by hand once): drop the `failed` check in
 * markAsContractorSubmittal and "a partial bulk write" fails; move
 * `startReviewRun` above the wait and the order test fails.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NewReviewPhase } from "./contract";

const calls: string[] = [];
const uploadDisciplines = vi.fn();
const document = vi.fn();
const setRoleBulk = vi.fn();
const startReviewRun = vi.fn();
const uploadOne = vi.fn();
const watchRun = vi.fn();

vi.mock("../../../api/client", () => ({
  api: {
    uploadDisciplines: (...a: unknown[]) => { calls.push("disciplines"); return uploadDisciplines(...a); },
    document: (...a: unknown[]) => { calls.push("document"); return document(...a); },
  },
  classification: {
    setRoleBulk: (...a: unknown[]) => { calls.push("mark"); return setRoleBulk(...a); },
  },
  reviews: {
    startReviewRun: (...a: unknown[]) => { calls.push("start"); return startReviewRun(...a); },
  },
}));
vi.mock("../../Uploader", () => ({
  uploadOne: (...a: unknown[]) => { calls.push("upload"); return uploadOne(...a); },
}));
vi.mock("./reviewWatch", () => ({
  watchRun: (...a: unknown[]) => { calls.push("watch"); return watchRun(...a); },
}));

import { NOT_ADMIN_MESSAGE, markAsContractorSubmittal, reviewAgain, startNewReview } from "./newReview";

const file = new File(["%PDF-1.7"], "Pump datasheet rev B.pdf", { type: "application/pdf" });
const noWait = { sleep: async () => {}, pollMs: 1, capMs: 60_000 };

beforeEach(() => {
  calls.length = 0;
  for (const m of [uploadDisciplines, document, setRoleBulk, startReviewRun, uploadOne, watchRun]) m.mockReset();
  uploadDisciplines.mockResolvedValue({ ok: true, data: { required: true, choices: ["Mechanical", "Piping"], default: ["Mechanical"] } });
  uploadOne.mockImplementation(async (_f: File, _d: string[], onProgress: (p: number) => void) => {
    onProgress(50);
    onProgress(100);
    return { phase: "done", documentId: "doc-1", duplicateOf: null, awaitingGrant: false };
  });
  setRoleBulk.mockResolvedValue({ ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: ["doc-1"], unchanged: [], failed: [] } });
  document
    .mockResolvedValueOnce({ ok: true, data: { id: "doc-1", status: "extracting" } })
    .mockResolvedValue({ ok: true, data: { id: "doc-1", status: "ready" } });
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", submittal_filename: "Pump datasheet rev B.pdf" } });
});

afterEach(() => { vi.restoreAllMocks(); });

describe("startNewReview", () => {
  it("uploads, marks, waits until read in, starts, then watches - in that order", async () => {
    const phases: NewReviewPhase[] = [];
    const outcome = await startNewReview(file, (p) => phases.push(p), noWait);

    expect(outcome).toEqual({ ok: true, documentId: "doc-1", runId: "run-1" });
    expect(calls).toEqual(["disciplines", "upload", "mark", "document", "document", "start", "watch"]);
    expect(phases.map((p) => p.kind)).toEqual([
      "uploading", "uploading", "uploading", "marking", "waiting", "starting", "started",
    ]);
    expect(phases[2]).toEqual({ kind: "uploading", percent: 100 });
    expect(uploadOne.mock.calls[0][0]).toBe(file);
    expect(uploadOne.mock.calls[0][1]).toEqual(["Mechanical"]);
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-1"], document_role: "CONTRACTOR_SUBMITTAL" });
    expect(startReviewRun).toHaveBeenCalledWith("doc-1");
    expect(watchRun).toHaveBeenCalledWith("run-1", "Pump datasheet rev B.pdf");
  });

  it("asks for no discipline when sign-in is off", async () => {
    uploadDisciplines.mockResolvedValue({ ok: true, data: { required: false, choices: [], default: [] } });
    await startNewReview(file, () => {}, noWait);
    expect(uploadOne.mock.calls[0][1]).toEqual([]);
  });

  it("a non-admin (404 from the role write) gets plain words and no review starts", async () => {
    setRoleBulk.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "That is not something the backend knows about." } });
    const phases: NewReviewPhase[] = [];
    const outcome = await startNewReview(file, (p) => phases.push(p), noWait);

    expect(outcome).toEqual({ ok: false, message: NOT_ADMIN_MESSAGE });
    expect(NOT_ADMIN_MESSAGE).toMatch(/Ask an administrator/);
    expect(phases.at(-1)).toEqual({ kind: "error", message: NOT_ADMIN_MESSAGE });
    expect(startReviewRun).not.toHaveBeenCalled();
    expect(document).not.toHaveBeenCalled();
    expect(watchRun).not.toHaveBeenCalled();
  });

  it("a partial bulk write (the document named in failed) starts no review", async () => {
    setRoleBulk.mockResolvedValue({ ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: [], unchanged: [], failed: [{ document_id: "doc-1", reason: "not_found" }] } });
    const outcome = await startNewReview(file, () => {}, noWait);
    expect(outcome).toEqual({ ok: false, message: NOT_ADMIN_MESSAGE });
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("stops at the time cap while the document is still being read in", async () => {
    document.mockReset();
    document.mockResolvedValue({ ok: true, data: { id: "doc-1", status: "extracting" } });
    let clock = 0;
    const outcome = await startNewReview(file, () => {}, {
      sleep: async (ms) => { clock += ms; }, now: () => clock, pollMs: 1000, capMs: 5000,
    });
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.message).toMatch(/taking longer than usual/);
    expect(document.mock.calls.length).toBe(6);
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("a document that cannot be read starts no review", async () => {
    document.mockReset();
    document.mockResolvedValue({ ok: true, data: { id: "doc-1", status: "no_searchable_content" } });
    const outcome = await startNewReview(file, () => {}, noWait);
    expect(outcome.ok).toBe(false);
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("an upload error stops before marking", async () => {
    uploadOne.mockResolvedValue({ phase: "error", code: "too_large", message: "That file is larger than the backend accepts." });
    const outcome = await startNewReview(file, () => {}, noWait);
    expect(outcome).toEqual({ ok: false, message: "That file is larger than the backend accepts." });
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("an upload waiting for an administrator's grant starts no review", async () => {
    uploadOne.mockResolvedValue({ phase: "done", documentId: "doc-1", duplicateOf: null, awaitingGrant: true });
    const outcome = await startNewReview(file, () => {}, noWait);
    expect(outcome.ok).toBe(false);
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("a refusal to start is shown exactly as the API worded it", async () => {
    const words = "a review of this submittal is already queued or running (run-0)";
    startReviewRun.mockResolvedValue({ ok: false, disconnected: false, error: { code: "invalid_parameter", message: words } });
    const outcome = await startNewReview(file, () => {}, noWait);
    expect(outcome).toEqual({ ok: false, message: words });
    expect(watchRun).not.toHaveBeenCalled();
  });
});

describe("markAsContractorSubmittal", () => {
  it("is ok when the role was written or already held", async () => {
    setRoleBulk.mockResolvedValue({ ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: [], unchanged: ["doc-1"], failed: [] } });
    expect(await markAsContractorSubmittal("doc-1")).toEqual({ ok: true });
  });
});

describe("reviewAgain", () => {
  it("starts a review of the same document and watches it", async () => {
    startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-2", submittal_filename: "Pump datasheet rev B.pdf" } });
    expect(await reviewAgain("doc-1", "Pump datasheet rev B.pdf")).toEqual({ ok: true, runId: "run-2" });
    expect(calls).toEqual(["start", "watch"]);
    expect(watchRun).toHaveBeenCalledWith("run-2", "Pump datasheet rev B.pdf");
  });

  it("returns the API's refusal word for word", async () => {
    const words = "a review of this submittal is already queued or running (run-1)";
    startReviewRun.mockResolvedValue({ ok: false, disconnected: false, error: { code: "invalid_parameter", message: words } });
    expect(await reviewAgain("doc-1")).toEqual({ ok: false, message: words });
    expect(watchRun).not.toHaveBeenCalled();
  });
});
