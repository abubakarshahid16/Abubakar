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
 *  as "Suggested: <code>" (the word the decision card uses for the AI's
 *  code) so it never reads like the engineer's decision;
 *  with neither, the run's status. Review codes are the configured labels
 *  ("Approved with Comments") that every existing screen already prints as
 *  they are; only the status (a database value such as "completed") is
 *  translated. */
function resultWords(run: ReviewRunSummary): string {
  if (run.engineer_final_code) return run.engineer_final_code;
  if (run.recommended_code) return `Suggested: ${run.recommended_code}`;
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

/** The batched counts route takes at most this many ids per request (the
 *  server refuses more with 422); the same limit the inbox uses. */
export const PAST_REVIEW_COUNTS_MAX_IDS = 200;

/**
 * TODO ADAPTER: the runs list carries no count. Today
 * `reviewsApi.reviewRunCounts(ids)` (GET /api/reviews/runs/counts, PR #1160),
 * one request per PAST_REVIEW_COUNTS_MAX_IDS ids, read only when the list is
 * opened: counts.comment + counts.needs_you, i.e. FINDINGS the engineer
 * decides on. That is not the comment sheet's row count (the sheet groups
 * findings into rows with `buildCrsRows`, which would need four reads per
 * run), so the list labels it "findings to decide", never "comments".
 * Each id is null when the server left it out (unknown or not readable),
 * when its request failed or threw, or when a count is not a number - an
 * unknown count is never shown as 0.
 */
export async function loadCommentCounts(runIds: string[]): Promise<Record<string, number | null>> {
  const out: Record<string, number | null> = {};
  const chunks: string[][] = [];
  for (let i = 0; i < runIds.length; i += PAST_REVIEW_COUNTS_MAX_IDS) {
    chunks.push(runIds.slice(i, i + PAST_REVIEW_COUNTS_MAX_IDS));
  }
  await Promise.all(chunks.map(async (chunk) => {
    let got: Record<string, unknown> | null = null;
    try {
      const res = await reviewsApi.reviewRunCounts(chunk);
      if (res.ok) got = res.data.counts as Record<string, unknown>;
    } catch {
      got = null;
    }
    for (const id of chunk) {
      const c = got && Object.prototype.hasOwnProperty.call(got, id) ? got[id] : undefined;
      const { comment, needs_you } = (c && typeof c === "object" ? c : {}) as { comment?: unknown; needs_you?: unknown };
      out[id] = typeof comment === "number" && typeof needs_you === "number" ? comment + needs_you : null;
    }
  }));
  return out;
}

/** One run's count, through the same batched route (kept for the
 *  contract's export). Null when unknown - never 0. */
export async function loadCommentCount(runId: string): Promise<number | null> {
  return (await loadCommentCounts([runId]))[runId] ?? null;
}
