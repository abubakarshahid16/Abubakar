/**
 * Switching between standards must not show the previous one's data, and the
 * "Superseded by" select must follow the server after a change.
 *
 * Invented identifiers only (STD-A-001, STD-B-002).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { StandardsView } from "./StandardsView";
import type { StandardRequirement, StandardSummary } from "../types/api";

const std = (id: string, number: string): StandardSummary => ({
  id, filename: `${number}.pdf`, status: "ready", page_count: 5,
  uploaded_at: "2026-09-18T00:00:00Z", title: number,
  document_number: number, revision: "1", effective_date: null,
  discipline: null, superseded_by: null, superseded: false,
  requirement_count: 1, awaiting_verification: 0,
});

const req = (id: string, docId: string, text: string): StandardRequirement => ({
  id, standard_document_id: docId, clause: "1.1", page: 1, chunk_id: "c",
  requirement_text: text, source_text: text, category: null,
  extraction_method: "extracted", confidence: 0.9, confirmed_by: null,
  confirmed_at: null, needs_verification: false, citation_resolves: true,
  created_at: "2026-09-18T00:00:00Z", updated_at: "2026-09-18T00:00:00Z",
  requirement_type: null, field: null, operator: null, value: null, unit: null,
  raw_value: null, raw_unit: null, condition: null, exceptions: [],
  discipline: null, table_row: null,
});

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200, headers: { "Content-Type": "application/json" },
  });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("switching standards", () => {
  it("does not show standard A's requirements while B's are loading", async () => {
    const a = std("doc_a", "STD-A-001");
    const b = std("doc_b", "STD-B-002");
    let releaseB: () => void = () => {};
    const gateB = new Promise<void>((r) => { releaseB = r; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const href = String(url);
      if (href.includes("/standards/missing")) return json([]);
      if (href.includes("/doc_a/requirements")) return json([req("r1", "doc_a", "Requirement text of A")]);
      if (href.includes("/doc_b/requirements")) {
        await gateB;
        return json([req("r2", "doc_b", "Requirement text of B")]);
      }
      if (href.includes("/requirements") || href.includes("/revisions")
        || href.includes("/clauses")) return json([]);
      return json([a, b]);
    }));
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /STD-A-001/ }));
    expect(await screen.findByText("Requirement text of A")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /STD-B-002/ }));
    // B's list has not arrived: A's rows must be gone, not left on screen.
    expect(screen.queryByText("Requirement text of A")).toBeNull();
    releaseB();
    expect(await screen.findByText("Requirement text of B")).toBeTruthy();
  });

  it("keeps the Superseded by select on the server's answer after a change", async () => {
    const a = std("doc_a", "STD-A-001");
    const b = std("doc_b", "STD-B-002");
    let supersededBy: string | null = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const href = String(url);
      if (init?.method === "POST") {
        supersededBy = JSON.parse(String(init.body)).superseded_by;
        return json({ superseded_by: supersededBy });
      }
      if (href.includes("/standards/missing")) return json([]);
      if (href.includes("/revisions")) return json([{ ...a, superseded_by: supersededBy }, b]);
      if (href.includes("/requirements") || href.includes("/clauses")) return json([]);
      return json([{ ...a, superseded_by: supersededBy }, b]);
    }));
    render(<StandardsView isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /STD-A-001/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Revision History" }));
    const select = await screen.findByLabelText("Superseded by");
    fireEvent.change(select, { target: { value: "doc_b" } });
    await waitFor(() => expect(supersededBy).toBe("doc_b"));
    await waitFor(() =>
      expect((screen.getByLabelText("Superseded by") as HTMLSelectElement).value)
        .toBe("doc_b"));
  });
});
