/**
 * The ONE way the app issues the contractor's copy (signs and exports it).
 *
 * Both screens that may sign use this and nothing else: the comment sheet
 * (views/CrsSheetView.tsx) and the new review workspace's sign-off
 * (workspace/useSignOff.ts). It applies the same rules the comment sheet's
 * Sign and export button follows (order 121, "Before you sign"):
 *  - no decision is on screen only (everything is saved);
 *  - every "Needs you" row has been opened;
 *  - the issue gate has nothing left (`signLeft` from issueGate.ts: the
 *    final code is recorded, every unread page is ticked, every item on the
 *    copy is decided).
 * While any of these is not met it refuses here, in plain words, and never
 * asks the server. The server still refuses on its own too.
 *
 * views/oldIssueGateFenced.test.ts checks that this file is the only one
 * that asks for the "issue" copy, and that only the two screens above call
 * it.
 */
import { downloadCrs } from "../downloadCrs";

/** What must be true before the contractor's copy is issued. */
export interface IssueChecks {
  /** Decisions on screen that are not saved yet. */
  unsaved: number;
  /** "Needs you" rows not opened yet. */
  unopenedNeedsYou: number;
  /** What the issue gate still wants (`signLeft`); empty when nothing. */
  signLeft: string[];
}

export const ISSUED_MESSAGE = "Signed and exported. The issued copy was downloaded and kept on record.";

/** Why the copy cannot be issued yet, in plain words; null when it can. */
export function issueWaitsFor(checks: IssueChecks): string | null {
  if (checks.unsaved > 0) {
    return `Save the ${checks.unsaved} ${checks.unsaved === 1 ? "decision" : "decisions"} on screen first.`;
  }
  if (checks.unopenedNeedsYou > 0) {
    const n = checks.unopenedNeedsYou;
    return `Open the ${n} "Needs you" ${n === 1 ? "row" : "rows"} first.`;
  }
  if (checks.signLeft.length > 0) return `Before you sign: ${checks.signLeft.join("; ")}.`;
  return null;
}

export type IssueOutcome = { ok: true } | { ok: false; message: string };

/** Sign and export: checks the rules above, then asks the server for the
 *  contractor's copy and hands it to the browser. */
export async function issueContractorCopy(runId: string, checks: IssueChecks): Promise<IssueOutcome> {
  const waits = issueWaitsFor(checks);
  if (waits) return { ok: false, message: waits };
  const problem = await downloadCrs(runId, "issue");
  return problem ? { ok: false, message: problem } : { ok: true };
}
