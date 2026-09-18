/**
 * A citation opens the exact document AND the exact page.
 *
 * Master-plan section 8: "Every citation in Chat, Analysis, Submittal Review
 * and Reports must open the exact document and page." The viewer used to open
 * at page 1 always, so following a citation to page 214 of a specification
 * landed the reader on the cover sheet - a citation that does not open its own
 * page is not a citation, it is a filename.
 *
 * The page image is fetched WITH THE BEARER HEADER (`useAuthedImage`) and
 * rendered from an object URL, never as a bare `<img src>` pointing at the
 * API: a bare src carries no Authorization and is a guaranteed 404 under
 * auth_mode=demo_required.
 *
 * Mutation-proven: M21 in `scripts/mutation_check.py`.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { PageImageViewer } from "./PageImageViewer";
import type { DocumentRecord } from "../types/api";

const doc: DocumentRecord = {
  id: "doc_spec", filename: "specification.pdf", sha256: "b".repeat(64),
  size_bytes: 10, page_count: 300, pages_done: 300, chunk_count: 20,
  chunk_count_total: 20, disciplines: ["Mechanical"], embedded_count: 20,
  status: "ready", needs_ocr_pages: 0, recognised_pages: 0, equation_pages: 0,
  error: null, uploaded_at: "2026-09-18T00:00:00Z", indexed_at: null,
};

const imageRequests: string[] = [];

beforeEach(() => {
  imageRequests.length = 0;
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:page"),
    revokeObjectURL: vi.fn(),
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const href = String(url);
    if (href.includes("/image")) {
      imageRequests.push(href);
      return new Response(new Blob([new Uint8Array([137, 80, 78, 71])]), { status: 200 });
    }
    return new Response(JSON.stringify({
      pages: Array.from({ length: 3 }, (_, i) => ({
        page_no: 212 + i, has_text: true, text_length: 100,
        needs_ocr: false, equation_heavy: false,
      })),
      total: 3, limit: 100, offset: 0,
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});

describe("citation to page", () => {
  it("opens at the cited page, not at page 1", async () => {
    render(<PageImageViewer doc={doc} initialPage={214} onClose={() => {}} />);
    await waitFor(() => expect(imageRequests.length).toBeGreaterThan(0));
    // The page the citation named, requested from the server.
    expect(imageRequests[0]).toContain("/pages/214/image");
    expect(imageRequests[0]).not.toContain("/pages/1/image");
  });

  it("opens at page 1 when a citation names no page", async () => {
    render(<PageImageViewer doc={doc} onClose={() => {}} />);
    await waitFor(() => expect(imageRequests.length).toBeGreaterThan(0));
    expect(imageRequests[0]).toContain("/pages/1/image");
  });

  it("never renders a page below 1 from a malformed citation", async () => {
    render(<PageImageViewer doc={doc} initialPage={0} onClose={() => {}} />);
    await waitFor(() => expect(imageRequests.length).toBeGreaterThan(0));
    expect(imageRequests[0]).toContain("/pages/1/image");
  });

  it("fetches the page image with the bearer header, not as a bare src", async () => {
    const { setToken } = await import("../api/client");
    setToken("tok-page");
    render(<PageImageViewer doc={doc} initialPage={214} onClose={() => {}} />);
    await waitFor(() => expect(imageRequests.length).toBeGreaterThan(0));
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    const imageCall = calls.find((c) => String(c[0]).includes("/image"));
    const headers = new Headers((imageCall?.[1] as RequestInit | undefined)?.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-page");
    // The rendered <img> must point at an object URL, never at the API path.
    const img = await screen.findByAltText(/Page 214 of specification.pdf/i);
    expect(img.getAttribute("src")).toBe("blob:page");
  });
});
