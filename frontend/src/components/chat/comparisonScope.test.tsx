/**
 * The comparison-scope notice.
 *
 * THE DEFECT THIS EXISTS FOR. "Please compare the mechanical requirements from
 * all documents" came back as ONE verbatim passage from one document, with two
 * other passages collapsed beneath it, and the screen said nothing about the
 * comparison it had not performed. ChatView sends every composer question as
 * `tier: "extract"` and there is no mode selector on Chat, so the screen
 * structurally cannot compare across the corpus. Silence in the face of a
 * comparison request is an implied claim that one was done.
 *
 * The fix is the small honest one — a statement, not a feature. These tests
 * hold the two halves that make it honest:
 *
 *  1. The COUNT is real. It comes from the evidence the message carries, and
 *     the notice does not appear when the answer genuinely spans documents.
 *  2. The DETECTION is conservative. An ordinary question gets no notice; a
 *     notice on a normal answer is a screen contradicting itself.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AnswerCard,
  asksForComparison,
  documentsAnsweredFrom,
  type AnswerView,
} from "./AnswerCard";
import type { AnswerPassage } from "../../types/api";

const DOC13: AnswerPassage = {
  chunk_id: "doc13:p00204:c00311:aa11",
  document_id: "doc13",
  filename: "MechanicalSpecification.pdf",
  page_start: 204,
  page_end: 205,
  section: "10.1 General Procedure",
  text: "The mechanical completion procedure shall be carried out in accordance with clause 10.",
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

const DOC15: AnswerPassage = {
  ...DOC13,
  chunk_id: "doc15:p00042:c00099:bb22",
  document_id: "doc15",
  filename: "PipingSpecification.pdf",
  page_start: 42,
  page_end: 42,
  section: "4.2 Mechanical requirements",
  text: "Mechanical requirements for piping supports are given in table 4.",
};

const DOC16: AnswerPassage = {
  ...DOC13,
  chunk_id: "doc16:p00007:c00012:cc33",
  document_id: "doc16",
  filename: "StructuralSpecification.pdf",
  page_start: 7,
  page_end: 7,
  section: "2.1 Scope",
  text: "Mechanical requirements for structural steelwork are given in annex B.",
};

function extractView(passage: AnswerPassage, supporting: AnswerPassage[] = []): AnswerView {
  return {
    answer_type: "extract",
    answer: passage.text,
    reason: null,
    passage,
    supporting,
    passages: [],
    cited: [],
    rejected_citations: [],
    model: null,
    truncated: false,
    evidence_removed: [],
    seconds: 1.4,
    examples: [],
  };
}

function generatedView(passages: AnswerPassage[], cited: number[]): AnswerView {
  return {
    answer_type: "generated",
    answer: passages.map((_, i) => `A claim [S${i + 1}].`).join(" "),
    reason: null,
    passage: null,
    supporting: [],
    passages,
    cited,
    rejected_citations: [],
    model: "qwen2.5:7b",
    truncated: false,
    evidence_removed: [],
    seconds: 48,
    examples: [],
  };
}

function card(view: AnswerView, question: string | null) {
  return (
    <AnswerCard
      view={view}
      question={question}
      onSelectSource={() => {}}
      activeSource={null}
    />
  );
}

/** The notice, however it is worded, is the one element marked as a note. */
const notice = () => screen.queryByRole("note");

// ------------------------------------------------------------ the matcher

describe("asksForComparison", () => {
  const COMPARISONS = [
    "please compare the mechanical requirements from all documents",
    "Compare the coating thickness in each spec",
    "How do these compare?",
    "Give me a comparison of the welding requirements",
    "comparisons of the two standards please",
    "contrast the inspection regimes",
    "What is the difference between NORSOK M-501 and the project spec?",
    "differences between the two documents",
    "NORSOK versus the client specification",
    "M-501 vs the project spec",
    "summarise the mechanical requirements across all documents",
    "what is common between all the specifications",
    "list the mechanical requirements from all documents",
    "the requirements from all of the documents",
  ];

  for (const q of COMPARISONS) {
    it(`matches: ${q}`, () => {
      expect(asksForComparison(q)).toBe(true);
    });
  }

  const ORDINARY = [
    "What is the NDFT for coating system no. 1?",
    "Which clause covers mechanical completion?",
    "Show me the hydrotest pressure",
    "What does section 10.1 say?",
    "Who approves the welding procedure specification?",
    // Near-misses. These carry a comparison WORD or a fragment of one and
    // must still be left alone; a matcher that fires on them is a matcher
    // that fires on prose.
    "What are the compartment ventilation requirements?",
    "State the difference in millimetres allowed for flatness",
    "Is a comparator required for the calibration rig?",
    "What is the pressure across the filter?",
  ];

  for (const q of ORDINARY) {
    it(`does not match: ${q}`, () => {
      expect(asksForComparison(q)).toBe(false);
    });
  }

  it("treats an absent question as not a comparison", () => {
    expect(asksForComparison(null)).toBe(false);
    expect(asksForComparison(undefined)).toBe(false);
    expect(asksForComparison("")).toBe(false);
  });
});

