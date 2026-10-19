/**
 * The ONE way the app issues the contractor's copy (signs and exports it).
 *
 * Both screens that may sign use this and nothing else: the comment sheet
 * (views/CrsSheetView.tsx) and the new review workspace's sign-off
 * (workspace/useSignOff.ts). It applies the same rules the comment sheet's
 * Sign and export button follows (order 121, "Before you sign"):
 *  - no decision is on screen only (everything is saved), and no draft
 *    from an earlier visit is waiting for "Bring them back" / "Discard"
 *    (order 141 D: a signed review deletes that draft);
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
  /** Order 141 D: decisions in a draft from an earlier visit still waiting
   *  for the reader's answer (absent or 0 when none). */
  draftWaiting?: number;
  /** Comments marked "Needs you" not opened yet. */
  unopenedNeedsYou: number;
  /** What the issue gate still wants (`signLeft`); empty when nothing. */
  signLeft: string[];
}

export const ISSUED_MESSAGE = "Signed and exported. The issued copy was downloaded and kept on record.";

/** Sign waits for the comments only an engineer can judge ("Needs you")
 *  to be opened; the same words on the old sheet and the workspace. */
export function needsYouFirst(n: number): string {
  return `Open the ${n} ${n === 1 ? "comment that needs" : "comments that need"} your judgement (marked "Needs you") first.`;
}

/** Order 141 D: a draft from an earlier visit is not on the record. */
export function draftFirst(n: number): string {
  return n === 1
    ? "1 decision from an earlier visit is not on the record: bring it back or discard it first."
    : `${n.toLocaleString()} decisions from an earlier visit are not on the record: bring them back or discard them first.`;
}

/** Why the copy cannot be issued yet, in plain words; null when it can. */
export function issueWaitsFor(checks: IssueChecks): string | null {
  if ((checks.draftWaiting ?? 0) > 0) return draftFirst(checks.draftWaiting ?? 0);
  if (checks.unsaved > 0) {
    return `Save the ${checks.unsaved} ${checks.unsaved === 1 ? "decision" : "decisions"} on screen first.`;
  }
  if (checks.unopenedNeedsYou > 0) {
    return needsYouFirst(checks.unopenedNeedsYou);
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
