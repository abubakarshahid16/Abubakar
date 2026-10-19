/**
 * OWNER: builder D. New review in three clicks, and "Review again".
 *
 * `startNewReview(file, onPhase)` runs, in this order, existing calls only:
 *   1. uploading - Uploader's XHR path (`uploadOne`), with its percent;
 *      disciplines are the uploader's own default when sign-in is on
 *      (`api.uploadDisciplines`), none when it is off.
 *   2. marking   - `markAsContractorSubmittal` (the one TODO ADAPTER).
 *   3. waiting   - `api.document(id)` until the document is read in, with a
 *      time cap so the screen never waits forever.
 *   4. starting  - `reviewsApi.startReviewRun(documentId)`.
 *   then `watchRun(runId, filename)` so the finished notice can say so.
 *
 * Any step that fails stops there with plain words and NO review is started.
 * A refusal from the review API is shown exactly as the API worded it.
 */
import { api, classification, reviews as reviewsApi } from "../../../api/client";
import { uploadOne } from "../../Uploader";
import type { NewReviewOutcome, NewReviewPhase, ReviewAgainOutcome } from "./contract";
import { watchRun } from "./reviewWatch";

/** How often the document is re-read while it is being read in. */
export const READ_IN_POLL_MS = 3_000;
/** The longest the screen waits for the document to be read in. */
export const READ_IN_CAP_MS = 10 * 60_000;

/** Document statuses that mean the text is in and a review can read it
 *  (the backend's own rule: `status IN ('ready','partially_searchable')`). */
const READ_IN = new Set(["ready", "partially_searchable"]);
/** Finished statuses that mean it will never be read in. */
const CANNOT_READ: Record<string, string> = {
  failed: "This document could not be read, so it cannot be reviewed.",
  no_searchable_content: "No text could be found in this document, so it cannot be reviewed.",
  stored_not_indexed: "This kind of file is kept but not read (for example a spreadsheet), so it cannot be reviewed.",
};

export const NOT_ADMIN_MESSAGE =
  "Your file was uploaded, but only an administrator can mark it as a document from a contractor. "
  + "Ask an administrator to mark it, then start the review from the list. No review was started.";

/** Optional knobs for tests: a fake clock and sleep. */
export interface NewReviewOptions {
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  pollMs?: number;
  capMs?: number;
}

const realSleep = (ms: number) => new Promise<void>((resolve) => { window.setTimeout(resolve, ms); });

async function uploadDisciplines(): Promise<{ ok: true; disciplines: string[] } | { ok: false; message: string }> {
  const r = await api.uploadDisciplines();
  if (!r.ok) return { ok: false, message: "Could not find out who the upload may be shared with, so nothing was uploaded." };
  if (!r.data.required) return { ok: true, disciplines: [] };
  if (r.data.default.length === 0) {
    return {
      ok: false,
      message: "You are not in any discipline, so an upload would be visible to nobody. Ask an administrator to add you to one.",
    };
  }
  return { ok: true, disciplines: r.data.default };
}

/** Waits until the document is read in, or says why it will not be. */
async function waitUntilReadIn(
  documentId: string, options: NewReviewOptions,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const sleep = options.sleep ?? realSleep;
  const now = options.now ?? Date.now;
  const pollMs = options.pollMs ?? READ_IN_POLL_MS;
  const capMs = options.capMs ?? READ_IN_CAP_MS;
  const started = now();
  for (;;) {
    const r = await api.document(documentId);
    if (r.ok) {
      const status = r.data.status;
      if (READ_IN.has(status)) return { ok: true };
      const reason = CANNOT_READ[status];
      if (reason) return { ok: false, message: reason };
    } else if (!r.disconnected && r.error.code === "not_found") {
      return { ok: false, message: "The uploaded document can no longer be found, so no review was started." };
    }
    // Still being read in, or a passing failure: try again until the cap.
    if (now() - started >= capMs) {
      return {
        ok: false,
        message: "The document is taking longer than usual to be read in, so no review was started yet. "
          + "Start it from the list once the document is ready.",
      };
    }
    await sleep(pollMs);
  }
}

export async function startNewReview(
  file: File,
  onPhase: (phase: NewReviewPhase) => void,
  options: NewReviewOptions = {},
): Promise<NewReviewOutcome> {
  const fail = (message: string): NewReviewOutcome => {
    onPhase({ kind: "error", message });
    return { ok: false, message };
  };

  onPhase({ kind: "uploading", percent: 0 });
  const who = await uploadDisciplines();
  if (!who.ok) return fail(who.message);
  const uploaded = await uploadOne(file, who.disciplines, (percent) => onPhase({ kind: "uploading", percent }));
  if (uploaded.phase === "error") return fail(uploaded.message);
  if (uploaded.phase !== "done") return fail("The upload did not finish.");
  if (uploaded.awaitingGrant) {
    return fail("Your file was uploaded, but an administrator must give access to it before it can be reviewed. No review was started.");
  }
  const documentId = uploaded.documentId || uploaded.duplicateOf || "";
  if (!documentId) return fail("The upload finished but the document could not be identified, so no review was started.");

  onPhase({ kind: "marking" });
  const marked = await markAsContractorSubmittal(documentId);
  if (!marked.ok) return fail(marked.message);

  onPhase({ kind: "waiting" });
  const readIn = await waitUntilReadIn(documentId, options);
  if (!readIn.ok) return fail(readIn.message);

  onPhase({ kind: "starting" });
  const started = await reviewsApi.startReviewRun(documentId);
  // SHOWN AS THE API RETURNED IT: a refusal is a real answer.
  if (!started.ok) return fail(started.error.message);
  const runId = started.data.review_run_id;
  watchRun(runId, started.data.submittal_filename ?? file.name);
  onPhase({ kind: "started", runId });
  return { ok: true, documentId, runId };
}

/**
 * TODO ADAPTER (the one place to swap in a future endpoint): there is no
 * "upload as contractor submittal" endpoint. Today this uses
 * `classification.setRoleBulk`, which is ADMIN ONLY: a non-admin gets a 404
 * that says nothing about the document, so a 404 here means "you may not do
 * this". The bulk write answers 207 with the untouched documents named in
 * `failed`, so `ok` alone is not success.
 */
export async function markAsContractorSubmittal(documentId: string): Promise<{ ok: true } | { ok: false; message: string }> {
  const r = await classification.setRoleBulk({ document_ids: [documentId], document_role: "CONTRACTOR_SUBMITTAL" });
  if (!r.ok) {
    if (r.disconnected) return { ok: false, message: r.error.message };
    if (r.error.code === "not_found") return { ok: false, message: NOT_ADMIN_MESSAGE };
    return { ok: false, message: `Your file was uploaded, but it could not be marked as a document from a contractor: ${r.error.message}` };
  }
  const failed = Array.isArray(r.data.failed) ? r.data.failed : [];
  if (failed.length > 0) {
    return { ok: false, message: NOT_ADMIN_MESSAGE };
  }
  return { ok: true };
}

/** "Review again": `reviewsApi.startReviewRun(documentId)` then `watchRun`.
 *  A refusal (a review already running) is returned as the API worded it. */
export async function reviewAgain(documentId: string, filename?: string | null): Promise<ReviewAgainOutcome> {
  const r = await reviewsApi.startReviewRun(documentId);
  if (!r.ok) return { ok: false, message: r.error.message };
  const runId = r.data.review_run_id;
  watchRun(runId, filename ?? r.data.submittal_filename ?? null);
  return { ok: true, runId };
}