// -------------------------------------------------------- the document count

describe("documentsAnsweredFrom", () => {
  it("counts the quoted passage's document for an extract", () => {
    expect(documentsAnsweredFrom(extractView(DOC13))).toEqual(["doc13"]);
  });

  it("does not count matched-but-unmerged passages as answered from", () => {
    // The card's own report warning says the other matched passages are "not
    // merged into the quoted answer". The count must agree with that sentence.
    expect(documentsAnsweredFrom(extractView(DOC13, [DOC15, DOC16]))).toEqual(["doc13"]);
  });

  it("counts the CITED documents for generated prose", () => {
    expect(documentsAnsweredFrom(generatedView([DOC13, DOC15, DOC16], [1, 3]))).toEqual([
      "doc13",
      "doc16",
    ]);
  });

  it("counts a document once however many of its passages are cited", () => {
    const second: AnswerPassage = { ...DOC13, chunk_id: "doc13:p00206:c00312:dd44" };
    expect(documentsAnsweredFrom(generatedView([DOC13, second], [1, 2]))).toEqual(["doc13"]);
  });

  it("counts nothing for an answer with no passage at all", () => {
    expect(documentsAnsweredFrom({ ...extractView(DOC13), passage: null })).toEqual([]);
  });

  it("counts nothing for a refusal", () => {
    const refusal: AnswerView = {
      ...extractView(DOC13),
      answer_type: "insufficient_evidence",
      passage: null,
      passages: [DOC13, DOC15],
    };
    expect(documentsAnsweredFrom(refusal)).toEqual([]);
  });
});

// ------------------------------------------------------------- the rendering

describe("the notice on the card", () => {
  it("says so when a comparison question is answered from one document", () => {
    render(card(extractView(DOC13, [DOC15, DOC16]), "please compare the mechanical requirements from all documents"));
    const n = notice();
    expect(n).not.toBeNull();
    expect(n!.textContent).toMatch(/answered from 1 document\b/i);
    expect(n!.textContent).toMatch(/not performed in Chat/i);
  });

  it("states the count, not a bare word", () => {
    // A hardcoded "one" would survive a change to the counting; a hardcoded
    // number would survive the count being wrong. The digit must be the one
    // documentsAnsweredFrom produced.
    const view = extractView(DOC13, [DOC15, DOC16]);
    render(card(view, "compare the mechanical requirements across all documents"));
    expect(notice()!.textContent).toContain(
      `Answered from ${documentsAnsweredFrom(view).length} document`,
    );
  });

  it("does not appear for an ordinary question", () => {
    render(card(extractView(DOC13, [DOC15, DOC16]), "What is the NDFT for coating system no. 1?"));
    expect(notice()).toBeNull();
  });

  it("does not appear when the question is unknown", () => {
    render(card(extractView(DOC13), null));
    expect(notice()).toBeNull();
  });

  it("does not appear when the answer draws on more than one document", () => {
    render(
      card(
        generatedView([DOC13, DOC15, DOC16], [1, 2, 3]),
        "compare the mechanical requirements from all documents",
      ),
    );
    expect(notice()).toBeNull();
  });

  it("appears on generated prose that cited only one document", () => {
    render(
      card(
        generatedView([DOC13, DOC15, DOC16], [1]),
        "compare the mechanical requirements from all documents",
      ),
    );
    expect(notice()!.textContent).toMatch(/answered from 1 document\b/i);
  });

  it("does not appear on a refusal, which claims no answer at all", () => {
    const refusal: AnswerView = {
      ...extractView(DOC13),
      answer_type: "insufficient_evidence",
      passage: null,
      passages: [DOC13],
      reason: "nothing credible was retrieved",
    };
    render(card(refusal, "compare the mechanical requirements from all documents"));
    expect(notice()).toBeNull();
  });

  it("promises no feature and points at no other screen", () => {
    render(card(extractView(DOC13), "compare the mechanical requirements from all documents"));
    const text = notice()!.textContent ?? "";
    for (const forbidden of [/\byet\b/i, /coming soon/i, /Analysis/i, /will be/i, /not supported yet/i]) {
      expect(text, `the notice said "${forbidden}"`).not.toMatch(forbidden);
    }
  });

  it("is not inside the quotation, so it cannot read as the document's words", () => {
    render(card(extractView(DOC13), "compare the mechanical requirements from all documents"));
    const quote = document.querySelector("blockquote");
    expect(quote).not.toBeNull();
    expect(quote!.contains(notice())).toBe(false);
  });
});
