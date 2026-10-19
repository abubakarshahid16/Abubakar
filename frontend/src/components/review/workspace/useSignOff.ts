/**
 * OWNER: builder C (v2.1; builder B before). Sign-off for the workspace:
 * save the on-screen decisions, sign and export the contractor copy, or
 * download the unsigned working copy. Existing routes only, the same ones
 * CrsSheetView uses.
 *
 * SIGNING HAS TWO STEPS (v2.1 gap S2). `sign()` never issues anything: it
 * checks the same rules the issuing path checks (`issueWaitsFor`) and, when
 * nothing is left, opens the "Preview and confirm" step (`confirmOpen`).
 * Only the confirm step's "Issue to contractor" button issues, by calling
 * `issueConfirmed(runId)` below, which runs this hook's issuer with the live
 * checks.
 *
 * Issuing goes through `issueContractorCopy` (crs/issueContractorCopy.ts),
 * the one shared issuing path the comment sheet uses too: it checks the
 * same rules (everything saved, every "Needs you" row opened, the issue
 * gate clear) before it asks the server. views/oldIssueGateFenced.test.ts
 * keeps this file and CrsSheetView the only callers, which is why the
 * confirm step (workspace/sign/SignConfirm.tsx) asks this file to issue
 * rather than calling the issuing path itself.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { SignOff, UseSignOffArgs } from "./contract";
import { downloadCrs } from "../downloadCrs";
import {
  ISSUED_MESSAGE, issueContractorCopy, issueWaitsFor, type IssueChecks, type IssueOutcome,
} from "../crs/issueContractorCopy";
import { saveCrsDecisions } from "../crs/saveCrsDecisions";

type Status = { busy: boolean; message: string | null; error: string | null };

/** What the workspace's sign-off offers on top of `SignOff`: the
 *  "Preview and confirm" step that `sign()` opens. */
export interface WorkspaceSignOff extends SignOff {
  /** The confirm step is open (`sign()` found nothing left). */
  confirmOpen: boolean;
  /** Close the confirm step without issuing anything. */
  closeConfirm: () => void;
}

/** Shown when the confirm step is pressed but no sign-off for that review
 *  is on screen (it was closed or never loaded): nothing is issued. */
export const NO_SIGN_OFF_MESSAGE =
  "This review's sign-off is not open any more, so nothing was issued. Open the review again and press Sign and export.";

/** The live issuer of each review whose sign-off is on screen. */
const issuers = new Map<string, () => Promise<IssueOutcome>>();

/** Issue the contractor's copy for `runId`, from the confirm step. Runs the
 *  on-screen sign-off's issuer, so the live checks apply; refuses in plain
 *  words, and issues nothing, when no sign-off for that review is open. */
export async function issueConfirmed(runId: string): Promise<IssueOutcome> {
  const issue = issuers.get(runId);
  if (!issue) return { ok: false, message: NO_SIGN_OFF_MESSAGE };
  return issue();
}

export function useSignOff({ runId, rows, decisions, refresh, numbers, beforeCopy }: UseSignOffArgs): WorkspaceSignOff {
  const [status, setStatus] = useState<Status>({ busy: false, message: null, error: null });
  const [confirmOpen, setConfirmOpen] = useState(false);

  const save = useCallback(async () => {
    if (decisions.unsaved.length === 0) return;
    setStatus({ busy: true, message: null, error: null });
    const outcome = await saveCrsDecisions(runId, rows, decisions.state.decisions, decisions.unsaved);
    decisions.markSaved(outcome.saved);
    setStatus({
      busy: false,
      message: outcome.saved.length > 0
        ? `${outcome.saved.length} ${outcome.saved.length === 1 ? "decision" : "decisions"} saved.` : null,
      error: outcome.failed.length > 0
        ? `${outcome.failed.length} not saved: ${outcome.failed.map((f) => f.message).join("; ")}` : null,
    });
    if (outcome.wrote) await refresh();
  }, [runId, rows, decisions, refresh]);

  const draftWaiting = decisions.pendingRestore?.count ?? 0;
  const checks = useCallback((): IssueChecks => ({
    unsaved: decisions.unsaved.length,
    // Order 141 D: a draft still waiting for an answer holds Sign; signing
    // would issue without it and then delete it.
    draftWaiting,
    unopenedNeedsYou: numbers ? numbers.unopenedNeedsYou : 0,
    // Not loaded yet is never "nothing left".
    signLeft: numbers ? numbers.signLeft : ["what is left could not be checked"],
  }), [decisions.unsaved.length, draftWaiting, numbers]);

  /** Opens the confirm step; issues nothing. */
  const sign = useCallback(async () => {
    const waits = issueWaitsFor(checks());
    if (waits) { setStatus({ busy: false, message: null, error: waits }); return; }
    setStatus({ busy: false, message: null, error: null });
    setConfirmOpen(true);
  }, [checks]);

  const closeConfirm = useCallback(() => setConfirmOpen(false), []);

  /** The real issue, only ever reached from the confirm step. */
  const issue = useCallback(async (): Promise<IssueOutcome> => {
    setStatus({ busy: true, message: null, error: null });
    const outcome = await issueContractorCopy(runId, checks());
    if (!outcome.ok) { setStatus({ busy: false, message: null, error: outcome.message }); return outcome; }
    setStatus({ busy: false, error: null, message: ISSUED_MESSAGE });
    setConfirmOpen(false);
    await refresh();
    return outcome;
  }, [runId, checks, refresh]);

  // Register the latest issuer for this review while the sign-off is on
  // screen; the ref keeps the registration stable between renders.
  const issueRef = useRef(issue);
  useEffect(() => { issueRef.current = issue; }, [issue]);
  useEffect(() => {
    const entry = () => issueRef.current();
    issuers.set(runId, entry);
    return () => { if (issuers.get(runId) === entry) issuers.delete(runId); };
  }, [runId]);

  const workingCopy = useCallback(async () => {
    setStatus({ busy: true, message: null, error: null });
    // Order 141 D: the copy is built from the record; the decisions on
    // screen go there first, or nothing is downloaded and the reason shows.
    const waits = beforeCopy ? await beforeCopy() : null;
    if (waits) { setStatus({ busy: false, message: null, error: waits }); return; }
    const problem = await downloadCrs(runId, "internal");
    if (problem) { setStatus({ busy: false, message: null, error: problem }); return; }
    setStatus({ busy: false, error: null, message: "Working copy downloaded. It is not signed." });
  }, [runId, beforeCopy]);

  return { ...status, save, sign, workingCopy, confirmOpen, closeConfirm };
}
