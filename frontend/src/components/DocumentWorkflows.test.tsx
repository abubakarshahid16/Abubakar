/**
 * One test per visible Phase 2 workflow.
 *
 * Every one of these asserts a USER-OBSERVABLE outcome - what is on screen, or
 * what was sent to the server - rather than that a component rendered. A test
 * that only asserts "the form exists" passes with the feature deleted.
 *
 * Mutation-proven: M21-M26 in `scripts/mutation_check.py`. Each names the line
 * whose deletion must fail the test.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DocumentFilters, EMPTY_FILTERS } from "./classification/DocumentFilters";
import type { DocumentFilterState } from "./classification/DocumentFilters";
import { MetadataEditor } from "./classification/MetadataEditor";
import { DocumentPreview } from "./DocumentPreview";
import { DocumentTechnicalDetails } from "./DocumentTechnicalDetails";
import type { DocumentClassification, DocumentRecord } from "../types/api";

const doc: DocumentRecord = {
  id: "doc_1", filename: "pump-datasheet.pdf", sha256: "a".repeat(64),
  size_bytes: 10, page_count: 4, pages_done: 4, chunk_count: 3,
  chunk_count_total: 5, disciplines: ["Mechanical"], embedded_count: 3,
  status: "ready", needs_ocr_pages: 0, recognised_pages: 0, equation_pages: 0,
  error: null, uploaded_at: "2026-09-18T00:00:00Z", indexed_at: null,
};

const classified: DocumentClassification = {
  document_id: "doc_1", doc_type: null, discipline: null, doc_class: null,
  register_id: null, suggested_by: "none", confirmed_by: null,
  confirmed_at: null, confirmed: false, subjects: [],
  document_role: null, title: null, equipment_tags: [],
};

// ---------------------------------------------------------------- 1. metadata

describe("editing metadata", () => {
  it("sends every field, with blanks cleared to null", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      sent.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify(classified), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));
    render(<MetadataEditor documentId="doc_1" record={classified} canEdit />);
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Pump datasheet" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save metadata/i }));
    await waitFor(() => expect(sent.length).toBe(1));
    const body = sent[0] as Record<string, unknown>;
    expect(body.title).toBe("Pump datasheet");
    // A field left blank is CLEARED, not omitted - otherwise an administrator
    // cannot remove a value they no longer believe.
    expect(body.revision).toBeNull();
    expect(body.project).toBeNull();
  });

  it("does not offer the controls to a non-admin", () => {
    render(<MetadataEditor documentId="doc_1" record={classified} canEdit={false} />);
    expect(screen.queryByRole("button", { name: /save metadata/i })).toBeNull();
  });
});

// ------------------------------------------------------------ 2. assign role

describe("assigning a document role", () => {
  it("sends the role the engineer chose, by its contract value", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      sent.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify(classified), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));
    render(<MetadataEditor documentId="doc_1" record={classified} canEdit />);
    fireEvent.change(screen.getByLabelText("Document role"), {
      target: { value: "COMPANY_STANDARD" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save metadata/i }));
    await waitFor(() => expect(sent.length).toBe(1));
    // The CONTRACT value, not the human label. A label sent here would be
    // refused by the backend vocabulary and match no filter.
    expect((sent[0] as Record<string, unknown>).document_role).toBe("COMPANY_STANDARD");
  });

  it("offers all five roles and a way to record none", () => {
    render(<MetadataEditor documentId="doc_1" record={classified} canEdit />);
    const select = screen.getByLabelText("Document role") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual([
      "", "CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT",
      "SUPPORTING_DOCUMENT", "CRS_TEMPLATE",
    ]);
  });
});

// ---------------------------------------------------------------- 3. filters

describe("filtering documents", () => {
  it("reports the chosen role to its caller so the SERVER can filter", () => {
    let state: DocumentFilterState = EMPTY_FILTERS;
    const onChange = vi.fn((next: DocumentFilterState) => { state = next; });
    render(<DocumentFilters value={state} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Company standard" }));
    expect(onChange).toHaveBeenCalled();
    expect(state.document_role).toEqual(["COMPANY_STANDARD"]);
  });

  it("toggles a role off when it is pressed again", () => {
    let state: DocumentFilterState = { ...EMPTY_FILTERS, document_role: ["COMPANY_STANDARD"] };
    render(
      <DocumentFilters
        value={state}
        onChange={(next) => { state = next; }}
      />,
    );
    const button = screen.getByRole("button", { name: "Company standard" });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(state.document_role).toEqual([]);
  });

  it("keeps the axes independent so they can AND together", () => {
    let state: DocumentFilterState = { ...EMPTY_FILTERS, document_role: ["CRS_TEMPLATE"] };
    render(
      <DocumentFilters
        value={state}
        projects={["Alpha"]}
        onChange={(next) => { state = next; }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "Alpha" } });
    expect(state.document_role).toEqual(["CRS_TEMPLATE"]);
    expect(state.project).toEqual(["Alpha"]);
  });
});

// ------------------------------------------------------- 4/5. preview

describe("previewing a document", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("fetches a PDF with the bearer header and never as a bare URL", async () => {
    const calls: Array<{ url: string; headers: Headers }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), headers: new Headers(init?.headers) });
      return new Response(new Blob([new Uint8Array([37, 80, 68, 70])]), { status: 200 });
    }));
    const { setToken } = await import("../api/client");
    setToken("tok-1");
    render(<DocumentPreview doc={doc} />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[0].url).toContain("/documents/doc_1/original");
    expect(calls[0].headers.get("Authorization")).toBe("Bearer tok-1");
    // The token must never reach the URL: it lands in history and proxy logs.
    expect(calls[0].url).not.toContain("tok-1");
    await screen.findByTitle("Preview of pump-datasheet.pdf");
  });

  it("shows a workbook as sheets of populated cells, read-only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({
        sheets: [
          { name: "CRS", rows: [["Item", "Value"], ["Design pressure", "10 bar"]] },
          { name: "Notes", rows: [] },
        ],
        truncated: false,
      }), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<DocumentPreview doc={{ ...doc, filename: "crs-template.xlsx" }} />);
    await screen.findByRole("tab", { name: "CRS" });
    expect(await screen.findByText("Design pressure")).toBeTruthy();
    expect(screen.getByText(/read-only preview/i)).toBeTruthy();
  });

  it("switches sheets when another tab is chosen", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({
        sheets: [
          { name: "CRS", rows: [["only on CRS"]] },
          { name: "Notes", rows: [["only on Notes"]] },
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<DocumentPreview doc={{ ...doc, filename: "crs-template.xlsx" }} />);
    await screen.findByText("only on CRS");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(await screen.findByText("only on Notes")).toBeTruthy();
    expect(screen.queryByText("only on CRS")).toBeNull();
  });

  it("says when a workbook preview is not the whole sheet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({
        sheets: [{ name: "Big", rows: [["a"]], truncated: true }], truncated: true,
      }), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<DocumentPreview doc={{ ...doc, filename: "big.xlsx" }} />);
    expect(await screen.findByRole("status")).toBeTruthy();
  });
});

// ------------------------------------------------- 6. technical details

describe("technical details", () => {
  it("renders nothing at all for a field that is not recorded", () => {
    render(<DocumentTechnicalDetails doc={doc} />);
    // Null is nothing: never "Unknown", never 0, never a dash that reads as a
    // recorded value.
    expect(screen.queryByText("Unknown")).toBeNull();
    expect(screen.queryByText("Revision")).toBeNull();
    expect(screen.getByText(/no submittal-review metadata/i)).toBeTruthy();
  });

  it("shows the metadata that IS recorded", () => {
    render(<DocumentTechnicalDetails doc={{
      ...doc, document_role: "COMPANY_STANDARD", revision: "B", project: "Alpha",
    }} />);
    expect(screen.getByText("Company standard")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("Alpha")).toBeTruthy();
  });

  it("states both chunk counts together, never one alone", () => {
    render(<DocumentTechnicalDetails doc={doc} />);
    expect(screen.getByText("3 / 5")).toBeTruthy();
  });

  it("says a document has not been reviewed rather than leaving it blank", () => {
    render(<DocumentTechnicalDetails doc={doc} />);
    expect(screen.getByText("Not reviewed")).toBeTruthy();
  });

  it("explains why a stored workbook is not searchable", () => {
    render(<DocumentTechnicalDetails doc={{ ...doc, status: "stored_not_indexed" }} />);
    expect(screen.getByText(/not searchable/i)).toBeTruthy();
  });

  it("warns that a superseded document should not be quoted", () => {
    render(<DocumentTechnicalDetails doc={{ ...doc, superseded_by: "doc_2" }} />);
    expect(screen.getByText(/superseded/i)).toBeTruthy();
  });
});
