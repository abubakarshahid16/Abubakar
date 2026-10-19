/**
 * OWNER: builder A. The workspace's address.
 * `/review/<run>/workspace?tab=..&row=..&panel=..&doc=..`. Pure functions:
 * no React, no window. The run id is the path; everything else that keeps
 * the reader's place is the query string, so a refresh (or a sign-in in
 * between) lands in the same place.
 */
import { INBOX_RECORD, pathForView } from "../../../routing";
import { WORKSPACE_TABS, type WorkspaceLocation, type WorkspacePanel, type WorkspaceQuery, type WorkspaceTab } from "./contract";

/** The third path segment that always opens the workspace. */
export const WORKSPACE_PANEL = "workspace";

/** The old per-browser "Try new design" key (localStorage). Nothing reads
 *  it to decide what shows any more (owner, 19 Oct 2026). */
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
 *  panel "workspace"; for no panel only when the switch is on. Superseded in
 *  the App by `reviewPageFor` (the switch is gone); kept for the contract
 *  until the clean-up that removes the old screens. */
export function isWorkspaceScreen(panel: string | undefined, switchOn: boolean): boolean {
  if (panel === WORKSPACE_PANEL) return true;
  return !panel && switchOn;
}

/**
 * THE ONE MAP from the old review screens to the workspace (owner's written
 * order, 19 Oct 2026: the new review workspace replaces the old review
 * design permanently). Each old third path segment of `/review/<run>/<x>`
 * opens the workspace on the tab that holds the same thing, so old
 * bookmarks and links still work:
 *   cards, crs-sheet          -> the comment sheet tab
 *   findings, standards, steps, numbers, how, crs -> the tab of that name
 */
export const OLD_REVIEW_PANEL_TABS: Readonly<Record<string, WorkspaceTab>> = {
  cards: "sheet",
  "crs-sheet": "sheet",
  findings: "findings",
  standards: "standards",
  steps: "steps",
  numbers: "numbers",
  how: "how",
  crs: "crs",
};

/** What a `/review[/<record>[/<panel>]]` address opens now. `address` is
 *  where the browser should say it is; `redirected` is true when that is not
 *  the address asked for (an old screen's address, or the old inbox), so the
 *  App replaces it in the history and a bookmark of it keeps working. */
export type ReviewPage =
  | { kind: "landing"; address: string; redirected: boolean }
  | { kind: "workspace"; location: WorkspaceLocation; address: string; redirected: boolean };

export function reviewPageFor(recordId: string | undefined, panel: string | undefined, search: string): ReviewPage {
  const landing = pathForView("review");
  // The first page, and the old inbox (`/review/inbox`): the workspace's
  // first page.
  if (!recordId) return { kind: "landing", address: landing, redirected: false };
  if (recordId === INBOX_RECORD && !panel) return { kind: "landing", address: landing, redirected: true };
  const query = parseWorkspaceQuery(search);
  if (!panel || panel === WORKSPACE_PANEL) {
    return {
      kind: "workspace", location: { runId: recordId, ...query },
      address: pathForView("review", recordId, panel) + search, redirected: false,
    };
  }
  const tab = Object.prototype.hasOwnProperty.call(OLD_REVIEW_PANEL_TABS, panel) ? OLD_REVIEW_PANEL_TABS[panel] : "sheet";
  const location: WorkspaceLocation = { runId: recordId, ...query, tab };
  return {
    kind: "workspace", location,
    address: pathForView("review", recordId) + workspaceSearch(location), redirected: true,
  };
}
