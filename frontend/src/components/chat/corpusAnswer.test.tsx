/**
 * A question about the LIBRARY, on screen - and a count the model was not
 * allowed to state as one.
 *
 * "How many standards cover hydrotesting" is two questions. The library's
 * count comes from the database; what covers hydrotesting comes from the
 * documents. Blending them into one sentence is how "there are 12 distinct
 * standards" happened - a count of three retrieved passages, read as the size
 * of a 272-standard library. So the card shows two LABELLED parts, the
 * library's first, and these tests hold it to that.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerCard, type AnswerView } from "./AnswerCard";
import { viewFromMessage } from "./AnswerCardContent";
import type { AnswerPassage, CorpusFact, Message } from "../../types/api";

const P1: AnswerPassage = {
  chunk_id: "spec:p00001:c00001:aa11",
  document_id: "doc_spec",
  filename: "SAES-A-004.pdf",
  page_start: 4,
  page_end: 4,
  section: "5.3 Hydrostatic testing",
  text: "Hydrostatic testing shall be performed at 1.5 times the design pressure.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 6.5,
  identifier_hits: [],
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
};

const FACT: CorpusFact = {
  text: "272 company standards are loaded and readable by you.",
  role: "COMPANY_STANDARD",
  loaded: 272,
  not_loaded: 0,
  kind: "count",
  source: "database",
  qualified: true,
};

function view(over: Partial<AnswerView> = {}): AnswerView {
  return {
    answer_type: "extract",
    answer: P1.text,
    reason: null,
    passage: P1,
    supporting: [],
    passages: [],
    cited: [],
    rejected_citations: [],
    model: null,
    truncated: false,
    evidence_removed: [],
    seconds: 1.2,
    examples: [],
    ...over,
  };
}

function card(v: AnswerView) {
  return render(
    <AnswerCard view={v} onSelectSource={vi.fn()} activeSource={null} />,
  );
}

describe("a question about both the library and its content", () => {
  it("shows the library's count and the documents' answer as two labelled parts", () => {
    card(view({ corpus: FACT }));

    const library = screen.getByLabelText("From the library");
    expect(library).toHaveTextContent(
      "272 company standards are loaded and readable by you.");
    expect(library).toHaveTextContent(/counted from the database/i);
    expect(screen.getByText("From the documents")).toBeInTheDocument();
    // And the retrieval half is still there, unmerged.
    expect(screen.getAllByText(/1\.5 times the design pressure/).length).toBeGreaterThan(0);
  });

  it("puts the library's part FIRST, above the documents' answer", () => {
    const { container } = card(view({ corpus: FACT }));

    const text = container.textContent ?? "";
    expect(text.indexOf("272 company standards")).toBeLessThan(
      text.indexOf("From the documents"));
  });

  it("keeps the library's part above a refusal too", () => {
    // The documents may not answer the content half; the database still
    // answered the library half, and that must not vanish with the refusal.
    card(view({
      corpus: FACT, answer_type: "insufficient_evidence", answer: null,
      passage: null, reason: "none of the indexed documents mention this topic",
    }));

    expect(screen.getByLabelText("From the library")).toHaveTextContent("272 company standards");
  });
});

describe("a question about the library alone", () => {
  it("answers from the database once, not twice", () => {
    // A metadata answer IS the library's answer; wrapping it in a second
    // "From the library" block would say the same sentence twice.
    card(view({
      answer_type: "metadata", answer: FACT.text, passage: null,
      corpus: { ...FACT, qualified: false },
    }));

    expect(screen.getAllByText(FACT.text)).toHaveLength(1);
    expect(screen.queryByText("From the documents")).toBeNull();
  });
});

describe("a count the model stated, re-bounded", () => {
  it("says why the count is marked, when one was", () => {
    card(view({
      answer_type: "generated",
      answer: "There are 12 distinct standards (counted in the 3 passages retrieved for this question, not in the library) [S1].",
      passage: null, passages: [P1], cited: [1], model: "qwen", counts_bounded: 1,
    }));

    expect(screen.getByRole("note")).toHaveTextContent(
      /count of documents in this answer was marked as a count of the passages retrieved/i);
  });

  it("says nothing when no count was re-bounded", () => {
    card(view({ answer_type: "generated", passage: null, passages: [P1], cited: [1],
                model: "qwen", counts_bounded: 0 }));

    expect(screen.queryByText(/marked as a count of the passages/i)).toBeNull();
  });
});

describe("on replay", () => {
  it("carries both fields from a persisted message", () => {
    // The live reply is ALSO rendered from the persisted message, so a field
    // missing from the payload is missing from the screen, live or reopened.
    const m = {
      id: "m1", conversation_id: "c1", ordinal: 2, role: "assistant",
      text: P1.text, resolved_question: null, carried_terms: [],
      answer_type: "extract", reason: null, input_kind: null, examples: [],
      explains_id: null, created_at: "2026-09-20T00:00:00Z",
      payload: { passage: P1, corpus: FACT, counts_bounded: 2 },
    } as unknown as Message;

    const v = viewFromMessage(m);

    expect(v.corpus?.loaded).toBe(272);
    expect(v.counts_bounded).toBe(2);
  });
});
