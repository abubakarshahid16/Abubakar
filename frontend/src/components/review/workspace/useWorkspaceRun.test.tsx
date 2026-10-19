/**
 * Builder A: the workspace's data hook on made-up data.
 *
 * MUTATION PROOF: drop the `mine !== latest.current` check after readiness and
 * "newest load wins" fails; drop the poll and "polls while running" fails;
 * set readiness to an empty object on failure and "a failed readiness is
 * unknown" fails.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { COULD_NOT_REFRESH, useWorkspaceRun } from "./useWorkspaceRun";

const reviewRun = vi.fn();
const list = vi.fn();
const reviewRunStandards = vi.fn();
const reviewRunSummary = vi.fn();
const readiness = vi.fn();
const documentRead = vi.fn();

vi.mock("../../../api/client", () => ({
  api: { document: (...a: unknown[]) => documentRead(...a) },
  reviews: {
    reviewRun: (...a: unknown[]) => reviewRun(...a),
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
    reviewRunSummary: (...a: unknown[]) => reviewRunSummary(...a),
    readiness: (...a: unknown[]) => readiness(...a),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "Pump datasheet rev B.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-15T08:00:00Z", completed_at: "2026-10-15T08:18:00Z",
    standards_in_scope: 1, findings_total: 2, by_status: {}, recommended_code: null, recommended_reason: null,
    page_coverage: { pages_total: 12, fact_pages: [1, 2, 3], pages_not_read_into_fields: [4], not_read_reasons: {} },
    engineer_final_code: null, ...over,
  } as ReviewRunSummary;
}

function finding(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: 1, approval_status: "pending",
    standard_document_id: "std-1", standard_clause: "4.1", ...over,
  } as ReviewFinding;
}

const READY = {
  submittal_document_id: "doc-sub", pages_total: 12, pages_read: 11, unread_pages: [9],
  unread_page_reasons: { 9: "scanned" }, standards_cited: 1, standards_held: [], standards_missing: ["API 610"],
  last_run_id: "run-1", nothing_changed: true, changes: [],
};

beforeEach(() => {
  reviewRun.mockResolvedValue({ ok: true, data: run() });
  list.mockResolvedValue({ ok: true, data: { findings: [finding("a"), finding("b", { contractor_page: 3 })] } });
  reviewRunStandards.mockResolvedValue({
    ok: true, data: { standards: [{ standard_document_id: "std-1", filename: "API 610.pdf" }], missing_references: [] },
  });
  reviewRunSummary.mockResolvedValue({ ok: false, error: { message: "not found" } });
  readiness.mockResolvedValue({ ok: true, data: READY });
  documentRead.mockResolvedValue({ ok: true, data: { id: "doc-sub", filename: "Pump datasheet rev B.pdf" } });
});

afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

describe("useWorkspaceRun", () => {
  it("makes the sheet's reads plus readiness, and builds the rows", async () => {
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    expect(result.current.load).toEqual({ kind: "loading" });
    await waitFor(() => expect(result.current.readiness).not.toBeNull());
    expect(result.current.load).toEqual({ kind: "ready" });
    expect(result.current.run?.review_run_id).toBe("run-1");
    expect(result.current.findings).toHaveLength(2);
    expect(result.current.rows.length).toBeGreaterThan(0);
    expect(result.current.standardNames.get("std-1")).toBe("API 610.pdf");
    expect(result.current.summary).toBeNull();
    expect(result.current.readiness?.unread_pages).toEqual([9]);
    expect(readiness).toHaveBeenCalledWith("doc-sub");
    expect(list).toHaveBeenCalledWith({ review_run_id: "run-1" });
    await waitFor(() => expect(result.current.submittal?.id).toBe("doc-sub"));
    expect(result.current.active).toBe(false);
  });

  it("a failed readiness is unknown (null), never an empty list", async () => {
    readiness.mockResolvedValue({ ok: false, error: { message: "nope" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("ready"));
    await waitFor(() => expect(readiness).toHaveBeenCalled());
    expect(result.current.readiness).toBeNull();
  });

  it("a failed standards read is unknown (null missing ids), never an empty list", async () => {
    reviewRunStandards.mockResolvedValue({ ok: false, error: { message: "nope" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("ready"));
    expect(result.current.missingStandardIds).toBeNull();
  });

  it("a standards read that answered gives the missing ids (empty when none)", async () => {
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("ready"));
    expect(result.current.missingStandardIds).toEqual([]);
  });

  it("a run that cannot be found is an error in plain words", async () => {
    reviewRun.mockResolvedValue({ ok: true, data: null });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load).toEqual({ kind: "error", message: "This review run could not be found." }));
  });

  it("newest load wins: an older, slower answer never paints over a newer one", async () => {
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.readiness).not.toBeNull());
    let releaseSlow: (v: unknown) => void = () => {};
    readiness.mockImplementationOnce(() => new Promise((resolve) => { releaseSlow = resolve; }));
    readiness.mockResolvedValueOnce({ ok: true, data: { ...READY, unread_pages: [2, 5] } });
    let first: Promise<void> = Promise.resolve();
    await act(async () => {
      first = result.current.refresh();
      await Promise.resolve();
    });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.readiness?.unread_pages).toEqual([2, 5]);
    await act(async () => { releaseSlow({ ok: true, data: { ...READY, unread_pages: [99] } }); await first; });
    expect(result.current.readiness?.unread_pages).toEqual([2, 5]);
  });

  it("polls every 3 seconds while the run is running, and stops when it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reviewRun.mockResolvedValue({ ok: true, data: run({ status: "running" }) });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.active).toBe(true));
    const before = reviewRun.mock.calls.length;
    reviewRun.mockResolvedValue({ ok: true, data: run({ status: "completed" }) });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    await waitFor(() => expect(result.current.active).toBe(false));
    expect(reviewRun.mock.calls.length).toBe(before + 1);
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(reviewRun.mock.calls.length).toBe(before + 1);
  });

  /** One failed poll keeps the last good data and says it could not
   *  refresh, instead of replacing the screen with an error.
   *  MUTATION PROOF: set the load to an error on every failed read again and
   *  this fails. */
  it("a failed refresh after a good load keeps the data and says it could not refresh", async () => {
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.readiness).not.toBeNull());
    expect(result.current.refreshError).toBeNull();
    reviewRun.mockResolvedValueOnce({ ok: false, error: { message: "Cannot reach the backend." } });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.load).toEqual({ kind: "ready" });
    expect(result.current.run?.review_run_id).toBe("run-1");
    expect(result.current.findings).toHaveLength(2);
    expect(result.current.refreshError).toBe(COULD_NOT_REFRESH);
    // A failed findings read is the same.
    list.mockResolvedValueOnce({ ok: false, error: { message: "nope" } });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.findings).toHaveLength(2);
    expect(result.current.refreshError).toBe(COULD_NOT_REFRESH);
    // The next good read clears the line.
    await act(async () => { await result.current.refresh(); });
    expect(result.current.refreshError).toBeNull();
  });

  it("a failed first load is still an error (nothing good to keep)", async () => {
    reviewRun.mockResolvedValue({ ok: false, error: { message: "Cannot reach the backend." } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load).toEqual({ kind: "error", message: "Cannot reach the backend." }));
    expect(result.current.refreshError).toBeNull();
  });
});
