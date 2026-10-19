/**
 * Planner team: the contract compiles and its two switch rules hold. Each
 * builder adds their own tests next to their own files (SPEC.md section 8).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import * as contract from "./contract";
import { WORKSPACE_IS_DEFAULT } from "../../../routing";

describe("workspace v2 contract", () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

  it("is off by default", () => {
    expect(WORKSPACE_IS_DEFAULT).toBe(false);
  });

  it("opens the workspace only on its own address, or with the switch on", () => {
    expect(contract.isWorkspaceScreen("workspace", false)).toBe(true);
    expect(contract.isWorkspaceScreen(undefined, false)).toBe(false);
    expect(contract.isWorkspaceScreen(undefined, true)).toBe(true);
    expect(contract.isWorkspaceScreen("crs-sheet", true)).toBe(false);
    expect(contract.isWorkspaceScreen("cards", true)).toBe(false);
  });

  it("a blocked storage never breaks the switch", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(contract.readWorkspaceOptIn()).toBe(false);
    expect(() => contract.writeWorkspaceOptIn(true)).not.toThrow();
  });

  it("every tab has a plain label", () => {
    for (const tab of contract.WORKSPACE_TABS) expect(contract.WORKSPACE_TAB_LABELS[tab]).toMatch(/^[A-Z][a-z ]+$/);
  });
});
