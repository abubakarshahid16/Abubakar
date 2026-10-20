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
import { COULD_NOT_REFRESH, REVIEW_NOT_FOUND, newerReviewOf, useWorkspaceRun } from "./useWorkspaceRun";

const reviewRun = vi.fn();
const list = vi.fn();
const reviewRunStandards = vi.fn();
const reviewRunSummary = vi.fn();
const readiness = vi.fn();
const documentRead = vi.fn();
const reviewRuns = vi.fn();

vi.mock("../../../api/client", () => ({
  api: { document: (...a: unknown[]) => documentRead(...a) },
  reviews: {
    reviewRun: (...a: unknown[]) => reviewRun(...a),
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
    reviewRunSummary: (...a: unknown[]) => reviewRunSummary(...a),
    readiness: (...a: unknown[]) => readiness(...a),
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
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
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run()] } });
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

  it("carries the server's held-for-the-engineer note, and null when the key is absent", async () => {
    const held = { count: 1, standard_document_ids: ["std-1"], sentence: "Invented held sentence." };
    reviewRunStandards.mockResolvedValue({
      ok: true, data: { standards: [{ standard_document_id: "std-1", filename: "API 610.pdf" }], missing_references: [], held_for_engineer: held },
    });
    const withNote = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(withNote.result.current.load.kind).toBe("ready"));
    expect(withNote.result.current.standardsState.held?.sentence).toBe("Invented held sentence.");
    reviewRunStandards.mockResolvedValue({
      ok: true, data: { standards: [{ standard_document_id: "std-1", filename: "API 610.pdf" }], missing_references: [] },
    });
    const bare = renderHook(() => useWorkspaceRun("run-2"));
    await waitFor(() => expect(bare.result.current.load.kind).toBe("ready"));
    expect(bare.result.current.standardsState.held).toBeNull();
  });

  it("a run that cannot be found is an error in plain words", async () => {
    reviewRun.mockResolvedValue({ ok: true, data: null });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load).toEqual({ kind: "error", message: REVIEW_NOT_FOUND }));
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

  /** Order 139 part 2: the rows are the server's grouping; one failed
   *  summary read must not flip them to one row per finding (new keys) under
   *  the engineer's open decisions.
   *  MUTATION PROOF: set the summary to null on a failed read again and this fails. */
  it("a failed summary refresh keeps the last grouping", async () => {
    reviewRunSummary.mockResolvedValue({
      ok: true,
      data: {
        review_run_id: "run-1", crs_grouping: true,
        rows: ["a", "b"].map((finding_id) => ({ finding_id, tier: "B", label: "Comment", crs_group: "field:x", crs_order: 0 })),
      },
    });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.rows.map((r) => r.key)).toEqual(["crs:field:x"]));
    reviewRunSummary.mockResolvedValueOnce({ ok: false, error: { message: "Cannot reach the backend." } });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.rows.map((r) => r.key)).toEqual(["crs:field:x"]);
    expect(result.current.summary?.crs_grouping).toBe(true);
  });

  /** Release 1b: the kept grouping is not quietly passed off as current.
   *  MUTATION PROOF: never set `groupingStale` (or set it on a first failed
   *  read) and this fails. */
  it("a failed summary refresh after a good one says the grouping is the last one read, until a read succeeds", async () => {
    const good = {
      ok: true,
      data: {
        review_run_id: "run-1", crs_grouping: true,
        rows: ["a", "b"].map((finding_id) => ({ finding_id, tier: "B", label: "Comment", crs_group: "field:x", crs_order: 0 })),
      },
    };
    reviewRunSummary.mockResolvedValue(good);
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.rows.map((r) => r.key)).toEqual(["crs:field:x"]));
    expect(result.current.groupingStale).toBe(false);
    reviewRunSummary.mockResolvedValueOnce({ ok: false, error: { message: "Cannot reach the backend." } });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.rows.map((r) => r.key)).toEqual(["crs:field:x"]);
    expect(result.current.groupingStale).toBe(true);
    await act(async () => { await result.current.refresh(); });
    expect(result.current.groupingStale).toBe(false);
  });

  it("a summary that never answered is not 'stale': the one-row-per-finding note already says it", async () => {
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load).toEqual({ kind: "ready" }));
    await act(async () => { await result.current.refresh(); });
    expect(result.current.summary).toBeNull();
    expect(result.current.groupingStale).toBe(false);
  });

  it("a failed first load is still an error (nothing good to keep)", async () => {
    reviewRun.mockResolvedValue({ ok: false, error: { message: "Cannot reach the backend." } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("error"));
    expect(result.current.refreshError).toBeNull();
  });
});

