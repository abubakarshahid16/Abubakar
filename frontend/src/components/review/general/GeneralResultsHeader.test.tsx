/** The results page header (planner 18 Nov 23:40): the banner after sign-off, plain words for the label counts. Invented values only. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralReview } from "../../../api/generalReview";
import { GeneralResults } from "./GeneralResults";

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 0, comments: 0, by_label: {}, boundary: "this paper, this review" },
    comments: [], points: [], books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: null }, completeness: { ok: true, page: 0, database: 0, file_rows: 0, sentence: null },
    ...over,
  } as GeneralReview;
}
const mount = (r: GeneralReview) => render(<GeneralResults review={r} howTab={null} onViewPage={() => undefined} />);

describe("GeneralResults header", () => {
  it("after sign-off the banner says it was signed off and no longer says nothing is signed off", () => {
    const signoff = { state: "signed", undecided: [], undecided_count: 0, codes: [], can_sign: false, may_sign: true, may_sign_words: null,
      signed: { by: "Dana Engineer", at: "2026-11-18T12:00:00+00:00", code: "Approved", statement: null, copy_statement: "x" } } as GeneralReview["signoff"];
    mount(review({ signoff }));
    const banner = screen.getByTestId("general-mark");
    expect(banner).toHaveTextContent("Signed off");
    expect(banner).toHaveTextContent("signed off by Dana Engineer");
    expect(banner).not.toHaveTextContent("nothing here is signed off");
  });

  it("before sign-off the banner keeps the mark and the warning", () => {
    mount(review());
    expect(screen.getByTestId("general-mark")).toHaveTextContent("AI, to be checked");
    expect(screen.getByTestId("general-mark")).toHaveTextContent("nothing here is signed off");
  });

  it("the header counts by label are plain words, not raw label names", () => {
    mount(review({ counts: { points: 193, comments: 73, by_label: {}, boundary: "this paper", by_shown_label: { "Question": 159, "AI opinion: does not apply": 28, "AI opinion: met": 4, "AI opinion": 2 } } }));
    const t = screen.getByTestId("general-counts");
    expect(t).toHaveTextContent("159 questions");
    expect(t).toHaveTextContent("28 do not apply (the AI's view)");
    expect(t).toHaveTextContent("4 met (the AI's view)");
    expect(t).not.toHaveTextContent("AI opinion:");
  });
});
