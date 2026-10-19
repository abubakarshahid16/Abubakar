/**
 * OWNER: builder B. Sign-off for the workspace: save the on-screen
 * decisions, sign and export the contractor copy, or download the unsigned
 * working copy. Existing routes only, the same ones CrsSheetView uses.
 */
import { useCallback, useState } from "react";

import type { SignOff, UseSignOffArgs } from "./contract";
import { downloadCrs } from "../downloadCrs";
import { saveCrsDecisions } from "../crs/saveCrsDecisions";

type Status = { busy: boolean; message: string | null; error: string | null };

export function useSignOff({ runId, rows, decisions, refresh }: UseSignOffArgs): SignOff {
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

  const exportCopy = useCallback(async (copy: "internal" | "issue") => {
    setStatus({ busy: true, message: null, error: null });
    const problem = await downloadCrs(runId, copy);
    if (problem) { setStatus({ busy: false, message: null, error: problem }); return; }
    setStatus({
      busy: false, error: null,
      message: copy === "issue"
        ? "Signed and exported. The signed copy was downloaded and kept on record."
        : "Working copy downloaded. It is not signed.",
    });
    await refresh();
  }, [runId, refresh]);

  /** NOTE: #1150 (a dedicated sign-off route) is NOT on main. Signing uses
   *  the existing path CrsSheetView's "Sign and export" uses today:
   *  `downloadCrs(runId, "issue")`, which the server still refuses while
   *  anything is open. Swap it here when #1150 lands. */
  const sign = useCallback(() => exportCopy("issue"), [exportCopy]);
  const workingCopy = useCallback(() => exportCopy("internal"), [exportCopy]);

  return { ...status, save, sign, workingCopy };
}
