/**
 * Search, sort and filters read immediately, and a slow older answer can
 * never overwrite a newer one. Invented filenames only.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// The poll makes only the initial read here, so any further request in these
// tests is caused by the query change itself, not by a poll tick.
vi.mock("../hooks/usePoll", async () => {
  const { useEffect } = await import("react");
  return {
    usePoll: (tick: () => void) => {
      // eslint-disable-next-line react-hooks/rules-of-hooks
      useEffect(() => { tick(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    },
  };
});

import type { Health } from "../api/client";
import { DocumentsView } from "./DocumentsView";
import type { DocumentRecord } from "../types/api";

const health: Health = {
  ok: true, embed_model_present: true, answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const doc = (name: string): DocumentRecord => ({
  id: name, filename: name, sha256: name, size_bytes: 1, page_count: 1,
  pages_done: 1, chunk_count: 1, chunk_count_total: 1, disciplines: [],
  embedded_count: 1, status: "ready", needs_ocr_pages: 0, recognised_pages: 0,
  equation_pages: 0, error: null, uploaded_at: "2026-09-19T00:00:00Z",
  indexed_at: "2026-09-19T00:01:00Z",
}) as DocumentRecord;

const json = (body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status: 200, headers: { "Content-Type": "application/json", ...headers },
  });

let seen: URL[] = [];
let answer: (url: URL) => Promise<Response>;

beforeEach(() => {
  seen = [];
  answer = async () => json([doc("STD-A-001.pdf")], { "X-Total-Count": "1" });
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://x");
    const p = url.pathname;
    if (p.endsWith("/documents")) { seen.push(url); return answer(url); }
    if (p.includes("/metrics")) return Promise.resolve(json({ worker: null }));
    if (p.includes("/classification/vocabulary")) {
      return Promise.resolve(json({ register_revision: "r1", types: [], disciplines: [], subjects: [], needs_classification: 0 }));
    }
    if (p.includes("/classification/coverage")) {
      return Promise.resolve(json({ register_loaded: true, register_revision: "r1", by_type: [], by_discipline: [], by_subject: [], needs_classification: 0 }));
    }
    return Promise.resolve(json({}));
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function mount() {
  render(<DocumentsView connection={{ state: "online", health, at: Date.now() }}
    onRetryConnection={() => {}} polling={false} />);
}

it("reads with the new search text without waiting for a poll", async () => {
  mount();
  await screen.findByText("STD-A-001.pdf");
  fireEvent.change(screen.getByPlaceholderText(/Filename contains/), { target: { value: "pump" } });
  await waitFor(() => expect(seen.some((u) => u.searchParams.get("q") === "pump")).toBe(true));
});

it("reads with the new sort order without waiting for a poll", async () => {
  mount();
  await screen.findByText("STD-A-001.pdf");
  fireEvent.click(screen.getByRole("button", { name: /Order:/ }));
  await waitFor(() => expect(seen.some((u) => u.searchParams.get("direction") === "asc")).toBe(true));
});

it("a slow earlier answer does not overwrite a newer one", async () => {
  mount();
  await screen.findByText("STD-A-001.pdf");
  const gates: Record<string, (r: Response) => void> = {};
  answer = (url) => new Promise<Response>((resolve) => { gates[url.searchParams.get("q") ?? ""] = resolve; });

  const box = screen.getByPlaceholderText(/Filename contains/);
  fireEvent.change(box, { target: { value: "a" } });
  await waitFor(() => expect(gates["a"]).toBeDefined());
  fireEvent.change(box, { target: { value: "ab" } });
  await waitFor(() => expect(gates["ab"]).toBeDefined());

  // The NEWER query answers first, then the older one arrives late.
  await act(async () => { gates["ab"](json([doc("STD-NEW-002.pdf")], { "X-Total-Count": "1" })); });
  await screen.findByText("STD-NEW-002.pdf");
  await act(async () => { gates["a"](json([doc("STD-OLD-003.pdf")], { "X-Total-Count": "1" })); });

  expect(screen.getByText("STD-NEW-002.pdf")).toBeInTheDocument();
  expect(screen.queryByText("STD-OLD-003.pdf")).toBeNull();
});
