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
 *
 * v2.1 round 2: a decision whose comment is no longer on the sheet (the
 * review was read again and the row went away) is reported as failed
 * ("this comment is no longer on the sheet") and listed in `missing`, so
 * the caller can take it off the unsaved list instead of waiting on it
 * forever. Each failure also carries its plain words (`words`, through
 * workspace/plainError) and the server's own words (`detail`); `message`
 * keeps its old wording for the old comment sheet.
 */
import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewFinding } from "../../../types/api";
import { type FailedResult, plainError } from "../workspace/plainError";
import type { CrsRow } from "./crsRows";
import { type Decision, REMOVE_REASON_CODES } from "./useCrsDecisions";

export interface SaveFailure {
  key: string;
  /** The old one-line message ("Comment 3: saved 1 of 3; Not allowed."). */
  message: string;
  /** v2.1: plain words ("Comment 3 was not saved. Try again in a moment."). */
  words?: string;
  /** v2.1: the server's own words (and how far the row got), or null. */
  detail?: string | null;
}

/** The plain words for a decision whose comment is no longer on the sheet. */
export const NO_LONGER_ON_SHEET = "this comment is no longer on the sheet";

export interface SaveOutcome {
  /** Row keys the record now holds as decided on screen. */
  saved: string[];
  /** One plain line per row that did not save. */
  failed: SaveFailure[];
  /** Keys whose comment is no longer on the sheet (also in `failed`):
   *  nothing can ever save them, so the caller drops them. */
  missing: string[];
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
): Promise<{ done: number; wrote: boolean; error: string | null; failure: FailedResult | null }> {
  if (decision.kind === "edit" && !decision.requiredAction.trim()) {
    return { done: 0, wrote: false, error: "the required action is empty", failure: null };
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
      if (!res.ok) return { done, wrote, error: res.error.message, failure: res };
      wrote = true;
    }
    done += 1;
  }
  return { done, wrote, error: null, failure: null };
}

export async function saveCrsDecisions(
  runId: string, rows: CrsRow[], decisions: Record<string, Decision>, keys: string[],
): Promise<SaveOutcome> {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const outcome: SaveOutcome = { saved: [], failed: [], missing: [], wrote: false };
  for (const key of keys) {
    const row = byKey.get(key);
    const decision = decisions[key];
    if (!decision) continue;
    if (!row) {
      // The sheet no longer has this comment: say so, never skip it quietly
      // (a skipped key stays "not saved" for ever and holds Sign).
      outcome.missing.push(key);
      outcome.failed.push({
        key, message: `A decision was not saved: ${NO_LONGER_ON_SHEET}.`,
        words: `A decision was not saved: ${NO_LONGER_ON_SHEET}, so it was taken off your list.`, detail: null,
      });
      continue;
    }
    const { done, wrote, error, failure } = await saveRow(runId, row, decision);
    outcome.wrote ||= wrote;
    if (error === null) {
      outcome.saved.push(key);
      continue;
    }
    const part = done > 0 ? `saved ${done} of ${row.findings.length}; ` : "";
    const lead = row.commentNo === null ? "A comment with no number was not saved." : `Comment ${row.commentNo} was not saved.`;
    const plain = failure
      ? plainError(lead, failure)
      : { words: `${lead} The required action is empty: write it, or keep the comment as it is.`, detail: null };
    outcome.failed.push({
      key, message: `Comment ${row.commentNo ?? "-"}: ${part}${error}`,
      words: plain.words, detail: [part ? part.replace(/; $/, "") : "", plain.detail ?? ""].filter(Boolean).join("; ") || null,
    });
  }
  return outcome;
}
