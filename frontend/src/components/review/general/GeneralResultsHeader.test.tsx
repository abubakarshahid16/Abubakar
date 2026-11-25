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
    mount(review({ counts: { points: 193, comments: 73, by_label: {}, boundary: "this paper", by_shown_label: { "Question": 159, "AI opinion: does not apply": 28, "AI opinion: met": 4, "AI opinion: not met": 1, "AI opinion": 2 } } }));
    const t = screen.getByTestId("general-counts");
    expect(t).toHaveTextContent("159 questions");
    expect(t).toHaveTextContent("28 do not apply (the AI's view)");
    expect(t).toHaveTextContent("4 met (the AI's view)");
    expect(t).toHaveTextContent("1 not met (the AI's view)");
    expect(t).not.toHaveTextContent(/AI opinion:/i);
  });

  it("names the pages that were not read, and says nothing when every page was", () => {
    const { unmount } = mount(review({ pages_not_read: [
      { where: "page 7", why: "no_text", sentence: "Page 7 was not read: it has no text, or almost none (fewer than 20 characters), and no picture reading came back." },
      { where: "picture 2", why: "picture_not_read", sentence: "Picture 2 was not read: no picture reading came back." },
    ] }));
    const note = screen.getByTestId("general-pages-not-read");
    expect(note).toHaveTextContent("2 parts of this paper were not read.");
    expect(note).toHaveTextContent("Page 7 was not read");
    expect(note).toHaveTextContent("Picture 2 was not read");
    unmount();
    mount(review({ pages_not_read: [] }));
    expect(screen.queryByTestId("general-pages-not-read")).toBeNull();
  });

  it("a review that stopped because the Claude account has no credit says so at the top in plain words, not only a stop code", () => {
    const words = "The AI account has no credit left, so the Claude steps cannot run. Choose Local only, or ask the owner to add credit.";
    mount(review({ status: "stopped", stop_reason: "aim_judge: stop account_no_credit", stop_words: words }));
    const top = screen.getByTestId("general-account-stop");
    expect(top).toHaveTextContent("This review did not finish.");
    expect(top).toHaveTextContent(words);
    expect(screen.getByTestId("general-stopped")).not.toHaveTextContent("account_no_credit"); // the code is not the message
  });

  it("any other stop keeps the code and shows no account alert", () => {
    mount(review({ status: "stopped", stop_reason: "run_cap: the run cap" }));
    expect(screen.queryByTestId("general-account-stop")).toBeNull();
    expect(screen.getByTestId("general-stopped")).toHaveTextContent("run_cap");
  });
});

