/**
 * V1b: the server answers the findings and runs lists in pages (default 200 / 100). A screen that needs every row asks page
 * after page and joins them, so no row is lost; a page-only caller gets the total.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { reviews } from "./client";

function serve(total: number, key: "findings" | "runs") {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(String(url));
    const q = new URL(String(url), "http://x").searchParams;
    const offset = Number(q.get("offset") ?? 0);
    const limit = Number(q.get("limit") ?? 100);
    const rows = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => ({ id: `r${offset + i}` }));
    return new Response(JSON.stringify({ [key]: rows, total, limit, offset }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
  return calls;
}

describe("lists that need every row page through the server", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("findings: 1,200 rows arrive as three pages, joined, none lost", async () => {
    const calls = serve(1200, "findings");
    const r = await reviews.list({ review_run_id: "run-1" });
    expect(r.ok && r.data.findings).toHaveLength(1200);
    expect(calls).toHaveLength(3);
    expect(calls[0]).toContain("review_run_id=run-1");
    expect(calls.every((c) => c.includes("limit=500"))).toBe(true);
  });

  it("findings: an empty list is one call", async () => {
    const calls = serve(0, "findings");
    const r = await reviews.list();
    expect(r.ok && r.data.findings).toHaveLength(0);
    expect(calls).toHaveLength(1);
  });

  it("findings: a page-only caller gets the first page and the total", async () => {
    serve(1200, "findings");
    const r = await reviews.listPage(undefined, 0, 200);
    expect(r.ok && r.data.findings).toHaveLength(200);
    expect(r.ok && r.data.total).toBe(1200);
  });

  it("runs: 450 runs arrive as three pages of at most 200, joined", async () => {
    const calls = serve(450, "runs");
    const r = await reviews.reviewRuns("doc-1");
    expect(r.ok && r.data.runs).toHaveLength(450);
    expect(calls).toHaveLength(3);
    expect(calls[0]).toContain("document_id=doc-1");
  });
});
