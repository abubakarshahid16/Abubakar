/**
 * Order 141 D (review, order 144 item 1): Sign, and its confirm step, refuse
 * while a draft from an earlier visit is waiting for "Bring them back" or
 * "Discard". Issuing then would send the contractor a copy without those
 * decisions, and a signed review deletes the draft, so they would be lost
 * with nothing said. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): drop `draftWaiting` from useSignOff's
 * checks (or its line in `issueWaitsFor`) and both tests fail: the confirm
 * step opens, and the issue copy is downloaded.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsDecisions, CrsRow, ReviewNumbers } from "./contract";
import { issueConfirmed, useSignOff } from "./useSignOff";

const downloadCrs = vi.fn();
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../crs/saveCrsDecisions", () => ({ saveCrsDecisions: vi.fn() }));

/** Everything else is done: nothing unsaved, nothing to open, gate clear. */
const NUMBERS = { unopenedNeedsYou: 0, signLeft: [] } as unknown as ReviewNumbers;
const ROWS: CrsRow[] = [];

function decisions(pendingRestore: { count: number } | null): CrsDecisions {
  return {
    state: { decisions: {}, opened: {} }, unsaved: [], markSaved: vi.fn(), pendingRestore,
  } as unknown as CrsDecisions;
}

beforeEach(() => {
  downloadCrs.mockReset().mockResolvedValue(null);
});

describe("Sign waits for a draft from an earlier visit", () => {
  it("Sign says the draft's decisions are not on the record, and does not open the confirm step", async () => {
    const { result } = renderHook(() => useSignOff({
      runId: "run-1", rows: ROWS, decisions: decisions({ count: 2 }), refresh: async () => {}, numbers: NUMBERS,
    }));
    await act(async () => { await result.current.sign(); });
    expect(result.current.confirmOpen).toBe(false);
    expect(result.current.error).toBe(
      "2 decisions from an earlier visit are not on the record: bring them back or discard them first.");
  });

  it("the confirm step's Issue refuses too, and nothing is issued", async () => {
    renderHook(() => useSignOff({
      runId: "run-1", rows: ROWS, decisions: decisions({ count: 1 }), refresh: async () => {}, numbers: NUMBERS,
    }));
    let outcome: Awaited<ReturnType<typeof issueConfirmed>> | null = null;
    await act(async () => { outcome = await issueConfirmed("run-1"); });
    expect(outcome).toEqual({
      ok: false, message: "1 decision from an earlier visit is not on the record: bring it back or discard it first.",
    });
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("with no draft waiting, Sign opens the confirm step as before", async () => {
    const { result } = renderHook(() => useSignOff({
      runId: "run-1", rows: ROWS, decisions: decisions(null), refresh: async () => {}, numbers: NUMBERS,
    }));
    await act(async () => { await result.current.sign(); });
    expect(result.current.error).toBeNull();
    expect(result.current.confirmOpen).toBe(true);
  });
});
