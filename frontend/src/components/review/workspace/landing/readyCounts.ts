/**
 * The counts behind the landing page's status chips and the past reviews,
 * many runs in one request (moved here from SubmittalsLandingView, which
 * re-exports it unchanged so the old screens and tests keep their import).
 */
import { reviews as reviewsApi } from "../../../../api/client";
import type { ReadyCounts } from "../../inbox/inboxState";

/** Order 117 item 5: the most run ids one counts request may carry; the
 *  server answers 422 above this. */
export const RUN_COUNTS_MAX_IDS = 200;

/** #1114 / order 117 item 5: the Ready labels' counts, for many runs at once
 *  - one counts request per RUN_COUNTS_MAX_IDS ids, not one full summary per
 *  run. A run absent from the answer, or in a request that failed, maps to
 *  null and its row says "Ready" alone; a failure never shows 0.
 *
 *  FINDINGS, NOT COMMENT ROWS: the server counts findings per tier; the
 *  comment sheet groups findings into rows. Whoever shows these says so. */
export async function loadReadyCounts(runIds: string[]): Promise<Record<string, ReadyCounts | null>> {
  const out: Record<string, ReadyCounts | null> = {};
  const chunks: string[][] = [];
  for (let i = 0; i < runIds.length; i += RUN_COUNTS_MAX_IDS) chunks.push(runIds.slice(i, i + RUN_COUNTS_MAX_IDS));
  await Promise.all(chunks.map(async (chunk) => {
    let got: Record<string, { comment: number; needs_you: number }> | null = null;
    try {
      const res = await reviewsApi.reviewRunCounts(chunk);
      if (res.ok) got = res.data.counts;
    } catch {
      got = null;
    }
    for (const id of chunk) {
      const c = got && Object.prototype.hasOwnProperty.call(got, id) ? got[id] : undefined;
      out[id] = c ? { findings: c.comment + c.needs_you, needs_you: c.needs_you } : null;
    }
  }));
  return out;
}
