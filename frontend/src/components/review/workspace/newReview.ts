/**
 * OWNER: builder D. New review in three clicks, and "Review again".
 *
 * `startNewReview(file, onPhase)` runs, in this order, existing calls only:
 *   0. who may   - only an administrator may mark a document as one from a
 *      contractor, so a non-administrator is told so BEFORE anything is
 *      uploaded (the `isAdmin` option, else `auth.me()`).
 *   1. uploading - Uploader's XHR path (`uploadOne`), with its percent;
 *      disciplines are the uploader's own default when sign-in is on
 *      (`api.uploadDisciplines`), none when it is off.
 *   2. marking   - `markAsContractorSubmittal` (the one TODO ADAPTER). A file
 *      that is ALREADY in the library is never re-marked: its current role is
 *      read, and only one already marked as a contractor submittal goes on.
 *      Any other role (a standard, a contract document...) or a role that
 *      cannot be read stops here with nothing changed.
 *   3. waiting   - `api.document(id)` until the document is read in, with a
 *      time cap so the screen never waits forever.
 *   4. starting  - `reviewsApi.startReviewRun(documentId)`.
 *   then `watchRun(runId, filename)` so the finished notice can say so.
 *
 * Any step that fails stops there with plain words and NO review is started.
 * A refusal from the review API is put in plain words by `startRefusal`
 * (already running, administrators only, document not readable); any other
 * refusal is shown exactly as the API worded it.
 */
import { api, auth, classification, reviews as reviewsApi } from "../../../api/client";
import { hasAdminCapability } from "../../Shell";
import { uploadOne } from "../../Uploader";
import { ROLE_OPTIONS } from "../../classification/MetadataEditor";
import type { ApiError, ReviewRunSummary } from "../../../types/api";
import { groupRunsByDocument } from "../reviewFormat";
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

/** Said BEFORE anything is uploaded, so a non-administrator never leaves an
 *  unmarked file behind. */
export const NOT_ADMIN_BEFORE_UPLOAD_MESSAGE =
  "Only an administrator can start a new review from a file, because the file must be marked as a document from a contractor. "
  + "Ask an administrator to upload it. Nothing was uploaded and no review was started.";

export const ADMIN_UNKNOWN_MESSAGE =
  "Could not check whether you may start a new review, so nothing was uploaded. Try again in a moment.";

/** The role the submittal must already hold for a re-dropped file to go on. */
const SUBMITTAL_ROLE = "CONTRACTOR_SUBMITTAL";

/** A role in plain words, from the one list that names roles
 *  (`MetadataEditor.ROLE_OPTIONS`): "a company standard". */
function roleInPlainWords(role: string | null | undefined): string {
  if (!role) return "a document with no role set";
  const label = ROLE_OPTIONS.find((o) => o.value === role)?.label;
  if (!label) return `a document with the role "${role}"`;
  // "Company standard" -> "company standard", but "CRS template" stays.
  const lowered = /^[A-Z][a-z]/.test(label) ? label[0].toLowerCase() + label.slice(1) : label;
  return `${/^[aeiou]/i.test(lowered) ? "an" : "a"} ${lowered}`;
}

export function alreadyInLibraryMessage(role: string | null | undefined): string {
  return `This file is already in the library as ${roleInPlainWords(role)}. It was not changed and no review was started. `
    + "Open it on the Documents page if you want to review it.";
}

/** The bulk role write names a document it did not touch as `not_found`,
 *  which means "unknown OR you may not read it" (the same answer on purpose).
 *  Only an administrator gets that far, so it is never about being an admin. */
export const MARK_UNREADABLE_MESSAGE =
  "Your file was uploaded, but it could not be marked as a document from a contractor, because it could not be found or you may not read it. "
  + "No review was started.";

export const UPLOADED_UNREADABLE_MESSAGE =
  "The uploaded document could not be found or you may not read it, so no review was started.";

/* Refusals of `startReviewRun`, in plain words. */
export const REVIEW_ADMIN_ONLY_MESSAGE = "Only an administrator can start a review.";
export const REVIEW_DOCUMENT_UNREADABLE_MESSAGE =
  "This document could not be found or you may not read it, so no review was started.";
export const REVIEW_REFUSED_UNKNOWN_MESSAGE =
  "The review could not be started. Only an administrator can start one, and only of a document they may read.";
