/**
 * The clause label is not printed, and the citation still stands.
 *
 * WHY THIS FILE EXISTS. `chunks.section` is the heading the chunker believed
 * was in force, and it does not reset at chapter or appendix boundaries: a
 * stale label carries forward and is asserted, in the same weight and with the
 * same confidence as the page number, over text it has nothing to do with.
 * Measured twice and the two agree - 5 of 6 cited passages wrong when checked
 * against the PDFs, and `scripts/section_audit.py` scoring doc16 at 0% correct
 * (11 of 11 wrong) with the whole of doc17's Appendix A carrying "3.20 SUPPLY
 * CHAIN RISK MANAGEMENT" from the last numbered chapter before it.
 *
 * FABRICATED is zero corpus-wide. That is the danger: a stale label is a real
 * clause from the same document, so nothing about it looks wrong.
 *
 * WHAT IS ASSERTED HERE, and it is three separate things because the obvious
 * over-correction breaks two of them:
 *
 *   1. The section string does not reach the screen. Anywhere.
 *   2. The document and the page DO, unchanged. That is the citation, it is
 *      what makes an answer auditable, and it is reliable (7/7 on pages).
 *   3. Nothing takes the label's place. No "unknown", no "N/A", no dash, no
 *      "(no clause numbering)". A value this codebase cannot state renders as
 *      NOTHING - the same way `AnswerCard` renders nothing for a null
 *      `seconds`, a null `passage`, or an empty `supporting`.
 *
 * Both render sites are covered, because the label had three homes on screen
 * and fixing one would have left the others: the citation row under a quoted
 * answer (`Citation`), the "other passages matched" list and the "what was
 * considered" list (`PassageLocation`), and the evidence panel (`Citation`
 * again, at the top of the panel).
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerCard, type AnswerView } from "./AnswerCard";
import { Citation, PassageLocation } from "./EvidencePanel";
import { clauseLabel } from "./Provenance";
import type { AnswerPassage } from "../../types/api";

/** doc16 p22. The chunker labels this "6.0 Procedure"; that heading is on
 *  p15, seven pages earlier. The page is right and the clause is not. */
