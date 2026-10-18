/**
 * Order 95 piece 6c: "Save decisions" sends what the engineer decided on the
 * CRS-first Sheet to the record, row by row, through existing routes only:
 *
 * - Keep: a confirm PATCH for every finding in the row (#986).
 * - Edit wording: the Required action saved as `engineer_comment` on every
 *   finding in the row; saving it confirms the comment. The Observation is
 *   the review's own and is not sent.
 * - Remove: the CRS decision route, `reject` with the listed `reason_code`
 *   (piece 6a), for every finding in the row.
 *
 * Who and when are the server's. A row counts as saved only when every one
 * of its calls succeeded; a failed row stays unsaved and says why, including
 * how many of its findings did reach the record ("saved 1 of 3"). A finding
 * the record already holds as decided is not sent again, so saving a row
 * twice - or again after it failed half-way - repeats no confirm or reject.
 */
import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewFinding } from "../../../types/api";
import type { CrsRow } from "./crsRows";
import { type Decision, REMOVE_REASON_CODES } from "./useCrsDecisions";

export interface SaveOutcome {
  /** Row keys the record now holds as decided on screen. */
  saved: string[];
  /** One plain line per row that did not save. */
  failed: { key: string; message: string }[];
  /** True when any finding reached the record, even in a row that failed, so
   *  the caller re-reads the run before the engineer saves again. */
  wrote: boolean;
}

/** The record already holds this decision on the finding, so sending it again
 *  would only repeat it. */
function alreadyOnRecord(finding: ReviewFinding, decision: Decision): boolean {
  if (decision.kind === "keep") return Boolean(finding.confirmed_by);
  if (decision.kind === "edit") return finding.engineer_comment === decision.requiredAction.trim();
  return finding.approval_status === "rejected";
}

async function saveRow(
  runId: string, row: CrsRow, decision: Decision,
): Promise<{ done: number; wrote: boolean; error: string | null }> {
  if (decision.kind === "edit" && !decision.requiredAction.trim()) {
    return { done: 0, wrote: false, error: "the required action is empty" };
  }
  let done = 0;
  let wrote = false;
  for (const finding of row.findings) {
    if (!alreadyOnRecord(finding, decision)) {
      const res = decision.kind === "keep"
        ? await reviewsApi.confirm(finding.id)
        : decision.kind === "edit"
          ? await reviewsApi.update(finding.id, { engineer_comment: decision.requiredAction.trim() })
          : await reviewsApi.decideCrsFinding(runId, finding.id, "reject", "", REMOVE_REASON_CODES[decision.reason]);
      if (!res.ok) return { done, wrote, error: res.error.message };
      wrote = true;
    }
    done += 1;
  }
  return { done, wrote, error: null };
}

export async function saveCrsDecisions(
  runId: string, rows: CrsRow[], decisions: Record<string, Decision>, keys: string[],
): Promise<SaveOutcome> {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const outcome: SaveOutcome = { saved: [], failed: [], wrote: false };
  for (const key of keys) {
    const row = byKey.get(key);
    const decision = decisions[key];
    if (!row || !decision) continue;
    const { done, wrote, error } = await saveRow(runId, row, decision);
    outcome.wrote ||= wrote;
    if (error === null) {
      outcome.saved.push(key);
      continue;
    }
    const part = done > 0 ? `saved ${done} of ${row.findings.length}; ` : "";
    outcome.failed.push({ key, message: `Comment ${row.commentNo ?? "-"}: ${part}${error}` });
  }
  return outcome;
}