/** v2.1 N2: a failed read is said in plain words first; the server's own
 *  words follow only as a detail, never alone.
 *  MUTATION PROOF: put `runs.error.message` back as the load message and the
 *  first test fails (the message starts with the raw text). */
describe("useWorkspaceRun: errors in plain words (v2.1 N2)", () => {
  it("a failed first load starts with a plain sentence and keeps the server's words as a detail", async () => {
    reviewRun.mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "Cannot reach the backend. ECONNREFUSED" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("error"));
    const message = result.current.load.kind === "error" ? result.current.load.message : "";
    expect(message.startsWith("Could not open this review. The server could not be reached.")).toBe(true);
    expect(message).toContain("Details: Cannot reach the backend. ECONNREFUSED");
  });

  it("a signed-out answer says to sign in again", async () => {
    list.mockResolvedValue({ ok: false, disconnected: false, error: { code: "unauthenticated", message: "token expired" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("error"));
    expect(result.current.load).toEqual({
      kind: "error", message: "Could not open this review. Your sign-in has ended. Sign in again to carry on. Details: token expired",
    });
  });

  it("a failed standards read is a plain sentence too", async () => {
    reviewRunStandards.mockResolvedValue({ ok: false, disconnected: false, error: { code: "internal", message: "HTTP 500" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("ready"));
    expect(result.current.standardsState.error).toBe(
      "Could not read the list of standards for this review. Try again in a moment. Details: HTTP 500");
  });

  it("the not-found words name no internal term", () => {
    expect(REVIEW_NOT_FOUND).not.toMatch(/\brun\b/i);
  });

  /** Round 2 item 4. MUTATION PROOF: drop the runs read (or compare the
   *  wrong way round in newerReviewOf) and this fails. */
  it("reads the document's reviews once and names a newer one", async () => {
    const newer = run({ review_run_id: "run-2", created_at: "2026-10-17T08:00:00Z" });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [newer, run()] } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.newerRun?.review_run_id).toBe("run-2"));
    expect(reviewRuns).toHaveBeenCalledTimes(1);
    expect(reviewRuns).toHaveBeenCalledWith("doc-sub");
    expect(result.current.documentRuns).toHaveLength(2);
  });

  it("a failed runs read says nothing about a newer review", async () => {
    reviewRuns.mockResolvedValue({ ok: false, error: { message: "nope" } });
    const { result } = renderHook(() => useWorkspaceRun("run-1"));
    await waitFor(() => expect(result.current.load.kind).toBe("ready"));
    await waitFor(() => expect(reviewRuns).toHaveBeenCalled());
    expect(result.current.newerRun).toBeNull();
    expect(result.current.documentRuns).toBeNull();
  });

  it("newerReviewOf: only a later review of the same document that did not fail or get cancelled", () => {
    const me = run();
    const older = run({ review_run_id: "run-0", created_at: "2026-10-01T08:00:00Z" });
    const failed = run({ review_run_id: "run-f", created_at: "2026-10-18T08:00:00Z", status: "failed" });
    const cancelled = run({ review_run_id: "run-c", created_at: "2026-10-18T09:00:00Z", status: "cancelled" });
    const other = run({ review_run_id: "run-o", created_at: "2026-10-18T09:00:00Z", submittal_document_id: "doc-other" });
    expect(newerReviewOf(me, [me, older, failed, cancelled, other])).toBeNull();
    const a = run({ review_run_id: "run-a", created_at: "2026-10-16T08:00:00Z" });
    const b = run({ review_run_id: "run-b", created_at: "2026-10-17T08:00:00Z", status: "running" });
    expect(newerReviewOf(me, [a, me, b])?.review_run_id).toBe("run-b");
  });
});
