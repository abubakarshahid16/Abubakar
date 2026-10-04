import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvidencePanel } from "./EvidencePanel";
import type { AnswerPassage } from "../../types/api";

const passage = {
  chunk_id: "c1", document_id: "doc_a", filename: "STD-A-001.pdf",
  page_start: 1, page_end: 1, section: null, text: "Invented text.",
  highlight: null, match_span: null, chunks_joined: 1, text_source: "extracted",
  ocr_min_conf: null, ocr_alphabet_violations: 0, ocr_alphabet_sample: null,
  kind: "prose", score: 1, identifier_hits: [],
} as unknown as AnswerPassage;

afterEach(() => vi.restoreAllMocks());

describe("EvidencePanel with blocked storage", () => {
  it("still renders when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<EvidencePanel passages={[passage]} selected={0} onSelect={() => {}} onClose={() => {}} />);
    expect(screen.getByLabelText("Evidence")).toBeInTheDocument();
  });
});
