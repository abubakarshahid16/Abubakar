/**
 * OWNER: builder A. The workspace's address (PLACEHOLDER - planner team).
 * `/review/<run>/workspace?tab=..&row=..&panel=..&doc=..`. Pure functions.
 */
import type { WorkspaceLocation, WorkspaceQuery } from "./contract";

/** The third path segment that always opens the workspace. */
export const WORKSPACE_PANEL = "workspace";

/** The per-browser "Try new design" key (localStorage). */
export const WORKSPACE_OPT_IN_KEY = "rag-intelligence-workspace-v2";

/** PLACEHOLDER: always the default place. Builder A implements parsing. */
export function parseWorkspaceQuery(_search: string): WorkspaceQuery {
  return { tab: "sheet", row: null, panel: null, documentId: null };
}

/** PLACEHOLDER: "". Builder A implements; defaults are left out of the URL. */
export function workspaceSearch(_location: WorkspaceLocation): string {
  return "";
}

/** Whether `/review/<run>[/<panel>]` shows the workspace: always for
 *  panel "workspace"; for no panel only when the switch is on. */
export function isWorkspaceScreen(panel: string | undefined, switchOn: boolean): boolean {
  if (panel === WORKSPACE_PANEL) return true;
  return !panel && switchOn;
}
