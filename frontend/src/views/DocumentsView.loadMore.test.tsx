/**
 * "Load next 100" survives the background poll.
 *
 * The poll used to replace the list with the first page, so everything the
 * operator had loaded vanished every few seconds. Asserted against the
 * request log AND the screen: the second page must be re-read, and its
 * rows must still be shown after a poll tick.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Capture the poll callback so the test fires a tick itself instead of
// waiting out a real interval.
const poll = vi.hoisted(() => ({ tick: null as null | (() => void) }));
vi.mock("../hooks/usePoll", async () => {
  const { useEffect } = await import("react");
  return {
    usePoll: (tick: () => void) => {
      poll.tick = tick;
      // Initial read on mount, as the real hook does.
      // eslint-disable-next-line react-hooks/rules-of-hooks
      useEffect(() => { tick(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    },
  };
});

import type { Health } from "../api/client";
import { DocumentsView } from "./DocumentsView";
import type { DocumentRecord } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

function makeDoc(n: number): DocumentRecord {
  const id = `d${n}`;
  return {
    id, filename: `STD-A-${String(n).padStart(3, "0")}.pdf`, sha256: `sha-${id}`,
    size_bytes: 1000, page_count: 2, pages_done: 2, chunk_count: 2,
    chunk_count_total: 2, disciplines: [], embedded_count: 2, status: "ready",
    needs_ocr_pages: 0, recognised_pages: 0, equation_pages: 0, error: null,
    uploaded_at: "2026-09-19T00:00:00Z", indexed_at: "2026-09-19T00:01:00Z",
  } as DocumentRecord;
}

const ALL = Array.from({ length: 130 }, (_, i) => makeDoc(i + 1));
let offsets: number[] = [];

function json(body: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200, headers: { "Content-Type": "application/json", ...headers },
  }));
}

beforeEach(() => {
  offsets = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://x");
    const p = url.pathname;
    if (p.endsWith("/documents") || p.endsWith("/documents/")) {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 20);
      offsets.push(offset);
      return json(ALL.slice(offset, offset + limit), { "X-Total-Count": String(ALL.length) });
    }
    if (p.includes("/auth/me")) return json({ required: false, user: null });
    if (p.includes("/health")) return json(health);
    if (p.includes("/metrics")) return json({ worker: null });
    if (p.includes("/classification/vocabulary")) {
      return json({ register_revision: "r1", types: [], disciplines: [], subjects: [], needs_classification: 0 });
    }
    if (p.includes("/classification/coverage")) {
      return json({ register_loaded: true, register_revision: "r1", by_type: [], by_discipline: [], by_subject: [], needs_classification: 0 });
    }
    if (/\/documents\/[^/]+\/classification/.test(p)) return json({});
    return json({});
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("keeps the extra page the operator loaded after a poll tick", async () => {
  render(
    <DocumentsView
      connection={{ state: "online", health, at: Date.now() }}
      onRetryConnection={() => {}}
      polling={false}
    />,
  );
  await screen.findByText(/Showing 100 of 130 documents/);
  fireEvent.click(screen.getByRole("button", { name: "Load next 100" }));
  await screen.findByText("STD-A-130.pdf");
  expect(screen.queryByText(/Showing .* of 130/)).not.toBeInTheDocument();

  offsets = [];
  await act(async () => {
    poll.tick?.(); // one poll tick
  });

  // The poll re-read the second page, and the rows are still on screen.
  await waitFor(() => expect(offsets).toContain(100));
  expect(screen.getByText("STD-A-130.pdf")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Load next 100" })).not.toBeInTheDocument();
  // This test renders 130 rows twice (about 3.5s alone), so it needs its own budget
  // under a loaded full run; the default 5s timed out on the owner's PC, twice.
}, 20000);
