/**
 * OWNER: builder D. Watched reviews and the finished notice's store
 * (PLACEHOLDER - planner team). A module-level store (plus sessionStorage
 * in try/catch so a refresh keeps the watch list); `useFinishedReviews`
 * polls `reviewsApi.reviewRun(id)` for watched runs while any is running.
 */
import type { FinishedReview } from "./contract";

/** PLACEHOLDER. */
export function watchRun(_runId: string, _filename: string | null = null): void {}

/** PLACEHOLDER. */
export function useFinishedReviews(): { finished: FinishedReview[]; dismiss: (runId: string) => void } {
  return { finished: [], dismiss: () => {} };
}
