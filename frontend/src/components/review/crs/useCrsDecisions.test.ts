/**
 * Order 95 piece 2: Accept all and its one-step undo.
 *
 * MUTATION PROOF: let Undo restore the whole earlier state and "undo clears
 * only what Accept all set" fails (it would also wipe a decision taken in
 * between); keep the undo after another decision and "any other decision
 * drops the undo" fails.
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { buildCrsRows } from "./crsRows";
import { EMPTY_FACTS } from "./tiers";
import { useCrsDecisions } from "./useCrsDecisions";

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