const STALE: AnswerPassage = {
  chunk_id: "c1",
  document_id: "doc16",
  filename: "doc16.pdf",
  page_start: 22,
  page_end: 22,
  section: "6.0 Procedure",
  text: "Submissions shall be made in accordance with the design programme.",
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

/** doc16 p27. Labelled "3.4 Final Design Submissions"; the truth is
 *  "4.5 Mechanical". A second real-world label, so a test that happened to
 *  match one string is not the whole of the evidence. */
const STALE_2: AnswerPassage = {
  ...STALE,
  chunk_id: "c2",
  page_start: 27,
  page_end: 27,
  section: "3.4 Final Design Submissions",
  text: "Mechanical services shall be coordinated with the structural design.",
};

/** A passage the chunker gave no heading at all. It must look EXACTLY like
 *  one that has a heading: the reader learns nothing from either, so the
 *  screen must not offer them a difference to read into. */
const UNLABELLED: AnswerPassage = {
  ...STALE,
  chunk_id: "c3",
  section: null,
};

/** Every placeholder this codebase refuses to print. `—` is the em dash and
 *  `-` the hyphen, because a stand-in is a stand-in whichever one gets typed. */
const PLACEHOLDERS = [
  /unknown/i,
  /\bn\/a\b/i,
  /not available/i,
  /no clause/i,
  /clause/i,
  /section/i,
  /^\s*[—–-]\s*$/,
];

function extractView(p: AnswerPassage, supporting: AnswerPassage[] = []): AnswerView {
  return {
    answer_type: "extract",
    answer: p.text,
    reason: null,
    passage: p,
    supporting,
    passages: [],
    cited: [],
    rejected_citations: [],
    model: null,
    truncated: false,
    evidence_removed: [],
    seconds: 1.2,
    examples: [],
  };
}

// ---------------------------------------------------------------- the seam

describe("clauseLabel is the one place that decides", () => {
  it("yields nothing for a passage carrying a section string", () => {
    expect(clauseLabel(STALE)).toBeNull();
    expect(clauseLabel(STALE_2)).toBeNull();
  });

  it("yields nothing for a passage carrying none, and so cannot be a tell", () => {
    // Same answer either way. If the two ever differ, the screen has started
    // leaking whether the chunker guessed a heading - which is not a fact
    // about the document.
    expect(clauseLabel(UNLABELLED)).toBeNull();
    expect(clauseLabel(null)).toBeNull();
    expect(clauseLabel(undefined)).toBeNull();
  });
});

// ------------------------------------------------------------ the citation

describe("Citation: the clause is not printed", () => {
  it("does not render the section string", () => {
    const { container } = render(<Citation passage={STALE} />);
    expect(container.textContent).not.toContain("6.0 Procedure");
    // Not just the whole string: the clause NUMBER alone was rendered in its
    // own span, so a check for the full heading would pass while "6.0" sat on
    // screen labelled as a clause.
    expect(container.textContent).not.toContain("6.0");
  });

  it("does not render a DIFFERENT stale section string either", () => {
    const { container } = render(<Citation passage={STALE_2} />);
    expect(container.textContent).not.toContain("3.4 Final Design Submissions");
    expect(container.textContent).not.toContain("3.4");
  });

  it("still renders the document and the page, unchanged", () => {
    const { container } = render(<Citation passage={STALE} />);
    expect(container.textContent).toContain("doc16.pdf");
    expect(container.textContent).toContain("page 22");
  });

  it("renders a page RANGE unchanged", () => {
    const { container } = render(
      <Citation passage={{ ...STALE, page_start: 22, page_end: 24 }} />,
    );
    expect(container.textContent).toContain("pages 22–24");
  });

  it("puts no placeholder where the clause was", () => {
    const { container } = render(<Citation passage={STALE} />);
    const text = container.textContent ?? "";
    for (const p of PLACEHOLDERS) {
      expect(text, `citation rendered a placeholder matching ${p}`).not.toMatch(p);
    }
  });

  it("reads exactly as document, page, and nothing else", () => {
    // The whole line, not a substring: this is what gets pasted into an email.
    const { container } = render(<Citation passage={STALE} />);
    expect(container.textContent).toBe("doc16.pdf, page 22");
  });

  it("looks identical whether or not the chunker guessed a heading", () => {
    const withLabel = render(<Citation passage={STALE} />).container.textContent;
    const withoutLabel = render(<Citation passage={UNLABELLED} />).container.textContent;
    expect(withoutLabel).toBe(withLabel);
  });
});

// ------------------------------------------------------------- the list row

describe("PassageLocation: the clause is not printed", () => {
  it("does not render the section string", () => {
    const { container } = render(<PassageLocation passage={STALE} />);
    expect(container.textContent).not.toContain("6.0 Procedure");
    expect(container.textContent).not.toContain("6.0");
  });

  it("still renders the document and the page, unchanged", () => {
    const { container } = render(<PassageLocation passage={STALE} />);
    expect(container.textContent).toContain("doc16.pdf");
    expect(container.textContent).toContain("page 22");
  });

  it("puts no placeholder where the clause was", () => {
    const { container } = render(<PassageLocation passage={STALE} />);
    const text = container.textContent ?? "";
    for (const p of PLACEHOLDERS) {
      expect(text, `row rendered a placeholder matching ${p}`).not.toMatch(p);
    }
  });

  it("looks identical whether or not the chunker guessed a heading", () => {
    const withLabel = render(<PassageLocation passage={STALE} />).container.textContent;
    const withoutLabel = render(
      <PassageLocation passage={UNLABELLED} />,
    ).container.textContent;
    expect(withoutLabel).toBe(withLabel);
  });
});

// -------------------------------------------------- the whole answer card

describe("AnswerCard: no clause anywhere on a rendered answer", () => {
  function renderCard() {
    return render(
      <AnswerCard
        view={extractView(STALE, [STALE_2])}
        onSelectSource={() => {}}
        activeSource={null}
      />,
    );
  }

  it("prints neither stale label, on the citation row or in the matched list", () => {
    const { container } = renderCard();
    const text = container.textContent ?? "";
    expect(text).not.toContain("6.0 Procedure");
    expect(text).not.toContain("3.4 Final Design Submissions");
    // The supporting list is inside a <details>; jsdom renders its children
    // regardless of the open attribute, so this really does cover that row.
    expect(screen.getByText(/1 other passage matched/i)).toBeInTheDocument();
  });

  it("keeps the document and both pages, so the answer stays auditable", () => {
    renderCard();
    const cite = document.querySelector("cite")!;
    expect(cite.textContent).toContain("doc16.pdf");
    expect(cite.textContent).toContain("page 22");
    // and the supporting row keeps its own page
    const details = screen.getByText(/1 other passage matched/i).closest("details")!;
    expect(within(details).getByText("page 27")).toBeInTheDocument();
    expect(within(details).getByText("doc16.pdf")).toBeInTheDocument();
  });

  it("puts no placeholder anywhere the clause used to be", () => {
    const { container } = renderCard();
    const text = container.textContent ?? "";
    // Narrowed to the citation row and the matched list: the card's own prose
    // legitimately contains the word "section" ("stay in the evidence
    // section"), and asserting over the whole card would fail on a sentence
    // that has nothing to do with this defect.
    const cite = container.querySelector("cite")!.textContent ?? "";
    const details = container.querySelector("details")!.textContent ?? "";
    for (const p of PLACEHOLDERS) {
      expect(cite, `citation rendered a placeholder matching ${p}`).not.toMatch(p);
      expect(details, `matched list rendered a placeholder matching ${p}`).not.toMatch(p);
    }
    expect(text).toContain("doc16.pdf");
  });
});
