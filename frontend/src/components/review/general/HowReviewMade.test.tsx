/** Piece H: the general review's "How this review was made" view. Invented values only. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralLine, GeneralReview } from "../../../api/generalReview";
import { HowReviewMade, totalsByStep } from "./HowReviewMade";

const line = (n: number, shown: string, over: Partial<GeneralLine> = {}): GeneralLine => ({
  n, field: `Invented field ${n}`, page: n, label: shown, shown_label: shown, comment: `invented comment ${n}`, quote: `invented quote ${n}`,
  item_id: `C00${n}`, standard: "STD-X", clause: `4.${n}`, source: "held standard", compared: "", compare_kind: "", ...over,
});

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  const points = [
    line(1, "Fail, compared by code", { compared: "12 bar <= 10 bar: false", compare_kind: "verified paper quotes" }),
    line(2, "Question"),
    line(3, "AI opinion: met", { quote: "", standard: "" }),
  ];
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: "relief_valve", subject: "invented valve sheet" },
    counts: { points: 3, comments: 2, by_label: {}, boundary: "this paper, this review" },
    comments: [points[0], points[1]], points,
    books: [
      { id: "b1", title: "invented-book-one.pdf", why: "governs the equipment type" },
      { id: "b2", title: "invented-book-two.pdf", why: "" },
    ],
    books_not_readable: 1,
    not_held: [{ name: "Invented Std Part 2", why: "governs the equipment type; not held" }],
    unlisted_books: { count: 0, sentence: null },
    checklist: { key: "datasheet__relief_valve", items: 67, always_items: 3, reused: false, built_from: "standards only, no paper" },
    cost: { usd: 1.36 }, seconds: 624.4,
    calls: [
      { step: "aim_identify", model: "m-lead", usd: 0.1, seconds: 10 },
      { step: "aim_judge", model: "m-lead", usd: 0.2, seconds: 100 },
      { step: "aim_judge", model: "m-lead", usd: 0.3, seconds: 50 },
      { step: "aim_read_pages", model: "code", usd: 0, seconds: 0 },
    ],
    completeness: { ok: true, page: 3, database: 3, file_rows: 3, sentence: null },
    ...over,
  };
}

describe("H: How this review was made", () => {
  it("1 says what the paper is", () => {
    render(<HowReviewMade review={review()} />);
    const s = screen.getByTestId("how-paper");
    expect(s).toHaveTextContent("datasheet");
    expect(s).toHaveTextContent("relief valve"); // plain words, no underscore (planner 18 Nov 23:40-5)
    expect(s).toHaveTextContent("invented valve sheet");
  });

  it("2 gives each rule book its reason, says when none was recorded, lists the books not held, counts the hidden one", () => {
    render(<HowReviewMade review={review()} />);
    const books = within(screen.getByTestId("how-books"));
    const rows = books.getAllByTestId("how-book");
    expect(rows[0]).toHaveTextContent("Why chosen: governs the equipment type");
    expect(rows[1]).toHaveTextContent("the reason was not recorded");
    expect(books.getByTestId("how-not-held")).toHaveTextContent("Invented Std Part 2");
    expect(screen.getByTestId("how-books")).toHaveTextContent("and 1 you may not open");
  });

  it("2 says how many of the listed documents were used, and a reason the server withheld as it words it", () => {
    render(<HowReviewMade review={review({
      documents_listed: { listed: 21, used: 7, sentence: "Of the 21 other documents listed before the start, 7 were used." },
      books: [{ id: "b1", title: "invented-book-one.pdf", why: "not shown: it names a book you may not read" }],
    })} />);
    expect(screen.getByTestId("how-listed")).toHaveTextContent("Of the 21 other documents listed before the start, 7 were used.");
    expect(screen.getAllByTestId("how-book")[0]).toHaveTextContent("Why chosen: not shown: it names a book you may not read");
  });

  it("2 says nothing about a list for a run that stored none", () => {
    render(<HowReviewMade review={review({ documents_listed: null })} />);
    expect(screen.queryByTestId("how-listed")).toBeNull();
  });

  it("3 shows the checklist, and nothing for a part it does not hold", () => {
    render(<HowReviewMade review={review()} />);
    const s = screen.getByTestId("how-checklist");
    expect(s).toHaveTextContent("67");
    expect(s).toHaveTextContent("built for this review");
    expect(s).toHaveTextContent("standards only, no paper");
  });

  it("4 lists every check with book, clause, quote and what code compared; the filter narrows it", () => {
    render(<HowReviewMade review={review()} />);
    const rows = screen.getAllByTestId("how-check");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("STD-X, clause 4.1");
    expect(rows[0]).toHaveTextContent("12 bar <= 10 bar: false");
    expect(rows[0]).toHaveTextContent("invented quote 1");
    expect(rows[1]).toHaveTextContent("nothing compared by code");
    expect(rows[2]).toHaveTextContent("engineering knowledge");
    fireEvent.change(screen.getByLabelText("Show checks with this result"), { target: { value: "Question" } });
    expect(screen.getAllByTestId("how-check")).toHaveLength(1);
    expect(screen.getByTestId("how-checks-count")).toHaveTextContent("1 of 3 checks");
  });

  it("5 shows the comment sheet rows", () => {
    render(<HowReviewMade review={review()} />);
    expect(screen.getAllByTestId("how-comment")).toHaveLength(2);
  });

  it("6 groups time and cost by step, in plain names, summing the calls of one step", () => {
    render(<HowReviewMade review={review()} />);
    const steps = screen.getAllByTestId("how-step");
    expect(steps.map((r) => r.querySelector("td")?.textContent)).toEqual(["Name the paper", "Check each item", "Read the paper"]);
    expect(steps[1]).toHaveTextContent("2"); // two judge calls
    expect(steps[1]).toHaveTextContent("150"); // 100 + 50 seconds
    expect(steps[1]).toHaveTextContent("0.500"); // 0.2 + 0.3
    expect(screen.getByTestId("how-time")).toHaveTextContent("10.4 min");
    expect(screen.getByTestId("how-time")).toHaveTextContent("USD 1.36");
  });

  it("6 a cost that was not read renders as nothing and says so, never as 0", () => {
    const calls = [{ step: "aim_judge", model: "m", usd: null, seconds: 5 }];
    render(<HowReviewMade review={review({ cost: { usd: null, note: "the ledger could not be read" }, calls })} />);
    expect(screen.getByTestId("how-cost-unread")).toHaveTextContent("the ledger could not be read");
    expect(screen.getByTestId("how-time")).not.toHaveTextContent("USD 0");
    expect(within(screen.getByTestId("how-step")).getAllByRole("cell").pop()).toHaveTextContent(/^$/);
  });

  it("7 says whether the three counts agree", () => {
    const { rerender } = render(<HowReviewMade review={review()} />);
    expect(screen.getByTestId("how-complete")).toHaveTextContent("all three agree");
    rerender(<HowReviewMade review={review({ completeness: { ok: false, page: 3, database: 4, file_rows: 3, sentence: null } })} />);
    expect(screen.getByTestId("how-complete")).toHaveTextContent("they differ");
  });

  it("a review that recorded nothing says so and shows no zero", () => {
    render(<HowReviewMade review={review({
      identity: { kind: null, equipment_type: null, subject: null }, books: [], books_not_readable: 0, not_held: [],
      checklist: { key: null, items: null, reused: null, built_from: null }, calls: [], seconds: null, cost: { usd: null },
    })} />);
    expect(screen.getByTestId("how-paper")).toHaveTextContent("did not record what the paper is");
    expect(screen.getByTestId("how-checklist")).toHaveTextContent("did not record its checklist");
    expect(screen.getByTestId("how-time")).toHaveTextContent("No calls were recorded");
  });

  it("totalsByStep keeps a step with no cost at null, not 0", () => {
    expect(totalsByStep([{ step: "aim_edit", model: "m", usd: null, seconds: 3 }])[0].usd).toBeNull();
  });

  it("7 counts the confirmations beside the comments, when the server counted them", () => {
    const base = review();
    render(<HowReviewMade review={{ ...base, counts: { ...base.counts, comments: 51, confirmations: 20, comment_lines: 64, confirmation_lines: 33 } }} />);
    expect(screen.getByTestId("how-confirmations")).toHaveTextContent(
      '51 comments sent (covering 64 points) and 20 confirmations not sent (covering 33 points); together 97 points qualified to be sent. Every point stays in "Every check".');
  });

  it("7 says nothing about confirmations for an older run, and never 0 for a count it lacks", () => {
    const { rerender } = render(<HowReviewMade review={review()} />);
    expect(screen.queryByTestId("how-confirmations")).toBeNull();
    const base = review();
    rerender(<HowReviewMade review={{ ...base, counts: { ...base.counts, comments: 1, confirmations: 1 } }} />);
    const line = screen.getByTestId("how-confirmations").textContent ?? "";
    expect(line).toBe('1 comment sent and 1 confirmation not sent. Every point stays in "Every check".');
  });
});
