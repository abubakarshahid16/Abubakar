/**
 * Documents -> More -> "What was read" and "Left out" (H, 27 Nov 2026: the document's words were in monospace, the only mono on the
 * page). In the new look the document's own words use the app's reading face (.evidence-quote), a TABLE keeps its positional grid
 * (.document-table), and codes are the kit Tag. The classic look is unchanged. Invented values only.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NEW_LOOK } from "../look";

const chunk = (id: string, kind: "prose" | "table", text: string) => ({
  id, ordinal: 1, page_start: 2, page_end: 2, section: null, kind, token_count: 9, content_hash: "h", retrievable: true,
  quality_flags: null, text,
});
vi.mock("../api/client", () => ({
  api: {
    chunks: vi.fn(async () => ({ ok: true, data: { total_matching: 2, chunks: [
      chunk("chunk-a", "prose", "The pump shall be tested."),
      chunk("chunk-b", "table", "Item   Value\nFlow   10"),
    ] } })),
    excluded: vi.fn(async () => ({ ok: true, data: { total: 1, limit: 50, offset: 0,
      summary: [{ scope: "page", rule: "page_classified_toc", count: 1, characters_dropped: 40 }],
      excluded: [{ scope: "page", page_start: 1, page_end: 1, chunk_id: null, rule: "page_classified_toc", reason: null,
        text_length: 40, text_sample: "Contents 1 Scope 2 Duties" }] } })),
  },
}));

import { ChunkInspector } from "./ChunkInspector";
import { ExcludedViewer } from "./ExcludedViewer";

const doc = { id: "doc-1", filename: "Invented.pdf", chunk_count: 2, chunk_count_total: 2 } as never;
afterEach(() => cleanup());

describe("the document's words in the reader panels", () => {
  it("'What was read': prose in the reading face, a table in its grid, the reference a kit Tag, no mono", async () => {
    const { container } = render(<ChunkInspector doc={doc} onClose={() => undefined} />);
    const prose = (await screen.findByText("The pump shall be tested.")).closest("pre")!;
    const table = screen.getByText(/Item\s+Value/).closest("pre")!;
    if (NEW_LOOK) {
      expect(prose.className).toContain("evidence-quote");
      expect(table.className).toContain("document-table");
      expect(table.className).not.toContain("evidence-quote");
      expect(container.querySelectorAll(".font-mono")).toHaveLength(0);
      expect(screen.getByText("chunk-a").className).toBe("kit-tag");
    } else {
      expect(prose.className).toContain("font-mono");
    }
  });

  it("'Left out': the dropped words in the reading face, the rule a kit Tag, no mono", async () => {
    const { container } = render(<ExcludedViewer doc={doc} onClose={() => undefined} />);
    const sample = (await screen.findByText("Contents 1 Scope 2 Duties")).closest("pre")!;
    if (NEW_LOOK) {
      expect(sample.className).toContain("evidence-quote");
      expect(container.querySelectorAll(".font-mono")).toHaveLength(0);
      expect(screen.getAllByText("page_classified_toc").every((e) => e.className === "kit-tag")).toBe(true);
    } else {
      expect(sample.className).toContain("font-mono");
    }
  });
});
