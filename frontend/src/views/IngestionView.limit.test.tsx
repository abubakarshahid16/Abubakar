/**
 * The three Ingestion groups are counted over the documents the screen read.
 * It asks for the backend maximum and states the boundary when it was cut.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Health } from "../api/client";
import { IngestionView } from "./IngestionView";

const health: Health = {
  ok: true, embed_model_present: true, answer_model_configured: true,
  ingestion: { alive: true, stalled: false, busy: false },
};
const metrics = {
  at: "2026-09-04T12:00:00Z", refresh_seconds: 15, corpus_wide: false,
  corpus: {}, throughput: {},
  worker: { alive: true, current_document: null, seconds_since_heartbeat: 0, seconds_since_progress: 0,
    documents_completed: 0, pending_count: 0, oldest_pending_age_seconds: null, stalled: false,
    stalled_reasons: [], last_error: null },
};
const doc = (i: number) => ({
  id: `d${i}`, filename: `STD-A-${i}.pdf`, sha256: "x", size_bytes: 1, page_count: 1,
  pages_done: 1, chunk_count: 1, chunk_count_total: 1, disciplines: [], embedded_count: 1,
  status: "ready", needs_ocr_pages: 0, recognised_pages: 0, equation_pages: 0, error: null,
  uploaded_at: "2026-09-04T00:00:00Z", indexed_at: null,
});
const json = (body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json", ...headers } });

let docUrls: URL[] = [];
function stub(count: number, total: string | null) {
  docUrls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    if (url.pathname.endsWith("/documents")) {
      docUrls.push(url);
      return json(Array.from({ length: count }, (_, i) => doc(i)), total ? { "X-Total-Count": total } : {});
    }
    if (url.pathname.includes("/metrics")) return json(metrics);
    return json({ recent: [] });
  }));
}
const mount = () => render(<IngestionView connection={{ state: "online", health, at: Date.now() }} onRetryConnection={() => {}} />);

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Ingestion document list", () => {
  it("asks for 200 rows and states the cut when the total is larger", async () => {
    stub(200, "450");
    mount();
    expect(await screen.findByTestId("ingestion-boundary"))
      .toHaveTextContent("newest 200 of 450 documents you can open");
    expect(docUrls[0].searchParams.get("limit")).toBe("200");
  });

  it("states no cut when everything was read", async () => {
    stub(3, "3");
    mount();
    await screen.findByText("Fully indexed");
    expect(screen.queryByTestId("ingestion-boundary")).toBeNull();
  });
});
