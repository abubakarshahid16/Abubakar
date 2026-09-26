/**
 * B9: the chat shows the B8 verdict, the B6C scope, and withholds a reopened
 * turn whose document the reader can no longer open. Every assertion below is
 * paired with a vitest mutation in scripts/mutations/chat_reopen.py.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerCard, type AnswerView, viewFromMessage } from "./AnswerCard";
import type { AnswerPassage, Message } from "../../types/api";

const P: AnswerPassage = {
  chunk_id: "std:p00004:c00010:aa11",
  document_id: "doc_std",
  filename: "STD-100.pdf",
  page_start: 4,
  page_end: 4,
  section: "5.2 Bolting",
  text: "Bolts shall be hot-dip galvanised.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 6.1,
  identifier_hits: [],
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
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

describe("the B8 verdict is visible on the answer", () => {
  it("says a supported answer is supported by rendering no warning", () => {
    show(view({ answerability: { verdict: "supported", reason: "quoted", evidence: [] } }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText(P.text)).toBeInTheDocument();
  });

  it("warns on conflicting evidence, keeps the passage, and cites page and clause", () => {
    show(view({ answerability: {
      verdict: "conflicting_evidence", reason: "two documents give different values",
      evidence: [{ document_id: "doc_std", page_start: 4, page_end: 4, section: "5.2 Bolting" }],
    } }));
    expect(screen.getByText(/The documents disagree on this/)).toBeInTheDocument();
    expect(screen.getByText("two documents give different values")).toBeInTheDocument();
    expect(screen.getByText("page 4, 5.2 Bolting")).toBeInTheDocument();
    expect(screen.getByText(P.text)).toBeInTheDocument();
  });

  it("routes a judgement question to an engineer", () => {
    show(view({ answerability: { verdict: "requires_engineer_review", reason: "r", evidence: [] } }));
    expect(screen.getByText(/needs an engineer's judgement/)).toBeInTheDocument();
  });

  it("says it cannot determine the answer when the evidence is insufficient", () => {
    show(view({ answer_type: "insufficient_evidence", answer: null, passage: null,
      reason: "nothing credible was retrieved",
      answerability: { verdict: "insufficient_evidence", reason: "r", evidence: [] } }));
    expect(screen.getByText("I cannot determine this from the available evidence")).toBeInTheDocument();
  });

  it("an extract the gate called insufficient still says so", () => {
    show(view({ answerability: { verdict: "insufficient_evidence", reason: "no quote answers it", evidence: [] } }));
    expect(screen.getByText("I cannot determine this from the available evidence")).toBeInTheDocument();
  });
});

describe("the question's scope is shown, never silent", () => {
  it("shows the scope reason and the ambiguity with document names", () => {
    show(view({
      understanding: { retrieval_query: "q", document_id: "doc_std", scope_reason: "the question names STD-100",
        scope_ids: null, clause: "5.2", clause_reason: null, ambiguous_documents: [], notes: [] },
      scope_ambiguity: { reason: "the same text is in 2 documents",
        documents: [{ document_id: "a", filename: "A.pdf" }, { document_id: "b", filename: "B.pdf" }] },
    }));
    expect(screen.getByText("Searched: the question names STD-100")).toBeInTheDocument();
    expect(screen.getByText("Clause asked about: 5.2")).toBeInTheDocument();
    expect(screen.getByText("the same text is in 2 documents (A.pdf, B.pdf)")).toBeInTheDocument();
  });
});

describe("a reopened turn survives the round trip through the stored message", () => {
  const base: Message = {
    id: "m", conversation_id: "c", ordinal: 2, role: "assistant", text: P.text,
    resolved_question: null, carried_terms: [], answer_type: "extract", reason: null,
    explains_id: null, created_at: "2026-09-26T00:00:00Z", payload: null,
  };

  it("carries the verdict and scope back from the payload", () => {
    const v = viewFromMessage({ ...base, payload: {
      passage: P,
      answerability: { verdict: "ambiguous_evidence", reason: "r", evidence: [] },
      understanding: null, scope_ambiguity: null,
    } });
    expect(v.answerability?.verdict).toBe("ambiguous_evidence");
    show(v);
    expect(screen.getByText(/appears in more than one document/)).toBeInTheDocument();
  });

  it("a withheld turn shows the notice and no passage", () => {
    const v = viewFromMessage({ ...base, answer_type: null,
      text: "This answer cited a document you no longer have access to, so it is not shown.",
      payload: { withheld: true } });
    show(v);
    expect(screen.getByTestId("withheld")).toHaveTextContent(/no longer have access/);
    expect(screen.queryByText(/I cannot determine/)).toBeNull();
  });
});
