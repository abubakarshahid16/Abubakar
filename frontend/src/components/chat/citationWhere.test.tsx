/**
 * W5b-01 (#525): a Word passage is cited by where it sits, a PDF passage by page.
 *
 * MUTATION PROOF (scripts/mutations/w5b_525_docx.py, M4121 to M4124): removing
 * the locator branch of `citationWhere`, the locator in `Citation`, the
 * locator in `SourcePreview`'s chip label or the page-image guard in
 * `EvidencePanel` each fails a test here.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Citation, EvidencePanel, PassageLocation } from "./EvidencePanel";
import { previewSources, SourceChips } from "./SourcePreview";
import { citationWhere, hasPrintedPage } from "./citationWhere";
import type { AnswerPassage, ChatSource } from "../../types/api";

const PDF: AnswerPassage = {
  chunk_id: "c1",
  document_id: "doc1",
  filename: "spec.pdf",
  page_start: 7,
  page_end: 7,
  section: null,
  text: "Vessels shall be tested.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 1,
  identifier_hits: [],
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
};

const WORD: AnswerPassage = {
  ...PDF,
  chunk_id: "c2",
  filename: "spec.docx",
  page_start: 1,
  page_end: 1,
  locator: "4 > 4.2 > para 3",
};

describe("citationWhere", () => {
  it("is the locator for a Word passage and the page for a PDF passage", () => {
    expect(citationWhere(WORD)).toBe("4 > 4.2 > para 3");
    expect(citationWhere(PDF)).toBe("page 7");
    expect(citationWhere({ ...PDF, page_end: 9 })).toBe("pages 7–9");
  });

  it("says a Word passage has no printed page", () => {
    expect(hasPrintedPage(WORD)).toBe(false);
    expect(hasPrintedPage(PDF)).toBe(true);
  });
});

describe("the citation line", () => {
  it("shows the heading path and paragraph instead of a page for a Word document", () => {
    const { container } = render(<Citation passage={WORD} />);
    expect(container.textContent).toContain("spec.docx");
    expect(container.textContent).toContain("4 > 4.2 > para 3");
    expect(container.textContent).not.toMatch(/page \d/i);
  });

  it("still shows the page for a PDF", () => {
    const { container } = render(<Citation passage={PDF} />);
    expect(container.textContent).toContain("page 7");
  });

  it("the list row says the same", () => {
    const { container } = render(<PassageLocation passage={WORD} />);
    expect(container.textContent).toContain("4 > 4.2 > para 3");
    expect(container.textContent).not.toMatch(/page \d/i);
  });
});

describe("the numbered source chip", () => {
  it("is labelled with the locator for a Word source and the page for a PDF source", () => {
    const meta: ChatSource[] = [
      { n: 1, kind: "document", document_id: "doc1", display_name: "spec.docx", document_number: null,
        page: 1, page_end: 1, clause: null, locator: "4 > 4.2 > para 3", text_source: "extracted",
        ocr_min_conf: null, url: null, cited: true, quotes: [], rows: [] },
      { n: 2, kind: "document", document_id: "doc2", display_name: "spec.pdf", document_number: null,
        page: 7, page_end: 7, clause: null, text_source: "extracted", ocr_min_conf: null, url: null,
        cited: true, quotes: [], rows: [] },
    ];
    render(<SourceChips sources={previewSources([WORD, PDF], meta)} open={null} onOpen={() => {}} />);
    expect(screen.getByText(/4 > 4\.2 > para 3/)).toBeTruthy();
    expect(screen.getByText(/p\.7/)).toBeTruthy();
  });
});

describe("the evidence panel", () => {
  it("shows the position of a Word passage and asks for no page image", () => {
    const requested: string[] = [];
    const fetchSpy = (url: unknown) => { requested.push(String(url)); return Promise.reject(new Error("no")); };
    const original = globalThis.fetch;
    globalThis.fetch = fetchSpy as typeof fetch;
    try {
      render(<EvidencePanel passages={[WORD]} selected={0} onSelect={() => {}} onClose={() => {}} />);
    } finally {
      globalThis.fetch = original;
    }
    expect(screen.getByText(/Position in the document/)).toBeTruthy();
    expect(screen.queryByText(/as printed/i)).toBeNull();
    expect(requested.filter((u) => u.includes("/pages/"))).toEqual([]);
  });

  it("still shows the printed page for a PDF", () => {
    const original = globalThis.fetch;
    globalThis.fetch = (() => Promise.reject(new Error("no"))) as typeof fetch;
    try {
      render(<EvidencePanel passages={[PDF]} selected={0} onSelect={() => {}} onClose={() => {}} />);
    } finally {
      globalThis.fetch = original;
    }
    expect(screen.getByText(/as printed/i)).toBeTruthy();
    expect(screen.queryByText(/Position in the document/)).toBeNull();
  });
});
