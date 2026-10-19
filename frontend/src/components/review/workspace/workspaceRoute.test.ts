/**
 * Builder A: the workspace's address keeps the reader's place.
 *
 * MUTATION PROOF: drop the "tab" check in parseWorkspaceQuery and the junk
 * test fails (an unknown tab leaks through); write the default tab into the
 * query and "defaults are left out" fails; drop "doc" from workspaceSearch and
 * the round trip fails.
 */
import { describe, expect, it } from "vitest";

import { WORKSPACE_TABS, type WorkspaceLocation } from "./contract";
import { DEFAULT_WORKSPACE_QUERY, isWorkspaceScreen, parseWorkspaceQuery, workspaceSearch } from "./workspaceRoute";

describe("parseWorkspaceQuery / workspaceSearch", () => {
  it("round-trip for every tab, with and without an open row", () => {
    for (const tab of WORKSPACE_TABS) {
      for (const row of [null, "row-1", "r/2 & more?=x"]) {
        for (const panel of [null, "evidence"] as const) {
          for (const documentId of [null, "doc-7"]) {
            const location: WorkspaceLocation = { runId: "run-1", tab, row, panel, documentId };
            const { runId: _runId, ...query } = location;
            expect(parseWorkspaceQuery(workspaceSearch(location))).toEqual(query);
          }
        }
      }
    }
  });

  it("defaults are left out of the address", () => {
    expect(workspaceSearch({ runId: "run-1", ...DEFAULT_WORKSPACE_QUERY })).toBe("");
    expect(workspaceSearch({ runId: "run-1", tab: "standards", row: "row-3", panel: "evidence", documentId: null }))
      .toBe("?tab=standards&row=row-3&panel=evidence");
  });

  it("reads a pasted address with or without the leading ?", () => {
    const want = { tab: "standards", row: "row-3", panel: "evidence", documentId: "doc-1" };
    expect(parseWorkspaceQuery("?tab=standards&row=row-3&panel=evidence&doc=doc-1")).toEqual(want);
    expect(parseWorkspaceQuery("tab=standards&row=row-3&panel=evidence&doc=doc-1")).toEqual(want);
  });

  it("junk falls back to the defaults and never throws", () => {
    for (const junk of ["", "?", "?tab=nope&panel=drawer", "?tab=&row=&panel=&doc=", "%%%", "?tab=%E0%A4%A", "?row"]) {
      expect(() => parseWorkspaceQuery(junk)).not.toThrow();
      const parsed = parseWorkspaceQuery(junk);
      expect(parsed.tab).toBe("sheet");
      expect(parsed.panel).toBeNull();
    }
    expect(parseWorkspaceQuery("?tab=nope&row=row-9&panel=drawer"))
      .toEqual({ tab: "sheet", row: "row-9", panel: null, documentId: null });
  });
});

describe("isWorkspaceScreen", () => {
  it("own address always; the plain run address only with the switch on; other pages never", () => {
    expect(isWorkspaceScreen("workspace", false)).toBe(true);
    expect(isWorkspaceScreen(undefined, false)).toBe(false);
    expect(isWorkspaceScreen(undefined, true)).toBe(true);
    for (const panel of ["cards", "crs-sheet", "how", "findings", "crs"]) expect(isWorkspaceScreen(panel, true)).toBe(false);
  });
});
