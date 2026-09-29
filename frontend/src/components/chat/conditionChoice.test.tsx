/**
 * Plan step 4: when clauses near the top set different values for different
 * conditions, the answer says so - every clause with its condition, and a
 * question back - and a reopened turn keeps it. Paired with vitest mutations
 * M1416-M1418 in scripts/mutations/condition_choice.py.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerCard, type AnswerView, viewFromMessage } from "./AnswerCard";
import type { AnswerPassage, ConditionChoice, Message } from "../../types/api";

const P: AnswerPassage = {
  chunk_id: "spec:p00001:c00002:aa11", document_id: "doc_spec", filename: "SPEC-1.pdf",
  page_start: 1, page_end: 1, section: "4.2 Pipes 2 inch and smaller",
  text: "The minimum wall thickness shall be 3 mm.", highlight: null, match_span: null,
  chunks_joined: 1, kind: "prose", score: 5, identifier_hits: [], text_source: "extracted",
  ocr_min_conf: null, ocr_alphabet_violations: 0, ocr_alphabet_sample: null,
};

const OPTIONS: ConditionChoice = {
  mode: "options",
  reason: "these clauses set different values for different size",
  kinds: ["size"],
  question_names: [],
  options: [
    { chunk_id: "a", document_id: "doc_spec", filename: "SPEC-1.pdf", section: "4.2 Pipes 2 inch and smaller",
      page_start: 1, page_end: 1, conditions: ["2 inch and smaller"] },
    { chunk_id: "b", document_id: "doc_spec", filename: "SPEC-1.pdf", section: "4.3 Pipes larger than 2 inch",
      page_start: 1, page_end: 1, conditions: ["larger than 2 inch"] },
  ],
};

function view(over: Partial<AnswerView> = {}): AnswerView {
  return {
    answer_type: "extract", answer: P.text, reason: null, passage: P,
    supporting: [], passages: [], cited: [], rejected_citations: [], model: null,
    truncated: false, evidence_removed: [], seconds: 1, examples: [], ...over,
  };
}

function show(v: AnswerView) {
  return render(<AnswerCard view={v} onSelectSource={() => {}} activeSource={null} />);
}

describe("clauses that differ by condition", () => {
  it("asks which condition applies and lists every clause with its condition", () => {
    show(view({ condition_choice: OPTIONS }));
    expect(screen.getByText(/which applies to you\?/)).toBeInTheDocument();
    expect(screen.getByText("2 inch and smaller")).toBeInTheDocument();
    expect(screen.getByText("larger than 2 inch")).toBeInTheDocument();
    expect(screen.getByText(/4.3 Pipes larger than 2 inch, page 1/)).toBeInTheDocument();
    // the quoted passage is still shown: the notice is above it, not instead of it
    expect(screen.getByText(P.text)).toBeInTheDocument();
  });

  it("says why a clause other than the top-ranked one answered", () => {
    show(view({ condition_choice: { ...OPTIONS, mode: "matched", question_names: ["6 inch"],
      options: [OPTIONS.options[1]] } }));
    expect(screen.getByTestId("condition-matched")).toHaveTextContent(
      "Answered for 6 inch: the clause written for larger than 2 inch applies");
  });

  it("renders nothing when no clause competed", () => {
    show(view({ condition_choice: null }));
    expect(screen.queryByTestId("condition-options")).toBeNull();
    expect(screen.queryByTestId("condition-matched")).toBeNull();
  });

  it("keeps the choice when a conversation is reopened", () => {
    const m: Message = {
      id: "m", conversation_id: "c", ordinal: 2, role: "assistant", text: P.text,
      resolved_question: null, carried_terms: [], answer_type: "extract", reason: null,
      explains_id: null, created_at: "2026-09-30T00:00:00Z",
      payload: { passage: P, condition_choice: OPTIONS },
    };
    show(viewFromMessage(m));
    expect(screen.getByTestId("condition-options")).toBeInTheDocument();
  });
});
