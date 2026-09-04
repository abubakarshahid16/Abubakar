/**
 * The presentation rules the backend got wrong repeatedly.
 * These are pure functions so the rules can be asserted directly.
 */
import { describe, expect, it } from "vitest";

import type { DocumentRecord } from "../types/api";
import {
  LOW_RETRIEVABLE_THRESHOLD,
  excludedCount,
  hasLowRetrievableRatio,
  presentStatus,
  progressLine,
  retrievableRatio,
} from "./documentStatus";

function doc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc_1",
    filename: "spec.pdf",
    sha256: "abc",
    size_bytes: 1000,
    page_count: 1204,
    pages_done: 1204,
    chunk_count: 2831,
    chunk_count_total: 2900,
    embedded_count: 2831,
    status: "ready",
    needs_ocr_pages: 0,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    uploaded_at: "2026-09-04T00:00:00Z",
    indexed_at: "2026-09-04T00:10:00Z",
    ...over,
  };
}

describe("status presentation", () => {
  it("never calls a document ready before embedding finishes", () => {
    const partial = presentStatus(doc({ status: "partially_searchable", embedded_count: 340 }));
    expect(partial.label).toBe("partially searchable");
    expect(partial.label).not.toContain("ready");
    expect(partial.tone).not.toBe("success");
    expect(partial.answerable).toBe(true); // answerable, but not ready
  });

  it("renders no_searchable_content as a warning, never a success", () => {
    const p = presentStatus(doc({ status: "no_searchable_content", chunk_count: 0 }));
    expect(p.tone).toBe("warning");
    expect(p.answerable).toBe(false);
    expect(p.label).toBe("no searchable content");
  });

  it("marks failure as danger and not answerable", () => {
    const p = presentStatus(doc({ status: "failed" }));
    expect(p.tone).toBe("danger");
    expect(p.answerable).toBe(false);
  });

  it("only ready is a success", () => {
    expect(presentStatus(doc({ status: "ready" })).tone).toBe("success");
    for (const s of ["queued", "extracting", "chunking", "indexing_keyword"] as const) {
      expect(presentStatus(doc({ status: s })).tone).not.toBe("success");
    }
  });
});

describe("progress line", () => {
  it("reads like the required summary while embedding is in flight", () => {
    const line = progressLine(
      doc({ status: "partially_searchable", embedded_count: 340, indexed_at: null }),
    );
    expect(line).toContain("1,204 pages");
    expect(line).toContain("2,831 sections");
    expect(line).toContain("keyword search ready");
    expect(line).toContain("340/2,831 embedded");
  });

  it("says nothing searchable when there is nothing searchable", () => {
    const line = progressLine(
      doc({ status: "no_searchable_content", chunk_count: 0, chunk_count_total: 12 }),
    );
    expect(line).toContain("nothing searchable");
    expect(line).not.toContain("keyword search ready");
  });

  it("does not claim keyword search before the index exists", () => {
    const line = progressLine(doc({ status: "extracting", chunk_count: 0, chunk_count_total: 0 }));
    expect(line).not.toContain("keyword search ready");
  });
});

describe("retrievable ratio warning", () => {
  it("flags a document where the gate excluded most of it", () => {
    const d = doc({ chunk_count: 400, chunk_count_total: 1000 }); // 40%
    expect(retrievableRatio(d)).toBeCloseTo(0.4);
    expect(hasLowRetrievableRatio(d)).toBe(true);
    expect(excludedCount(d)).toBe(600);
  });

  it("does not flag a healthy document", () => {
    expect(hasLowRetrievableRatio(doc({ chunk_count: 980, chunk_count_total: 1000 }))).toBe(false);
  });

  it("uses a 60% threshold", () => {
    expect(LOW_RETRIEVABLE_THRESHOLD).toBe(0.6);
    expect(hasLowRetrievableRatio(doc({ chunk_count: 59, chunk_count_total: 100 }))).toBe(true);
    expect(hasLowRetrievableRatio(doc({ chunk_count: 61, chunk_count_total: 100 }))).toBe(false);
  });

  it("does not flag a document with no chunks at all", () => {
    // that case is no_searchable_content, a different and louder message
    expect(hasLowRetrievableRatio(doc({ chunk_count: 0, chunk_count_total: 0 }))).toBe(false);
  });
});
