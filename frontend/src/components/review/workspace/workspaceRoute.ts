/**
 * OWNER: builder A. The workspace's address.
 * `/review/<run>/workspace?tab=..&row=..&panel=..&doc=..`. Pure functions:
 * no React, no window. The run id is the path; everything else that keeps
 * the reader's place is the query string, so a refresh (or a sign-in in
 * between) lands in the same place.
 */
import { WORKSPACE_TABS, type WorkspaceLocation, type WorkspacePanel, type WorkspaceQuery, type WorkspaceTab } from "./contract";

/** The third path segment that always opens the workspace. */
export const WORKSPACE_PANEL = "workspace";

/** The per-browser "Try new design" key (localStorage). */
export const WORKSPACE_OPT_IN_KEY = "rag-intelligence-workspace-v2";

const PANELS: readonly WorkspacePanel[] = ["evidence"];

function isTab(value: string | null): value is WorkspaceTab {
  return value !== null && (WORKSPACE_TABS as readonly string[]).includes(value);
}

function isPanel(value: string | null): value is WorkspacePanel {
  return value !== null && (PANELS as readonly string[]).includes(value);
}

/** A non-empty value, else null. */
function text(value: string | null): string | null {
  return value ? value : null;
}

/** The default place: the comment sheet, nothing open. */
export const DEFAULT_WORKSPACE_QUERY: WorkspaceQuery = { tab: "sheet", row: null, panel: null, documentId: null };

/** Reads `?tab=..&row=..&panel=..&doc=..`. Unknown or junk values fall back
 *  to the defaults one by one; this never throws. */
export function parseWorkspaceQuery(search: string): WorkspaceQuery {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return { ...DEFAULT_WORKSPACE_QUERY };
  }
  const tab = params.get("tab");
  const panel = params.get("panel");
  return {
    tab: isTab(tab) ? tab : "sheet",
    row: text(params.get("row")),
    panel: isPanel(panel) ? panel : null,
    documentId: text(params.get("doc")),
  };
}

/** The inverse of `parseWorkspaceQuery`: "" for the default place, else
 *  "?..." with the defaults left out. `parse(workspaceSearch(x))` equals the
 *  query part of `x`. */
export function workspaceSearch(location: WorkspaceLocation): string {
  const params = new URLSearchParams();
  if (location.tab !== "sheet" && isTab(location.tab)) params.set("tab", location.tab);
  if (location.row) params.set("row", location.row);
  if (location.panel && isPanel(location.panel)) params.set("panel", location.panel);
  if (location.documentId) params.set("doc", location.documentId);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Whether `/review/<run>[/<panel>]` shows the workspace: always for
 *  panel "workspace"; for no panel only when the switch is on. */
export function isWorkspaceScreen(panel: string | undefined, switchOn: boolean): boolean {
  if (panel === WORKSPACE_PANEL) return true;
  return !panel && switchOn;
}
