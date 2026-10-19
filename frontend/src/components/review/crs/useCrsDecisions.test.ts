/**
 * Order 95 piece 2: Accept all and its one-step undo.
 *
 * MUTATION PROOF: let Undo restore the whole earlier state and "undo clears
 * only what Accept all set" fails (it would also wipe a decision taken in
 * between); keep the undo after another decision and "any other decision
 * drops the undo" fails.
 */
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { buildCrsRows } from "./crsRows";
import { EMPTY_FACTS } from "./tiers";
import { CrsDraftContext, clearDecisionDrafts, draftStorageKey, setDraftOwner, useCrsDecisions } from "./useCrsDecisions";

function f(id: string, page: number): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: page, approval_status: "pending",
    standard_document_id: "std-1", standard_clause: "4.1",
  } as ReviewFinding;
}

const rows = buildCrsRows([f("a", 1), f("b", 2), f("c", 3)], EMPTY_FACTS, new Map());
const [a, b, c] = rows.map((r) => r.key);

describe("useCrsDecisions: Accept all and undo", () => {
  it("undo clears only the keys Accept all set; a decision taken before it stays", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => result.current.keep(a));
    let kept = 0;
    act(() => { kept = result.current.acceptAll(rows); });
    expect(kept).toBe(2);
    expect(Object.keys(result.current.state.decisions).sort()).toEqual([a, b, c].sort());
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    expect(result.current.state.decisions).toEqual({ [a]: { kind: "keep" } });
    expect(result.current.canUndo).toBe(false);
  });

  it("any other decision after Accept all drops the undo, and nothing it did is lost", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => { result.current.acceptAll(rows); });
    act(() => result.current.remove(b, "Duplicate"));
    expect(result.current.canUndo).toBe(false);
    act(() => result.current.undo());
    expect(result.current.state.decisions).toEqual({
      [a]: { kind: "keep" }, [b]: { kind: "remove", reason: "Duplicate" }, [c]: { kind: "keep" },
    });
  });

  it("opening a row is not a decision and keeps the undo", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => { result.current.acceptAll(rows); });
    act(() => result.current.markOpened(a));
    expect(result.current.canUndo).toBe(true);
  });
});

describe("useCrsDecisions: what is not saved yet (order 95 piece 6c)", () => {
  it("a decision is unsaved until marked saved, and unsaved again once changed", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => result.current.keep(a));
    expect(result.current.unsaved).toEqual([a]);
    act(() => result.current.markSaved([a]));
    expect(result.current.unsaved).toEqual([]);
    act(() => result.current.edit(a, "obs", "Do it."));
    expect(result.current.unsaved).toEqual([a]);
  });
});

/** v2.1 N1: on the workspace (a review id given) the decisions not saved
 *  yet are kept as a draft in this tab, per review and per person, and come
 *  back when the screen opens again; a save clears the draft.
 *  MUTATION PROOF: drop the write effect and "comes back after the screen
 *  closes" fails; drop the owner from the key and "another person never
 *  gets it" fails; stop removing the draft when nothing is unsaved and
 *  "a save clears it" fails. */
describe("useCrsDecisions: the per-review draft (v2.1 N1)", () => {
  beforeEach(() => { sessionStorage.clear(); setDraftOwner(null); });
  afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); setDraftOwner(null); });

  it("unsaved decisions come back after the screen closes and opens again (as after an expired sign-in)", () => {
    setDraftOwner("user-a");
    const first = renderHook(() => useCrsDecisions("run-1"));
    act(() => first.result.current.keep(a));
    act(() => first.result.current.remove(b, "Duplicate"));
    act(() => first.result.current.markOpened(c));
    first.unmount();
    const again = renderHook(() => useCrsDecisions("run-1"));
    expect(again.result.current.state.decisions).toEqual({ [a]: { kind: "keep" }, [b]: { kind: "remove", reason: "Duplicate" } });
    expect(again.result.current.state.opened[c]).toBe(true);
    expect(again.result.current.unsaved.sort()).toEqual([a, b].sort());
    expect(again.result.current.restored).toBe(2);
  });

  it("a save clears the draft", () => {
    const { result } = renderHook(() => useCrsDecisions("run-1"));
    act(() => result.current.keep(a));
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).not.toBeNull();
    act(() => result.current.markSaved([a]));
    expect(result.current.unsaved).toEqual([]);
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).toBeNull();
  });

  it("is kept per review and per person: another review or another person never gets it", () => {
    setDraftOwner("user-a");
    const first = renderHook(() => useCrsDecisions("run-1"));
    act(() => first.result.current.keep(a));
    first.unmount();
    expect(renderHook(() => useCrsDecisions("run-2")).result.current.state.decisions).toEqual({});
    setDraftOwner("user-b");
    expect(renderHook(() => useCrsDecisions("run-1")).result.current.state.decisions).toEqual({});
    setDraftOwner("user-a");
    expect(renderHook(() => useCrsDecisions("run-1")).result.current.state.decisions).toEqual({ [a]: { kind: "keep" } });
  });

  it("clearDecisionDrafts removes only that person's drafts", () => {
    sessionStorage.setItem(draftStorageKey("run-1", "user-a"), "{}");
    sessionStorage.setItem(draftStorageKey("run-2", "user-a"), "{}");
    sessionStorage.setItem(draftStorageKey("run-1", "user-b"), "{}");
    clearDecisionDrafts("user-a");
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-a"))).toBeNull();
    expect(sessionStorage.getItem(draftStorageKey("run-2", "user-a"))).toBeNull();
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-b"))).toBe("{}");
  });

  it("the old screen (no review id) keeps no draft at all", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => result.current.keep(a));
    expect(sessionStorage.length).toBe(0);
  });

  it("junk in storage is ignored, and blocked storage never breaks deciding", () => {
    sessionStorage.setItem(draftStorageKey("run-1"), JSON.stringify({ decisions: { [a]: { kind: "remove", reason: "made up" }, [b]: { kind: "keep" } } }));
    expect(renderHook(() => useCrsDecisions("run-1")).result.current.state.decisions).toEqual({ [b]: { kind: "keep" } });
    sessionStorage.setItem(draftStorageKey("run-1"), "not json");
    expect(renderHook(() => useCrsDecisions("run-1")).result.current.state.decisions).toEqual({});
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const { result } = renderHook(() => useCrsDecisions("run-3"));
    act(() => result.current.keep(a));
    expect(result.current.unsaved).toEqual([a]);
  });

  it("the review id can come from the app's CrsDraftContext", () => {
    const wrapper = ({ children }: { children: ReactNode }) => createElement(CrsDraftContext.Provider, { value: "run-ctx" }, children);
    const { result } = renderHook(() => useCrsDecisions(), { wrapper });
    act(() => result.current.keep(a));
    expect(JSON.parse(sessionStorage.getItem(draftStorageKey("run-ctx")) ?? "{}").decisions).toEqual({ [a]: { kind: "keep" } });
  });
});
