/** Piece H: the general review's "How this review was made" view. Invented values only. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralLine, GeneralReview } from "../../../api/generalReview";
import { HowReviewMade, secondLookWords, sixSteps, totalsByStep, trustOf } from "./HowReviewMade";

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

/** Click one of the six steps: its panel opens (and any other closes). */
const open = (title: RegExp) => fireEvent.click(screen.getByRole("button", { name: title }));
const dataRows = (testId: string) => within(screen.getByTestId(testId)).getAllByRole("row").slice(1);

describe("H: How this review was made", () => {
  it("opens with one sentence, the numbers and six steps, and NO panel (owner, 28 Nov 2026)", () => {
    const base = review();
    render(<HowReviewMade review={{ ...base, counts: { ...base.counts, confirmations: 4, by_shown_label: { "AI opinion: met": 1, "AI opinion: does not apply": 0 } } }} />);
    expect(screen.getByTestId("how-summary")).toHaveTextContent("3 points were checked against 2 rule books.");
    expect(screen.getByTestId("how-summary")).toHaveTextContent("1 rule book this paper needs is not in the library.");
    expect(within(screen.getByTestId("how-steps")).getAllByRole("button")).toHaveLength(6);
    expect(screen.queryByTestId("how-panel")).toBeNull();
    const numbers = screen.getByTestId("how-numbers");
    expect(numbers).toHaveTextContent("Comments 2 for you to decide");
    expect(numbers).toHaveTextContent("To confirm 4");
  });

  it("a number the server did not count is not drawn, never 0", () => {
    render(<HowReviewMade review={review()} />);
    expect(screen.getByTestId("how-numbers")).not.toHaveTextContent("To confirm");
    expect(screen.getByTestId("how-numbers")).not.toHaveTextContent("Met");
  });

  it("one panel at a time: another step switches it, Close and the same step close it", () => {
    render(<HowReviewMade review={review()} />);
    open(/Named the paper/);
    expect(screen.getByTestId("how-panel")).toHaveAttribute("data-step", "named");
    open(/Picked the rule books/);
    expect(screen.getAllByTestId("how-panel")).toHaveLength(1);
    expect(screen.getByTestId("how-panel")).toHaveAttribute("data-step", "books");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("how-panel")).toBeNull();
    open(/Counted everything/);
    open(/Counted everything/);
    expect(screen.queryByTestId("how-panel")).toBeNull();
  });

  it("the panel stands straight after its step in the page, so on a narrow screen it opens under that step", () => {
    render(<HowReviewMade review={review()} />);
    open(/Checked each point/);
    const items = [...screen.getByTestId("how-steps").children];
    const at = items.findIndex((li) => li.getAttribute("data-testid") === "how-step-checks");
    expect(items[at + 1].querySelector('[data-testid="how-panel"]')).not.toBeNull();
  });

  it("1 read the paper: says what was not read, or that it is not recorded, never that all was read without the record", () => {
    const { unmount } = render(<HowReviewMade review={review()} />);
    expect(screen.getByTestId("how-step-read")).toHaveTextContent("Which pages were read is not recorded");
    open(/Read the paper/);
    expect(screen.getByTestId("general-pages-not-recorded")).toBeInTheDocument();
    unmount();
    render(<HowReviewMade review={review({ pages_not_read: [{ where: "page 4", why: "no text", sentence: "Page 4 was not read: no text came back." }], pages_not_read_record: "listed" })} />);
    expect(screen.getByTestId("how-step-read")).toHaveTextContent("1 part of the paper was not read");
    open(/Read the paper/);
    expect(screen.getByTestId("general-pages-not-read")).toHaveTextContent("Page 4 was not read: no text came back.");
  });

  it("2 named the paper: says what the paper is", () => {
    render(<HowReviewMade review={review()} />);
    open(/Named the paper/);
    const s = screen.getByTestId("how-paper");
    expect(s).toHaveTextContent("datasheet");
    expect(s).toHaveTextContent("relief valve"); // plain words, no underscore (planner 18 Nov 23:40-5)
    expect(s).toHaveTextContent("invented valve sheet");
  });

  it("3 gives each rule book its reason, says when none was recorded, lists the books not held, counts the hidden one", () => {
    render(<HowReviewMade review={review()} />);
    open(/Picked the rule books/);
    const books = within(screen.getByTestId("how-books"));
    const rows = books.getAllByTestId("how-book");
    expect(rows[0]).toHaveTextContent("Why chosen: governs the equipment type");
    expect(rows[1]).toHaveTextContent("the reason was not recorded");
    expect(books.getByTestId("how-not-held")).toHaveTextContent("Invented Std Part 2");
    expect(screen.getByTestId("how-books")).toHaveTextContent("and 1 you may not open");
  });

  it("3 says how many of the listed documents were used, and a reason the server withheld as it words it", () => {
    render(<HowReviewMade review={review({
      documents_listed: { listed: 21, used: 7, sentence: "Of the 21 other documents listed before the start, 7 were used." },
      books: [{ id: "b1", title: "invented-book-one.pdf", why: "not shown: it names a book you may not read" }],
    })} />);
    open(/Picked the rule books/);
    expect(screen.getByTestId("how-listed")).toHaveTextContent("Of the 21 other documents listed before the start, 7 were used.");
    expect(screen.getAllByTestId("how-book")[0]).toHaveTextContent("Why chosen: not shown: it names a book you may not read");
  });

  it("3 says nothing about a list for a run that stored none", () => {
    render(<HowReviewMade review={review({ documents_listed: null })} />);
    open(/Picked the rule books/);
    expect(screen.queryByTestId("how-listed")).toBeNull();
  });

  it("4 shows the checklist, and nothing for a part it does not hold", () => {
    render(<HowReviewMade review={review()} />);
    open(/Checked each point/);
    const s = screen.getByTestId("how-checklist");
    expect(s).toHaveTextContent("67");
    expect(s).toHaveTextContent("built for this review");
    expect(s).toHaveTextContent("standards only, no paper");
  });

  it("4 lists every point with book, clause, quote and what code compared; the filter narrows it", () => {
    render(<HowReviewMade review={review()} />);
    open(/Checked each point/);
    const rows = dataRows("how-checks");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("STD-X, clause 4.1");
    expect(rows[0]).toHaveTextContent("12 bar <= 10 bar: false");
    expect(rows[0]).toHaveTextContent("invented quote 1");
    expect(rows[1]).toHaveTextContent("nothing compared by code");
    expect(rows[2]).toHaveTextContent("engineering knowledge");
    fireEvent.change(screen.getByLabelText("Show points with this result"), { target: { value: "Question" } });
    expect(dataRows("how-checks")).toHaveLength(1);
    expect(screen.getByTestId("how-checks-count")).toHaveTextContent("1 of 3 points");
  });

  it("4 says how much to trust each part, marks the AI's own dismissals least trusted, and the four counts add up to the points", () => {
    const points = [
      line(1, "Pass, compared by code"), line(2, "AI opinion: met"), line(3, "Question"), line(4, "AI opinion: not met"),
      line(5, "AI opinion: does not apply"), line(6, "AI opinion: does not apply"),
    ];
    const base = review({ points, comments: [points[2], points[3]] });
    render(<HowReviewMade review={{ ...base, counts: { ...base.counts, points: 6, comments: 2, confirmations: 4 } }} />);
    open(/Checked each point/);
    expect(screen.getByTestId("how-trust-code")).toHaveTextContent("Decided by code: 1");
    expect(screen.getByTestId("how-trust-code")).toHaveTextContent("Most trusted");
    expect(screen.getByTestId("how-trust-ai_met")).toHaveTextContent("Read by the AI as met: 1");
    expect(screen.getByTestId("how-trust-yours")).toHaveTextContent("For you to decide: 2");
    expect(screen.getByTestId("how-trust-yours")).toHaveTextContent("These points make up the 2 comments and the 4 points to confirm of the first page.");
    const least = screen.getByTestId("how-trust-dismissed");
    expect(least).toHaveTextContent("Dismissed by the AI alone: 2");
    expect(least).toHaveTextContent("Least trusted");
    expect(least).toHaveTextContent("No code and no person checked it.");
    expect(screen.getByTestId("how-trust").parentElement).toHaveTextContent("1 + 1 + 2 + 2 = 6 points.");
    fireEvent.click(within(least).getByRole("button", { name: "Show these" }));
    expect(dataRows("how-checks")).toHaveLength(2);
  });

  it("trustOf sorts by the label the server shows, and an unknown label is the engineer's to decide", () => {
    expect(trustOf("Fail, compared by code")).toBe("code");
    expect(trustOf("AI opinion: met")).toBe("ai_met");
    expect(trustOf("AI opinion: does not apply")).toBe("dismissed");
    expect(trustOf("Question")).toBe("yours");
    expect(trustOf("something new")).toBe("yours");
  });

  it("5 says what a fault is, and says plainly when the same AI was asked twice", () => {
    const calls = [{ step: "aim_judge", model: "m-lead", usd: 0, seconds: 1 }, { step: "aim_second_read", model: "m-lead", usd: 0, seconds: 1 }];
    const base = review({ calls });
    const comments = [{ ...base.comments[0], title: "Invented title", readers: { first: "Not met", second: "Question", reason: "invented" } }, base.comments[1]];
    render(<HowReviewMade review={{ ...base, comments, steps_not_applied: [{ step: "aim_edit", why: "cut", sentence: "The wording step did not run for 2 comments." }] }} />);
    expect(screen.getByTestId("how-step-second")).toHaveTextContent("1 comment got a different answer");
    open(/Second look at the faults/);
    const panel = screen.getByTestId("how-panel");
    expect(panel).toHaveTextContent("A fault is a point where the AI said the paper does not meet the rule.");
    expect(screen.getByTestId("how-second-words")).toHaveTextContent("The same AI was asked twice. This is not a second reviewer.");
    expect(screen.getByTestId("how-second-differ")).toHaveTextContent("Invented title");
    expect(screen.getByTestId("general-steps-not-applied")).toHaveTextContent("The wording step did not run for 2 comments.");
  });

  it("5 never claims a second look that the run does not record, and names a different model as different", () => {
    expect(secondLookWords([{ step: "aim_judge", model: "a", usd: null }])).toBeNull();
    expect(secondLookWords([{ step: "aim_judge", model: "a", usd: null }, { step: "aim_second_read", model: "b", usd: null }])).toMatch(/A different AI looked/);
    render(<HowReviewMade review={review()} />);
    expect(screen.getByTestId("how-step-second")).toHaveTextContent("No second look is recorded for this review");
    open(/Second look at the faults/);
    expect(screen.getByTestId("how-second-words")).toHaveTextContent("No second look is recorded for this review.");
  });

  it("6 shows the comment sheet rows, folded", () => {
    render(<HowReviewMade review={review()} />);
    open(/Counted everything/);
    expect(dataRows("how-sheet")).toHaveLength(2);
  });

  it("time and cost are folded at the foot, grouped by step in plain names, summing the calls of one step", () => {
    render(<HowReviewMade review={review()} />);
    const steps = dataRows("how-time");
    expect(steps.map((r) => r.querySelector("td")?.textContent)).toEqual(["Name the document", "Check each item", "Read the document"]);
    expect(steps[1]).toHaveTextContent("2"); // two judge calls
    expect(steps[1]).toHaveTextContent("150"); // 100 + 50 seconds
    expect(steps[1]).toHaveTextContent("0.500"); // 0.2 + 0.3
    expect(screen.getByTestId("how-time")).toHaveTextContent("10.4 min");
    expect(screen.getByTestId("how-time")).toHaveTextContent("USD 1.36");
  });

  it("a cost that was not read renders as nothing and says so, never as 0", () => {
    const calls = [{ step: "aim_judge", model: "m", usd: null, seconds: 5 }];
    render(<HowReviewMade review={review({ cost: { usd: null, note: "the ledger could not be read" }, calls })} />);
    expect(screen.getByTestId("how-cost-unread")).toHaveTextContent("the ledger could not be read");
    expect(screen.getByTestId("how-time")).not.toHaveTextContent("USD 0");
    expect(within(dataRows("how-time")[0]).getAllByRole("cell").pop()).toHaveTextContent(/^$/);
  });

  it("6 says whether the three counts agree", () => {
    const { rerender } = render(<HowReviewMade review={review()} />);
    open(/Counted everything/);
    expect(screen.getByTestId("how-complete")).toHaveTextContent("all three agree");
    rerender(<HowReviewMade review={review({ completeness: { ok: false, page: 3, database: 4, file_rows: 3, sentence: null } })} />);
    expect(screen.getByTestId("how-complete")).toHaveTextContent("they differ");
  });

  it("three counts of 0 are never a pass in the list of steps", () => {
    const steps = sixSteps(review({ completeness: { ok: true, page: 0, database: 0, file_rows: 0, sentence: null } }));
    expect(steps[5].line).toBe("Nothing to compare: the review has no points");
    expect(steps[5].chip).toBe("Not recorded");
  });

  it("a review that recorded nothing says so and shows no zero", () => {
    render(<HowReviewMade review={review({
      identity: { kind: null, equipment_type: null, subject: null }, books: [], books_not_readable: 0, not_held: [],
      checklist: { key: null, items: null, reused: null, built_from: null }, calls: [], seconds: null, cost: { usd: null },
    })} />);
    expect(screen.getByTestId("how-step-named")).toHaveTextContent("What the paper is was not recorded");
    open(/Named the paper/);
    expect(screen.getByTestId("how-paper")).toHaveTextContent("did not record what the paper is");
    open(/Checked each point/);
    expect(screen.getByTestId("how-checklist")).toHaveTextContent("did not record its list of checks");
    expect(screen.getByTestId("how-time")).toHaveTextContent("No calls were recorded");
  });

  it("totalsByStep keeps a step with no cost at null, not 0", () => {
    expect(totalsByStep([{ step: "aim_edit", model: "m", usd: null, seconds: 3 }])[0].usd).toBeNull();
  });

  it("6 counts the confirmations beside the comments, when the server counted them", () => {
    const base = review();
    render(<HowReviewMade review={{ ...base, counts: { ...base.counts, comments: 51, confirmations: 20, comment_lines: 64, confirmation_lines: 33 } }} />);
    open(/Counted everything/);
    expect(screen.getByTestId("how-confirmations")).toHaveTextContent(
      '51 comments sent (covering 64 points) and 20 confirmations not sent (covering 33 points); together 97 points qualified to be sent. Every point stays under "Checked each point".');
  });

  it("6 says nothing about confirmations for an older run, and never 0 for a count it lacks", () => {
    const { rerender } = render(<HowReviewMade review={review()} />);
    open(/Counted everything/);
    expect(screen.queryByTestId("how-confirmations")).toBeNull();
    const base = review();
    rerender(<HowReviewMade review={{ ...base, counts: { ...base.counts, comments: 1, confirmations: 1 } }} />);
    const text = screen.getByTestId("how-confirmations").textContent ?? "";
    expect(text).toBe('1 comment sent and 1 confirmation not sent. Every point stays under "Checked each point".');
  });

  it("3 lists each part of the contract with its pages read of held, the unread pages and why; nothing for a paper without parts", () => {
    const refs = [
      { part: "Schedule B", title: "invented-schedule-b.pdf", status: "read in part", reason: "pages 44-84 were not read: a call stopped", questions: 7, settled: 3, pages_read: 43, pages_held: 84, compared: 4, differs: 1 },
      { part: "Schedule D", title: null, status: "not held", reason: "", questions: 0, settled: 0, pages_read: null, pages_held: null, compared: null, differs: null },
    ];
    const { unmount } = render(<HowReviewMade review={review({ references: refs })} />);
    open(/Picked the rule books/);
    const rows = screen.getAllByTestId("how-reference");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Schedule B (invented-schedule-b.pdf)");
    expect(rows[0]).toHaveTextContent("read in part; pages read 43 of 84; 3 of 7 questions settled; 4 sentences of the Form compared, 1 differ");
    expect(rows[0]).toHaveTextContent("pages 44-84 were not read: a call stopped");
    expect(rows[1]).toHaveTextContent("not held");
    expect(rows[1]).not.toHaveTextContent("pages read");
    unmount();
    render(<HowReviewMade review={review()} />);
    open(/Picked the rule books/);
    expect(screen.queryByTestId("how-references")).toBeNull();
  });
});
