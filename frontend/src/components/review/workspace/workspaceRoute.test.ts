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
import { DEFAULT_WORKSPACE_QUERY, OLD_REVIEW_PANEL_TABS, isWorkspaceScreen, parseWorkspaceQuery, reviewPageFor, workspaceSearch } from "./workspaceRoute";
import { PANELS } from "../../../routing";

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

/** Owner, 19 Oct 2026: the workspace replaces the old review design
 *  permanently. Every old review address leads into it.
 *  MUTATION PROOF: drop an entry from OLD_REVIEW_PANEL_TABS and its test
 *  opens the sheet tab instead (or the coverage test fails); stop sending
 *  /review/inbox to the first page and the inbox test fails; mark the
 *  workspace's own address redirected and the "keeps working" test fails. */
describe("reviewPageFor (old addresses lead into the workspace)", () => {
  const blank = { row: null, panel: null, documentId: null };

  it("/review is the workspace's first page", () => {
    expect(reviewPageFor(undefined, undefined, "")).toEqual({ kind: "landing", address: "/review", redirected: false });
  });

  it("/review/inbox (the old inbox) leads to the workspace's first page", () => {
    expect(reviewPageFor("inbox", undefined, "")).toEqual({ kind: "landing", address: "/review", redirected: true });
  });

  it("/review/<run> is the workspace, as asked", () => {
    expect(reviewPageFor("run-1", undefined, "?tab=steps&row=r-2")).toEqual({
      kind: "workspace", location: { runId: "run-1", tab: "steps", row: "r-2", panel: null, documentId: null },
      address: "/review/run-1?tab=steps&row=r-2", redirected: false,
    });
  });

  it("/review/<run>/workspace keeps working, at its own address", () => {
    expect(reviewPageFor("run-1", "workspace", "?tab=crs")).toEqual({
      kind: "workspace", location: { runId: "run-1", tab: "crs", ...blank },
      address: "/review/run-1/workspace?tab=crs", redirected: false,
    });
  });

  it.each([
    ["cards", "sheet", "/review/run-1"],
    ["crs-sheet", "sheet", "/review/run-1"],
    ["findings", "findings", "/review/run-1?tab=findings"],
    ["standards", "standards", "/review/run-1?tab=standards"],
    ["steps", "steps", "/review/run-1?tab=steps"],
    ["numbers", "numbers", "/review/run-1?tab=numbers"],
    ["how", "how", "/review/run-1?tab=how"],
    ["crs", "crs", "/review/run-1?tab=crs"],
  ] as const)("/review/<run>/%s opens the workspace on the %s tab at %s", (panel, tab, address) => {
    expect(reviewPageFor("run-1", panel, "")).toEqual({
      kind: "workspace", location: { runId: "run-1", tab, ...blank }, address, redirected: true,
    });
  });

  it("every old review address the router accepts has a place in the workspace", () => {
    const old = (PANELS.review ?? []).filter((p) => p !== "workspace");
    expect(old.slice().sort()).toEqual(Object.keys(OLD_REVIEW_PANEL_TABS).sort());
  });

  it("an odd run id is kept safe in the new address", () => {
    expect(reviewPageFor("run 1/2", "findings", "").address).toBe("/review/run%201%2F2?tab=findings");
  });
});
