/**
 * OWNER: builder D. New review in three clicks (PLACEHOLDER - planner team).
 * Sequence, existing calls only: upload (Uploader's XHR path, exported as
 * `uploadOne`) -> role CONTRACTOR_SUBMITTAL (`markAsContractorSubmittal`) ->
 * wait until the document is read in (`api.document(id)`) ->
 * `reviewsApi.startReviewRun(documentId)` -> `watchRun(runId)`.
 */
import type { NewReviewOutcome, NewReviewPhase, ReviewAgainOutcome } from "./contract";

/** PLACEHOLDER. */
export async function startNewReview(_file: File, _onPhase: (phase: NewReviewPhase) => void): Promise<NewReviewOutcome> {
  return { ok: false, message: "Not built yet." };
}

/**
 * TODO ADAPTER (the one place to swap in a future endpoint): there is no
 * "upload as contractor submittal" endpoint. Today this uses
 * `classification.setRoleBulk`, which is ADMIN ONLY (a non-admin gets 404).
 * PLACEHOLDER.
 */
export async function markAsContractorSubmittal(_documentId: string): Promise<{ ok: true } | { ok: false; message: string }> {
  return { ok: false, message: "Not built yet." };
}

/** PLACEHOLDER: `reviewsApi.startReviewRun(documentId)` then `watchRun`. */
export async function reviewAgain(_documentId: string, _filename?: string | null): Promise<ReviewAgainOutcome> {
  return { ok: false, message: "Not built yet." };
}
