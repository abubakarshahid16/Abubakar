/**
 * OWNER: builder E. Past reviews per document.
 *
 * `pastReviewsOf` is pure: it turns the runs list the landing page already
 * holds into that document's past reviews, newest first. The two loaders
 * below are the TODO ADAPTERs - the one place a future endpoint swaps in.
 */
import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewRunSummary } from "../../../types/api";
import { groupRunsByDocument, runStatusLabel } from "../reviewFormat";
import type { PastReview } from "./contract";
import type { ReadyCounts } from "../inbox/inboxState";
import { foundLine } from "./landing/landingRows";
import { loadReadyCounts } from "./landing/readyCounts";

/** What a past review came to, in plain words. The engineer's final code
 *  is shown as it is; when there is none, the AI's recommended code is shown
 *  as "Suggested: <code>" (the word the decision card uses for the AI's
 *  code) so it never reads like the engineer's decision;
 *  with neither, the run's status. Review codes are the configured labels
 *  ("Approved with Comments") that every existing screen already prints as
 *  they are; only the status (a database value such as "completed") is
 *  translated. */
function resultWords(run: ReviewRunSummary): string {
  if (run.engineer_final_code) return run.engineer_final_code;
  if (run.recommended_code) return `Suggested: ${run.recommended_code}`;
  // v2.1 L9: a failed review says why, in the words the run stored.
  if (run.status === "failed" && run.failure_reason) return `${runStatusLabel(run.status)}: ${run.failure_reason}`;
  return runStatusLabel(run.status);
}

/** A row of "All reviews of this file": the contract's row, plus whether
 *  the engineer recorded a final code (so an unsigned one can say "Final
 *  code recorded, not signed" rather than only "Not signed"). */
export interface PastReviewRow extends PastReview {
  finalCodeRecorded?: boolean;
}

/** The signed column in plain words. */
export function signedWords(review: PastReviewRow): string {
  if (review.signed) return "Signed";
  if (review.finalCodeRecorded) return "Final code recorded, not signed";
  return "Not signed";
}

/** Pure: that document's runs, newest first (the same order as
 *  `groupRunsByDocument`), as PastReview rows. `commentCount` starts unknown
 *  (null) - it is read lazily when the list is opened. */
export function pastReviewsOf(documentId: string, runs: ReviewRunSummary[]): PastReviewRow[] {
  const group = groupRunsByDocument(runs.filter((run) => run.submittal_document_id === documentId))[0];
  if (!group) return [];
  return [group.latest, ...group.earlier].map((run) => ({
    runId: run.review_run_id,
    createdAt: run.created_at ?? null,
    result: resultWords(run),
    commentCount: null,
    signed: Boolean(run.crs_issued_at),
    finalCodeRecorded: Boolean(run.engineer_final_code),
    status: run.status,
  }));
}

/**
 * TODO ADAPTER (the one place to swap in a future endpoint): today
 * `reviewsApi.reviewRuns(documentId)` (all runs, filtered by document on the
 * server) mapped with `pastReviewsOf`.
 */
export async function loadPastReviews(documentId: string): Promise<{ ok: true; reviews: PastReviewRow[] } | { ok: false; message: string }> {
  const res = await reviewsApi.reviewRuns(documentId);
  if (!res.ok) return { ok: false, message: res.error.message };
  return { ok: true, reviews: pastReviewsOf(documentId, res.data.runs) };
}

/**
 * TODO ADAPTER: the runs list carries no count. Today one
 * `reviewsApi.reviewRunSummary(runId)` per run, read only when the list is
 * opened: counts.comment + counts.needs_you, i.e. FINDINGS the engineer
 * decides on. That is not the comment sheet's row count (the sheet groups
 * findings into rows with `buildCrsRows`, which would need four reads per
 * run), so the list labels it as findings the review found, never
 * "comments" and never what is left to decide.
 * Null when it fails - an unknown count is never shown as 0.
 */
export async function loadCommentCount(runId: string): Promise<number | null> {
  try {
    const res = await reviewsApi.reviewRunSummary(runId);
    if (!res.ok) return null;
    const { comment, needs_you } = res.data.counts;
    if (typeof comment !== "number" || typeof needs_you !== "number") return null;
    return comment + needs_you;
  } catch {
    return null;
  }
}

/**
 * v2.1 W5 - TODO ADAPTER: the counts of several past reviews in ONE request
 * (the batch counts route the landing's chips use), instead of one full
 * summary per review. `findings` = comment + needs-you findings, `needs_you`
 * = those that need the engineer's judgement.
 *
 * HONEST LABEL: the comment sheet's own rule ("N comments, M left to
 * decide") groups findings into rows with `buildCrsRows` and needs the
 * run's findings, decisions and summary - four reads per review that the
 * landing does not have. So the list shows the SERVER'S totals, says they
 * are what the review found (not what is left to decide), and says it
 * counts findings, not comment lines. A review whose count is
 * not known maps to null and shows nothing, never 0.
 */
export async function loadPastReviewCounts(runIds: string[]): Promise<Record<string, ReadyCounts | null>> {
  if (runIds.length === 0) return {};
  try {
    return await loadReadyCounts(runIds);
  } catch {
    return Object.fromEntries(runIds.map((id) => [id, null]));
  }
}

/** "Found by the review: 6 findings, 2 needing your judgement"; nothing
 *  when not known. These are the review's TOTALS, never what is left to
 *  decide (decisions already made are not taken off). */
export function pastCountsLabel(counts: ReadyCounts | null | undefined): string {
  return foundLine(counts);
}

export const PAST_COUNTS_NOTE =
  "Counts are what each review found, not what is left to decide. They count findings; the comment sheet groups findings into fewer comment lines.";
