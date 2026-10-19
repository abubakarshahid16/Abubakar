/**
 * OWNER: builder E. Past reviews per document (PLACEHOLDER - planner team).
 */
import type { PastReview } from "./contract";
import type { ReviewRunSummary } from "../../../types/api";

/** PLACEHOLDER. Pure: that document's runs, newest first, as PastReview rows. */
export function pastReviewsOf(_documentId: string, _runs: ReviewRunSummary[]): PastReview[] {
  return [];
}

/**
 * TODO ADAPTER (the one place to swap in a future endpoint): today
 * `reviewsApi.reviewRuns(documentId)` (all runs, filtered by document on the
 * server) mapped with `pastReviewsOf`. PLACEHOLDER.
 */
export async function loadPastReviews(_documentId: string): Promise<{ ok: true; reviews: PastReview[] } | { ok: false; message: string }> {
  return { ok: true, reviews: [] };
}

/**
 * TODO ADAPTER: the runs list carries no comment count. Today one
 * `reviewsApi.reviewRunSummary(runId)` per run, read only when the list is
 * opened (counts.comment + counts.needs_you); null when it fails.
 * PLACEHOLDER.
 */
export async function loadCommentCount(_runId: string): Promise<number | null> {
  return null;
}
