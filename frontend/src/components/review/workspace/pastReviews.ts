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

/** What a past review came to, in plain words. The engineer's final code
 *  is shown as it is; when there is none, the AI's recommended code is shown
 *  as "Proposed: <code>" so it never reads like the engineer's decision;
 *  with neither, the run's status. Review codes are the configured labels
 *  ("Approved with Comments") that every existing screen already prints as
 *  they are; only the status (a database value such as "completed") is
 *  translated. */
function resultWords(run: ReviewRunSummary): string {
  if (run.engineer_final_code) return run.engineer_final_code;
  if (run.recommended_code) return `Proposed: ${run.recommended_code}`;
  return runStatusLabel(run.status);
}

/** Pure: that document's runs, newest first (the same order as
 *  `groupRunsByDocument`), as PastReview rows. `commentCount` starts unknown
 *  (null) - it is read lazily when the list is opened. */
export function pastReviewsOf(documentId: string, runs: ReviewRunSummary[]): PastReview[] {
  const group = groupRunsByDocument(runs.filter((run) => run.submittal_document_id === documentId))[0];
  if (!group) return [];
  return [group.latest, ...group.earlier].map((run) => ({
    runId: run.review_run_id,
    createdAt: run.created_at ?? null,
    result: resultWords(run),
    commentCount: null,
    signed: Boolean(run.crs_issued_at),
    status: run.status,
  }));
}

/**
 * TODO ADAPTER (the one place to swap in a future endpoint): today
 * `reviewsApi.reviewRuns(documentId)` (all runs, filtered by document on the
 * server) mapped with `pastReviewsOf`.
 */
export async function loadPastReviews(documentId: string): Promise<{ ok: true; reviews: PastReview[] } | { ok: false; message: string }> {
  const res = await reviewsApi.reviewRuns(documentId);
  if (!res.ok) return { ok: false, message: res.error.message };
  return { ok: true, reviews: pastReviewsOf(documentId, res.data.runs) };
}

/**
 * TODO ADAPTER: the runs list carries no comment count. Today one
 * `reviewsApi.reviewRunSummary(runId)` per run, read only when the list is
 * opened (counts.comment + counts.needs_you); null when it fails - an
 * unknown count is never shown as 0.
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