export const ALREADY_RUNNING_MESSAGE = "A review of this document is already running.";

export const ROLE_UNREADABLE_MESSAGE =
  "This file is already in the library, but what it is marked as could not be checked. It was not changed and no review was started. "
  + "Open it on the Documents page if you want to review it.";

/** Optional knobs: whether the caller is an administrator (when the screen
 *  already knows; otherwise it is asked), and for tests a fake clock and sleep. */
export interface NewReviewOptions {
  isAdmin?: boolean;
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

/** Only an administrator may mark a document (the role write is admin
 *  only), so this is asked before the upload. Unknown means no. */
async function mayStartNewReview(options: NewReviewOptions): Promise<{ ok: true } | { ok: false; message: string }> {
  if (options.isAdmin === true) return { ok: true };
  if (options.isAdmin === false) return { ok: false, message: NOT_ADMIN_BEFORE_UPLOAD_MESSAGE };
  const r = await auth.me();
  if (!r.ok) return { ok: false, message: ADMIN_UNKNOWN_MESSAGE };
  return hasAdminCapability(r.data) ? { ok: true } : { ok: false, message: NOT_ADMIN_BEFORE_UPLOAD_MESSAGE };
}

/** A file already in the library is reviewed only if it is ALREADY a
 *  contractor submittal. Nothing is ever re-marked: dropping a standard here
 *  must not quietly take it out of the standards set. */
async function checkDuplicateRole(documentId: string): Promise<{ ok: true } | { ok: false; message: string }> {
  const r = await api.document(documentId);
  if (!r.ok) {
    if (!r.disconnected && r.error.code === "not_found") return { ok: false, message: UPLOADED_UNREADABLE_MESSAGE };
    return { ok: false, message: ROLE_UNREADABLE_MESSAGE };
  }
  const role = r.data.document_role;
  if (role === SUBMITTAL_ROLE) return { ok: true };
  return { ok: false, message: alreadyInLibraryMessage(role) };
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
      return { ok: false, message: UPLOADED_UNREADABLE_MESSAGE };
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

  const may = await mayStartNewReview(options);
  if (!may.ok) return fail(may.message);

  onPhase({ kind: "uploading", percent: 0 });
  const who = await uploadDisciplines();
  if (!who.ok) return fail(who.message);
  const uploaded = await uploadOne(file, who.disciplines, (percent) => onPhase({ kind: "uploading", percent }));
  if (uploaded.phase === "error") return fail(uploaded.message);
  if (uploaded.phase !== "done") return fail("The upload did not finish.");
  if (uploaded.awaitingGrant) {
    return fail("Your file was uploaded, but an administrator must give access to it before it can be reviewed. No review was started.");
  }
  const documentId = uploaded.duplicateOf || uploaded.documentId || "";
  if (!documentId) return fail("The upload finished but the document could not be identified, so no review was started.");

  if (uploaded.duplicateOf) {
    // Already in the library: read its role, never write one (so no
    // "Marking..." line either).
    const held = await checkDuplicateRole(documentId);
    if (!held.ok) return fail(held.message);
  } else {
    onPhase({ kind: "marking" });
    const marked = await markAsContractorSubmittal(documentId);
    if (!marked.ok) return fail(marked.message);
  }

  onPhase({ kind: "waiting" });
  const readIn = await waitUntilReadIn(documentId, options);
  if (!readIn.ok) return fail(readIn.message);

  onPhase({ kind: "starting" });
  const started = await reviewsApi.startReviewRun(documentId);
  if (!started.ok) return fail((await startRefusal(started)).message);
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
 * `failed` (unknown or not readable, never "not an admin": the admin gate
 * already let the caller in), so `ok` alone is not success. Only ever called for a NEW
 * upload, never for a file that was already in the library.
 */
export async function markAsContractorSubmittal(documentId: string): Promise<{ ok: true } | { ok: false; message: string }> {
  const r = await classification.setRoleBulk({ document_ids: [documentId], document_role: "CONTRACTOR_SUBMITTAL" });
  if (!r.ok) {
    if (r.disconnected) return { ok: false, message: r.error.message };
    if (r.error.code === "not_found") return { ok: false, message: NOT_ADMIN_MESSAGE };
    return { ok: false, message: `Your file was uploaded, but it could not be marked as a document from a contractor: ${r.error.message}` };
  }
  // 207: the write went through the admin gate, so the caller IS an
  // administrator; the document named in `failed` is unknown or unreadable.
  const failed = Array.isArray(r.data.failed) ? r.data.failed : [];
  if (failed.length > 0) {
    return { ok: false, message: MARK_UNREADABLE_MESSAGE };
  }
  return { ok: true };
}

/** A refused `startReviewRun`, in plain words.
 *
 * - Already running (409, "... already queued or running (<run id>)"): said
 *   plainly, with the running review's id when the API named it, so the
 *   screen can offer to open it. The raw id is never shown.
 * - 404 `not_found`: the route is administrators only AND answers 404 for a
 *   document the caller may not read, with the same words for both. Who the
 *   caller is (`auth.me`) tells the two apart; when that cannot be read,
 *   both reasons are said.
 * - Anything else: the API's own words.
 */
export async function startRefusal(
  r: { disconnected: boolean; error: ApiError },
): Promise<{ message: string; runningRunId: string | null }> {
  if (r.disconnected) return { message: r.error.message, runningRunId: null };
  const words = r.error.message ?? "";
  if (/already (?:queued or )?running/i.test(words)) {
    const id = /already (?:queued or )?running \(([^)\s]+)\)/i.exec(words)?.[1] ?? null;
    return { message: ALREADY_RUNNING_MESSAGE, runningRunId: id };
  }
  if (r.error.code === "not_found") {
    const who = await auth.me();
    if (!who.ok) return { message: REVIEW_REFUSED_UNKNOWN_MESSAGE, runningRunId: null };
    return {
      message: hasAdminCapability(who.data) ? REVIEW_DOCUMENT_UNREADABLE_MESSAGE : REVIEW_ADMIN_ONLY_MESSAGE,
      runningRunId: null,
    };
  }
  return { message: words, runningRunId: null };
}

/** "Review again"'s answer: as the contract's, plus, when a review of this
 *  document is already running, that run's id (when the API named it). */
export type ReviewAgainResult = ReviewAgainOutcome | { ok: false; message: string; runningRunId: string | null };

/** "Review again": `reviewsApi.startReviewRun(documentId)` then `watchRun`.
 *  A refusal comes back in plain words (`startRefusal`). */
export async function reviewAgain(documentId: string, filename?: string | null): Promise<ReviewAgainResult> {
  const r = await reviewsApi.startReviewRun(documentId);
  if (!r.ok) {
    const refusal = await startRefusal(r);
    return { ok: false, message: refusal.message, runningRunId: refusal.runningRunId };
  }
  const runId = r.data.review_run_id;
  watchRun(runId, filename ?? r.data.submittal_filename ?? null);
  return { ok: true, runId };
}

/** What a new review would be started on top of: the document's newest
 *  review, if it is signed (`crs_issued_at`) or carries the engineer's final
 *  code. A new review is a new row, so that review stays as it is, but the
 *  reader is asked first. `unknown` when the runs could not be read. */
export type PriorDecision =
  | { kind: "none" }
  | { kind: "signed"; finalCode: string | null }
  | { kind: "final_code"; finalCode: string }
  | { kind: "unknown" };

export function priorDecisionOf(documentId: string, runs: ReviewRunSummary[]): PriorDecision {
  const latest = groupRunsByDocument(runs.filter((run) => run.submittal_document_id === documentId))[0]?.latest;
  if (!latest) return { kind: "none" };
  const finalCode = latest.engineer_final_code || null;
  if (latest.crs_issued_at) return { kind: "signed", finalCode };
  if (finalCode) return { kind: "final_code", finalCode };
  return { kind: "none" };
}

/** Reads the document's runs (`reviewsApi.reviewRuns(documentId)`) for
 *  `priorDecisionOf`. Never throws; a failure is `unknown`. */
export async function loadPriorDecision(documentId: string): Promise<PriorDecision> {
  try {
    const r = await reviewsApi.reviewRuns(documentId);
    if (!r.ok) return { kind: "unknown" };
    return priorDecisionOf(documentId, r.data.runs);
  } catch {
    return { kind: "unknown" };
  }
}
