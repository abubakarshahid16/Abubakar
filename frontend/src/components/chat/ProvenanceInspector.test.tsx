import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Citation } from "./EvidencePanel";
import type { AnswerPassage } from "../../types/api";

const passage: AnswerPassage = {
  chunk_id: "chunk-1", document_id: "doc-1", filename: "spec.pdf", page_start: 4, page_end: 5,
  section: "2.1 Design", text: "The design shall include a relief valve.", highlight: null,
  match_span: null, chunks_joined: 1, kind: "prose", score: 1.2, identifier_hits: [],
  text_source: "recognised", ocr_min_conf: 0.82, ocr_alphabet_violations: 0, ocr_alphabet_sample: null,
};

describe("citation inspection", () => {
  it("shows source, section, passage and OCR confidence, and closes with Escape", () => {
    render(<Citation passage={passage} />);
    const trigger = screen.getByRole("button", { name: /Inspect citation/i });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Citation details" })).toHaveTextContent("Read by OCR, lowest confidence 0.82");
    expect(screen.getByRole("dialog")).toHaveTextContent("2.1 Design");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
