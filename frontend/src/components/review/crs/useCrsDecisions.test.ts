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
import { CrsDraftContext, clearDecisionDrafts, draftStorageKey, keepOnlyDraftsOf, recordStamp, setDraftOwner, useCrsDecisions } from "./useCrsDecisions";

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

/** v2.1 N1 and round 2: on the workspace (a review id given) the decisions
 *  not saved yet are kept as a draft in this tab, per review and per
 *  person. A draft never comes back or saves by itself: the hook offers it
 *  (`pendingRestore`) and only "Yes" (`restoreDraft`) puts it on screen.
 *  Each entry carries the record's state of its row; one whose row changed
 *  since is dropped and counted. A signed review keeps and offers none.
 *  MUTATION PROOF: read the draft straight into `state` again and "is only
 *  offered" fails; skip the stamp check in restoreDraft and "a changed row
 *  is dropped" fails; drop the owner from the key and "another person never
 *  gets it" fails; stop removing the draft when nothing is unsaved and "a
 *  save clears it" fails; ignore `locked` and "a signed review" fails. */
describe("useCrsDecisions: the per-review draft (v2.1 N1, round 2)", () => {
  beforeEach(() => { sessionStorage.clear(); setDraftOwner(null); });
  afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); setDraftOwner(null); });

  /** A screen that knows the record (as useAutosave tells it). */
  function open(runId: string, record = rows, locked = false) {
    const hook = renderHook(() => useCrsDecisions(runId));
    act(() => hook.result.current.observeRecord?.(record, locked));
    return hook;
  }

  it("a draft is only offered: nothing is on screen or unsaved until Yes", () => {
    setDraftOwner("user-a");
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    act(() => first.result.current.remove(b, "Duplicate"));
    act(() => first.result.current.markOpened(c));
    first.unmount();
    const again = open("run-1");
    expect(again.result.current.state.decisions).toEqual({});
    expect(again.result.current.unsaved).toEqual([]);
    expect(again.result.current.pendingRestore).toEqual({ count: 2 });
    // Still kept while the question waits.
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).not.toBeNull();
    act(() => again.result.current.restoreDraft?.());
    expect(again.result.current.state.decisions).toEqual({ [a]: { kind: "keep" }, [b]: { kind: "remove", reason: "Duplicate" } });
    expect(again.result.current.state.opened[c]).toBe(true);
    expect(again.result.current.unsaved.sort()).toEqual([a, b].sort());
    expect(again.result.current.restored).toBe(2);
    expect(again.result.current.restoreDropped).toBe(0);
    expect(again.result.current.pendingRestore).toBeNull();
  });

  it("a decision whose row changed on the record since, or left the sheet, is dropped and counted", () => {
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    act(() => first.result.current.keep(b));
    act(() => first.result.current.keep(c));
    first.unmount();
    const stored = JSON.parse(sessionStorage.getItem(draftStorageKey("run-1")) ?? "{}");
    expect(Object.keys(stored.stamps).sort()).toEqual([a, b, c].sort());
    // Someone confirmed comment b meanwhile; comment c left the sheet.
    const changed = buildCrsRows([f("a", 1), { ...f("b", 2), confirmed_by: "someone" }], EMPTY_FACTS, new Map());
    expect(changed.map((r) => r.key)).toEqual([a, b]);
    const again = open("run-1", changed);
    expect(again.result.current.pendingRestore).toEqual({ count: 3 });
    act(() => again.result.current.restoreDraft?.());
    expect(again.result.current.state.decisions).toEqual({ [a]: { kind: "keep" } });
    expect(again.result.current.restored).toBe(1);
    expect(again.result.current.restoreDropped).toBe(2);
  });

  /** v2.1 follow-up: opened marks carry the same stamp as decisions. A
   *  "Needs you" row whose record changed since, or that left the sheet,
   *  does not come back opened. MUTATION PROOF: bring `pending.opened` back
   *  unchecked in restoreDraft (or the held marks unchecked) and these fail. */
  it("an opened mark whose row changed on the record since, or left the sheet, does not come back", () => {
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    act(() => first.result.current.markOpened(b));
    act(() => first.result.current.markOpened(c));
    act(() => first.result.current.markOpened(a));
    first.unmount();
    const stored = JSON.parse(sessionStorage.getItem(draftStorageKey("run-1")) ?? "{}");
    expect(Object.keys(stored.openedStamps).sort()).toEqual([a, b, c].sort());
    // Someone confirmed comment b meanwhile; comment c left the sheet.
    const changed = buildCrsRows([f("a", 1), { ...f("b", 2), confirmed_by: "someone" }], EMPTY_FACTS, new Map());
    const again = open("run-1", changed);
    act(() => again.result.current.restoreDraft?.());
    expect(again.result.current.state.opened).toEqual({ [a]: true });
  });

  it("opened marks kept alone come back only once the record is known, and only for unchanged rows", () => {
    const stampOf = (key: string) => recordStamp(rows.find((r) => r.key === key)!);
    sessionStorage.setItem(draftStorageKey("run-1"), JSON.stringify({
      decisions: {}, opened: [a, b, c], stamps: {}, openedStamps: { [a]: stampOf(a), [b]: "an older state" },
    }));
    const hook = renderHook(() => useCrsDecisions("run-1"));
    expect(hook.result.current.state.opened).toEqual({});
    act(() => hook.result.current.observeRecord?.(rows, false));
    expect(hook.result.current.state.opened).toEqual({ [a]: true });
  });

  it("Discard throws the draft away", () => {
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    first.unmount();
    const again = open("run-1");
    act(() => again.result.current.discardDraft?.());
    expect(again.result.current.pendingRestore).toBeNull();
    expect(again.result.current.state.decisions).toEqual({});
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).toBeNull();
  });

  it("a decision taken while the question waits is kept with the draft, and wins over it on Yes", () => {
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    first.unmount();
    const again = open("run-1");
    act(() => again.result.current.remove(a, "Duplicate"));
    act(() => again.result.current.keep(b));
    expect(JSON.parse(sessionStorage.getItem(draftStorageKey("run-1")) ?? "{}").decisions)
      .toEqual({ [a]: { kind: "remove", reason: "Duplicate" }, [b]: { kind: "keep" } });
    act(() => again.result.current.restoreDraft?.());
    expect(again.result.current.state.decisions[a]).toEqual({ kind: "remove", reason: "Duplicate" });
  });

  it("a signed review offers no draft and removes it", () => {
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    first.unmount();
    const signed = open("run-1", rows, true);
    expect(signed.result.current.pendingRestore).toBeNull();
    act(() => signed.result.current.restoreDraft?.());
    expect(signed.result.current.state.decisions).toEqual({});
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).toBeNull();
  });

  it("forget takes a decision off the screen, the unsaved list and the draft", () => {
    const { result } = open("run-1");
    act(() => result.current.keep(a));
    act(() => result.current.keep(b));
    act(() => result.current.forget?.([a]));
    expect(result.current.state.decisions).toEqual({ [b]: { kind: "keep" } });
    expect(result.current.unsaved).toEqual([b]);
    expect(Object.keys(JSON.parse(sessionStorage.getItem(draftStorageKey("run-1")) ?? "{}").decisions)).toEqual([b]);
  });

  it("a save clears the draft", () => {
    const { result } = open("run-1");
    act(() => result.current.keep(a));
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).not.toBeNull();
    act(() => result.current.markSaved([a]));
    expect(result.current.unsaved).toEqual([]);
    expect(sessionStorage.getItem(draftStorageKey("run-1"))).toBeNull();
  });

  it("is kept per review and per person: another review or another person never gets it", () => {
    setDraftOwner("user-a");
    const first = open("run-1");
    act(() => first.result.current.keep(a));
    first.unmount();
    expect(open("run-2").result.current.pendingRestore).toBeNull();
    setDraftOwner("user-b");
    expect(open("run-1").result.current.pendingRestore).toBeNull();
    setDraftOwner("user-a");
    expect(open("run-1").result.current.pendingRestore).toEqual({ count: 1 });
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

  it("keepOnlyDraftsOf removes every other person's drafts and keeps that person's and anything else", () => {
    sessionStorage.setItem(draftStorageKey("run-1", "user-a"), "{}");
    sessionStorage.setItem(draftStorageKey("run-1", "user-b"), "{}");
    sessionStorage.setItem(draftStorageKey("run-2", null), "{}");
    sessionStorage.setItem("something.else", "x");
    keepOnlyDraftsOf("user-b");
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-a"))).toBeNull();
    expect(sessionStorage.getItem(draftStorageKey("run-2", null))).toBeNull();
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-b"))).toBe("{}");
    expect(sessionStorage.getItem("something.else")).toBe("x");
  });

  it("the old screen (no review id) keeps no draft at all", () => {
    const { result } = renderHook(() => useCrsDecisions());
    act(() => result.current.keep(a));
    expect(sessionStorage.length).toBe(0);
    expect(result.current.pendingRestore).toBeNull();
  });

  it("junk in storage is ignored, an entry with no stamp is dropped, and blocked storage never breaks deciding", () => {
    sessionStorage.setItem(draftStorageKey("run-1"), JSON.stringify({ decisions: { [a]: { kind: "remove", reason: "made up" }, [b]: { kind: "keep" } } }));
    const old = open("run-1");
    expect(old.result.current.pendingRestore).toEqual({ count: 1 });
    act(() => old.result.current.restoreDraft?.());
    expect(old.result.current.state.decisions).toEqual({});
    expect(old.result.current.restoreDropped).toBe(1);
    sessionStorage.setItem(draftStorageKey("run-1"), "not json");
    expect(open("run-1").result.current.pendingRestore).toBeNull();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const { result } = open("run-3");
    act(() => result.current.keep(a));
    expect(result.current.unsaved).toEqual([a]);
  });

  it("the review id can come from the app's CrsDraftContext", () => {
    const wrapper = ({ children }: { children: ReactNode }) => createElement(CrsDraftContext.Provider, { value: "run-ctx" }, children);
    const { result } = renderHook(() => useCrsDecisions(), { wrapper });
    act(() => result.current.observeRecord?.(rows, false));
    act(() => result.current.keep(a));
    expect(JSON.parse(sessionStorage.getItem(draftStorageKey("run-ctx")) ?? "{}").decisions).toEqual({ [a]: { kind: "keep" } });
  });
});
