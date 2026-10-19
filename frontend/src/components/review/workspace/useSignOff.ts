/**
 * OWNER: builder B. Sign-off for the workspace: save the on-screen
 * decisions, sign and export the contractor copy, or download the unsigned
 * working copy. Existing routes only, the same ones CrsSheetView uses.
 *
 * Signing goes through `issueContractorCopy` (crs/issueContractorCopy.ts),
 * the one shared issuing path the comment sheet uses too: it checks the
 * same rules (everything saved, every "Needs you" row opened, the issue
 * gate clear) before it asks the server.
 */
import { useCallback, useState } from "react";

import type { SignOff, UseSignOffArgs } from "./contract";
import { downloadCrs } from "../downloadCrs";
import { ISSUED_MESSAGE, issueContractorCopy } from "../crs/issueContractorCopy";
import { saveCrsDecisions } from "../crs/saveCrsDecisions";

type Status = { busy: boolean; message: string | null; error: string | null };

export function useSignOff({ runId, rows, decisions, refresh, numbers }: UseSignOffArgs): SignOff {
  const [status, setStatus] = useState<Status>({ busy: false, message: null, error: null });
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

  const sign = useCallback(async () => {
    setStatus({ busy: true, message: null, error: null });
    const outcome = await issueContractorCopy(runId, {
      unsaved: decisions.unsaved.length,
      unopenedNeedsYou: numbers ? numbers.unopenedNeedsYou : 0,
      // Not loaded yet is never "nothing left".
      signLeft: numbers ? numbers.signLeft : ["what is left could not be checked"],
    });
    if (!outcome.ok) { setStatus({ busy: false, message: null, error: outcome.message }); return; }
    setStatus({ busy: false, error: null, message: ISSUED_MESSAGE });
    await refresh();
  }, [runId, decisions.unsaved.length, numbers, refresh]);

  const workingCopy = useCallback(async () => {
    setStatus({ busy: true, message: null, error: null });
    const problem = await downloadCrs(runId, "internal");
    if (problem) { setStatus({ busy: false, message: null, error: problem }); return; }
    setStatus({ busy: false, error: null, message: "Working copy downloaded. It is not signed." });
  }, [runId]);

  return { ...status, save, sign, workingCopy };
}
