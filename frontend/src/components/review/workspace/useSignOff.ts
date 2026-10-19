/**
 * OWNER: builder B. Sign-off for the workspace (PLACEHOLDER - planner team).
 * #1150 is NOT on main: builder B wires `sign` to the existing sign path,
 * `downloadCrs(runId, "issue")` (what CrsSheetView's Sign and export does),
 * `workingCopy` to `downloadCrs(runId, "internal")`, and `save` to
 * `saveCrsDecisions(runId, rows, decisions.state.decisions, decisions.unsaved)`.
 */
import type { SignOff, UseSignOffArgs } from "./contract";

const NOOP = async () => {};

export function useSignOff(_args: UseSignOffArgs): SignOff {
  return { busy: false, message: null, error: null, save: NOOP, sign: NOOP, workingCopy: NOOP };
}
