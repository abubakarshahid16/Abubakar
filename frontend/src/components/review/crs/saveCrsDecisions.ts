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
 * of its calls succeeded; a failed row stays unsaved and says why.
 */
import { reviews as reviewsApi } from "../../../api/client";
import type { CrsRow } from "./crsRows";
import { type Decision, REMOVE_REASON_CODES } from "./useCrsDecisions";

export interface SaveOutcome {
  /** Row keys the record now holds as decided on screen. */
  saved: string[];
  /** One plain line per row that did not save. */
  failed: { key: string; message: string }[];
}

async function saveRow(runId: string, row: CrsRow, decision: Decision): Promise<string | null> {
  if (decision.kind === "edit" && !decision.requiredAction.trim()) return "the required action is empty";
  for (const finding of row.findings) {
    const res = decision.kind === "keep"
      ? await reviewsApi.confirm(finding.id)
      : decision.kind === "edit"
        ? await reviewsApi.update(finding.id, { engineer_comment: decision.requiredAction.trim() })
        : await reviewsApi.decideCrsFinding(runId, finding.id, "reject", "", REMOVE_REASON_CODES[decision.reason]);
    if (!res.ok) return res.error.message;
  }
  return null;
}

export async function saveCrsDecisions(
  runId: string, rows: CrsRow[], decisions: Record<string, Decision>, keys: string[],
): Promise<SaveOutcome> {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const outcome: SaveOutcome = { saved: [], failed: [] };
  for (const key of keys) {
    const row = byKey.get(key);
    const decision = decisions[key];
    if (!row || !decision) continue;
    const message = await saveRow(runId, row, decision);
    if (message) outcome.failed.push({ key, message: `Comment ${row.commentNo ?? "-"}: ${message}` });
    else outcome.saved.push(key);
  }
  return outcome;
}
