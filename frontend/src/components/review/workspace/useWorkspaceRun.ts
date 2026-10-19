/**
 * OWNER: builder A. The run's data for the workspace (PLACEHOLDER - planner
 * team). Builder A implements it with the same reads as CrsSheetView's
 * `useRunData` (reviewRun, list, reviewRunStandards, reviewRunSummary,
 * document) plus `reviewsApi.readiness(submittalId)`, newest-load-wins,
 * 3 s poll while active, rows via buildCrsRows.
 */
import type { WorkspaceRunData } from "./contract";

const NOOP = async () => {};

export function useWorkspaceRun(_runId: string): WorkspaceRunData {
  return {
    load: { kind: "loading" }, run: null, findings: [], rows: [],
    standardsState: { standards: null, missing: [], error: null },
    standardNames: new Map(), submittal: null, summary: null, readiness: null,
    active: false, refresh: NOOP,
  };
}
