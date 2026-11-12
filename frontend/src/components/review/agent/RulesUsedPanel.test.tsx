/**
 * Rules used: view only. MUTATION PROOF: make the filter change the data
 * (drop a row from the totals) and the "only narrows" test fails; add an
 * edit control and the view-only test fails; render a null field as "null"
 * and the field test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRulesUsed } from "../../../types/api";
import { NOT_AGENT_RULES, RulesUsedPanel, RulesUsedView } from "./RulesUsedPanel";

const rulesUsed = vi.fn();
const summaryFn = vi.fn();
vi.mock("../../../api/agentReview", () => ({
  agentReview: { rulesUsed: (...a: unknown[]) => rulesUsed(...a), summary: (...a: unknown[]) => summaryFn(...a) },
  isFeatureOff: (r: { ok: boolean; error?: { code: string } }) => !r.ok && r.error?.code === "not_found",
}));
beforeEach(() => { rulesUsed.mockReset(); summaryFn.mockReset().mockResolvedValue({ ok: true, data: { mode: "rule review" } }); });

function data(over: Partial<AgentRulesUsed> = {}): AgentRulesUsed {
  return {
    paper_kind: "datasheet", equipment_type: "pump",
    asked: [
      { rule_book: "Book A", clause: "1.1", quote: "q one", paper_kind: "datasheet", field: "rated flow", equipment: null, tier: "AI approved", read_from: "text" },
      { rule_book: "Book B", clause: "2.1", quote: "q two", paper_kind: "datasheet", field: null, equipment: "pump", tier: "Engineer", read_from: "text" },
      { rule_book: "Book B", clause: "2.2", quote: "q three", paper_kind: "datasheet", field: "head", equipment: "pump", tier: "Not AI approved", read_from: "text" },
      { rule_book: "Book C", clause: "3.1", quote: "q four", paper_kind: "datasheet", field: "x", equipment: "pump", tier: "Owner", read_from: "text" },
    ],
    left_out: [
      { rule_book: "Book A", clause: "9.1", reason: "needs another paper" },
      { rule_book: "Book D", clause: "9.2", reason: "needs a human" },
      { rule_book: "Book D", clause: "9.3", reason: "needs a human" },
    ],
    left_out_counts: { "needs another paper": 1, "needs a human": 2 },
    missing_books: [{ name: "Book Q", why: "not in the library" }],
    rule_set_changed_by: null, books: [], equipment_state: null, equipment_notes: [], ...over,
  };
}

describe("RulesUsedView", () => {
  it("shows the header, the Asked table with every tier word, the Left out table with counts, and the missing books", () => {
    render(<RulesUsedView data={data()} />);
    expect(screen.getByText("datasheet", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByText("pump", { selector: "span" }).length).toBeGreaterThan(0);
    const asked = screen.getByRole("table", { name: "Rules asked of this paper" });
    for (const tier of ["AI approved", "Engineer", "Owner", "Not AI approved"]) expect(within(asked).getByText(tier)).toBeInTheDocument();
    expect(screen.getByTestId("asked-count")).toHaveTextContent("Showing 4 of 4 rules asked for this paper.");
    const counts = screen.getByTestId("left-out-counts");
    expect(counts).toHaveTextContent("needs another paper: 1");
    expect(counts).toHaveTextContent("needs a human: 2");
    expect(within(screen.getByRole("table", { name: "Rules left out of this paper" })).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByText("Book Q: not in the library")).toBeInTheDocument();
  });
  it("null fields render as nothing, never the word null or 0", () => {
    render(<RulesUsedView data={data()} />);
    const row = screen.getByText("q two").closest("tr")!;
    const cells = within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toEqual(["Book B", "2.1", "q two", "datasheet", "", "pump", "Engineer"]);
    expect(document.body.textContent).not.toMatch(/null|undefined/);
  });
  it("the filter only narrows what is shown and says so with its denominator", async () => {
    const d = data();
    const before = JSON.stringify(d);
    render(<RulesUsedView data={d} />);
    await userEvent.type(screen.getByLabelText("Filter by rule book, approval or reason"), "book b");
    expect(screen.getByTestId("asked-count")).toHaveTextContent("Showing 2 of 4 rules asked");
    expect(screen.queryByText("q one")).toBeNull();
    expect(screen.getByTestId("left-count")).toHaveTextContent("Showing 0 of 3 rules left out");
    expect(screen.getByTestId("left-out-counts")).toHaveTextContent("needs a human: 2");
    expect(JSON.stringify(d)).toBe(before);
  });
  it("the filter reaches tier and reason", async () => {
    render(<RulesUsedView data={data()} />);
    const box = screen.getByLabelText("Filter by rule book, approval or reason");
    await userEvent.type(box, "owner");
    expect(screen.getByTestId("asked-count")).toHaveTextContent("Showing 1 of 4");
    await userEvent.clear(box);
    await userEvent.type(box, "needs a human");
    expect(screen.getByTestId("left-count")).toHaveTextContent("Showing 2 of 3");
  });
  it("is view only: no edit, add or leave-out control", () => {
    render(<RulesUsedView data={data()} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/View only/)).toBeInTheDocument();
  });
  it("shows who changed the rule set only when someone did", () => {
    const { rerender } = render(<RulesUsedView data={data()} />);
    expect(screen.queryByTestId("rules-changed-by")).toBeNull();
    rerender(<RulesUsedView data={data({ rule_set_changed_by: "A. Person" })} />);
    expect(screen.getByTestId("rules-changed-by")).toHaveTextContent("Rule set changed by A. Person");
  });
  it("honest empty states", () => {
    render(<RulesUsedView data={data({ paper_kind: "unknown", equipment_type: null, asked: [], left_out: [], left_out_counts: {}, missing_books: [] })} />);
    expect(screen.getByTestId("asked-empty")).toHaveTextContent("No rule was asked: the paper kind could not be decided.");
    expect(screen.getByTestId("left-empty")).toHaveTextContent("No rule was left out.");
    expect(screen.getByTestId("missing-empty")).toBeInTheDocument();
    expect(screen.queryByText(/Equipment type/)).toBeNull();
  });
});

describe("RulesUsedPanel", () => {
  it("a review the AI reviewer did not make says so", async () => {
    rulesUsed.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "x" } });
    render(<RulesUsedPanel runId="r1" />);
    expect(await screen.findByText(NOT_AGENT_RULES)).toBeInTheDocument();
  });
  it("loads and shows the page", async () => {
    rulesUsed.mockResolvedValue({ ok: true, data: data() });
    render(<RulesUsedPanel runId="r1" />);
    expect(await screen.findByTestId("rules-used")).toBeInTheDocument();
    expect(rulesUsed).toHaveBeenCalledWith("r1");
  });
});

describe("RulesUsedView: rule books and scans", () => {
  const withBooks = (books: AgentRulesUsed["books"]) => ({ ...data(), books });
  /** MUTATION PROOF: render null as 0 or 100% and the not-measured test fails;
   *  drop the below_half warning and the warning test fails. */
  it("shows coverage with its denominator and a plain warning below half", () => {
    render(<RulesUsedView data={withBooks([
      { rule_book: "Book A", requirement_sentences: 530, covered_sentences: 412, unreadable_pages: 2, weak_pages: 5, below_half: false },
      { rule_book: "Book B", requirement_sentences: 100, covered_sentences: 40, unreadable_pages: 9, weak_pages: 11, below_half: true },
    ])} />);
    const books = screen.getByTestId("books");
    expect(books).toHaveTextContent("Book A: 412 of 530 requirement sentences stored (78%)");
    expect(books).toHaveTextContent("unreadable pages: 2 · weak pages: 5");
    const warnings = screen.getAllByRole("note");
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toHaveTextContent("less than half of this book's requirement sentences are stored: weak or scanned pages must be re-read");
    expect(within(books).getByText(/Book B/).closest("li")).toContainElement(warnings[0]);
  });
  it("null numbers render as not measured, never 0% or 100%", () => {
    render(<RulesUsedView data={withBooks([
      { rule_book: "Book N", requirement_sentences: null, covered_sentences: null, unreadable_pages: null, weak_pages: null, below_half: null },
      { rule_book: "Book Z", requirement_sentences: 0, covered_sentences: 0 },
    ])} />);
    const books = screen.getByTestId("books");
    expect(books).toHaveTextContent("Book N: not measured");
    expect(books).toHaveTextContent("Book Z: not measured");
    expect(books).toHaveTextContent("unreadable pages: not measured · weak pages: not measured");
    expect(books.textContent).not.toMatch(/%/);
    expect(screen.queryByRole("note")).toBeNull();
  });
  it("no books recorded says so", () => {
    render(<RulesUsedView data={data()} />);
    expect(screen.getByTestId("books-empty")).toBeInTheDocument();
  });
  it("marks a rule read from a scan, and only that one", () => {
    const d = data();
    render(<RulesUsedView data={{ ...d, asked: [{ ...d.asked[0], read_from: "scan" as const }, { ...d.asked[1], read_from: "text" as const }] }} />);
    expect(screen.getAllByText("read from a scan")).toHaveLength(1);
    expect(screen.getByText("read from a scan").closest("tr")).toHaveTextContent("q one");
  });
});

describe("RulesUsedView: equipment notes and new reasons", () => {
  it("shows equipment_notes and the three new left-out reasons in their contract words", () => {
    render(<RulesUsedView data={data({
      equipment_notes: ["The paper names no equipment; 7 rules were left out for it."],
      left_out: [{ rule_book: "Book A", clause: "1", reason: "the paper names no equipment" }],
      left_out_counts: { "the paper names no equipment": 7 },
    })} />);
    expect(screen.getByTestId("equipment-notes")).toHaveTextContent("The paper names no equipment; 7 rules were left out for it.");
    expect(screen.getByTestId("left-out-counts")).toHaveTextContent("the paper names no equipment: 7");
    expect(screen.getAllByText("the paper names no equipment").length).toBeGreaterThan(0);
  });
});

describe("RulesUsedView: a rule left out for a part excluded by a value the paper states", () => {
  it("shows the part reason in its contract word in the counts and on the row", () => {
    render(<RulesUsedView data={data({
      left_out: [{ rule_book: "Book A", clause: "5.5", reason: "a part excluded by a value the paper states" }],
      left_out_counts: { "a part excluded by a value the paper states": 4 },
    })} />);
    expect(screen.getByTestId("left-out-counts")).toHaveTextContent("a part excluded by a value the paper states: 4");
    expect(screen.getByText("a part excluded by a value the paper states", { selector: "td" })).toBeInTheDocument();
  });
});

describe("RulesUsedView: both labelling readers named other equipment", () => {
  it("shows the reason in its contract words", () => {
    render(<RulesUsedView data={data({
      left_out: [{ rule_book: "Book A", clause: "7", reason: "both labelling readers named other equipment" }],
      left_out_counts: { "both labelling readers named other equipment": 2 },
    })} />);
    expect(screen.getByTestId("left-out-counts")).toHaveTextContent("both labelling readers named other equipment: 2");
    expect(screen.getByText("both labelling readers named other equipment", { selector: "td" })).toBeInTheDocument();
  });
});

describe("RulesUsedView: where the rules came from", () => {
  it("says the source, the repeats, and the other-book count with its boundary", () => {
    render(<RulesUsedView data={data({
      candidates_from: "the rules of the selected books", same_rule_repeats: 3,
      other_books: { books: 3, ai_approved_rules: 100, boundary: "rule books the person who started this review may read" },
    })} />);
    expect(screen.getByTestId("candidates-from")).toHaveTextContent("taken from: the rules of the selected books");
    expect(screen.getByTestId("candidates-from")).toHaveTextContent("3 stored rules are the same rule");
    expect(screen.getByTestId("other-books")).toHaveTextContent("100 in 3 books (counted over rule books the person who started this review may read)");
  });
  it("shows nothing for a run stored before this was kept (null, never 0)", () => {
    render(<RulesUsedView data={data({ candidates_from: null, same_rule_repeats: null, other_books: null })} />);
    expect(screen.queryByTestId("candidates-from")).toBeNull();
    expect(screen.queryByTestId("other-books")).toBeNull();
  });
});

describe("RulesUsedView: percentage and warning agree", () => {
  /** MUTATION PROOF: use Math.round when below half and "50%" appears with the warning; trust the server flag and the warning vanishes. */
  it("49.6% below half shows 49% with the warning, whatever the server flag says", () => {
    const d = { ...data(), books: [{ rule_book: "Book H", requirement_sentences: 500, covered_sentences: 248, below_half: false }] };
    render(<RulesUsedView data={d} />);
    expect(screen.getByTestId("books")).toHaveTextContent("248 of 500 requirement sentences stored (49%)");
    expect(screen.getByRole("note")).toHaveTextContent("less than half");
  });
  it("exactly half is not below half and rounds normally", () => {
    const d = { ...data(), books: [{ rule_book: "Book H", requirement_sentences: 500, covered_sentences: 250, below_half: true }] };
    render(<RulesUsedView data={d} />);
    expect(screen.getByTestId("books")).toHaveTextContent("(50%)");
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("Rules used for a general review", () => {
  it("says no rule was asked, lists the books not held, and shows no asked or left-out table", () => {
    render(<RulesUsedView general data={data({ asked: [], left_out: [], left_out_counts: {} })} />);
    expect(screen.getByTestId("rules-general")).toHaveTextContent("General review: no rule was asked. Rule books the paper cites that we do not hold are listed below.");
    expect(screen.getByText("Book Q: not in the library")).toBeInTheDocument();
    expect(screen.queryByTestId("asked-empty")).toBeNull();
    expect(screen.queryByTestId("left-empty")).toBeNull();
    expect(screen.queryByTestId("books-empty")).toBeNull();
    expect(screen.queryByLabelText("Filter by rule book, approval or reason")).toBeNull();
  });
  it("the panel picks the general state from the summary's mode", async () => {
    rulesUsed.mockResolvedValue({ ok: true, data: data({ asked: [] }) });
    summaryFn.mockResolvedValue({ ok: true, data: { mode: "general review" } });
    render(<RulesUsedPanel runId="r1" />);
    expect(await screen.findByTestId("rules-general")).toBeInTheDocument();
  });
  it("a rule review keeps the tables", async () => {
    rulesUsed.mockResolvedValue({ ok: true, data: data() });
    render(<RulesUsedPanel runId="r1" />);
    await screen.findByTestId("rules-used");
    expect(screen.queryByTestId("rules-general")).toBeNull();
    expect(screen.getByTestId("asked-count")).toBeInTheDocument();
  });
});


describe("BookTable", () => {
  const table = {
    boundary: "rule books in the library the person viewing this may read",
    hidden_books: 2,
    note: null,
    books: [
      { rule_book: "Book A", in_review: true, method: "named in the paper", stored_rules: 40, asked: 3, left_out: { "needs a human": 2, "needs another paper": 1 } },
      { rule_book: "Book Z", in_review: false, method: "similar text only: a reason to look, not evidence that it governs", stored_rules: 9, asked: 0, left_out: {} },
    ],
  };
  it("shows candidates with why, stored, asked and left-out counts, the boundary, and the considered-not-included books", () => {
    render(<RulesUsedView data={data({ book_table: table })} />);
    const t = screen.getByRole("table", { name: "Rule books that were candidates for this review" });
    const row = within(t).getByText("Book A").closest("tr")!;
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual(["Book A", "named in the paper", "40", "3", "needs a human 2, needs another paper 1"]);
    expect(screen.getByTestId("book-table-boundary")).toHaveTextContent("Counted over: rule books in the library the person viewing this may read");
    expect(screen.getByTestId("book-table-count")).toHaveTextContent("1 book were candidates; 1 were considered and not included.");
    expect(screen.getByTestId("book-table-out")).toHaveTextContent("Book Z: not included. similar text only");
  });
  it("says how many books are not listed because the person may not read them, without naming any", () => {
    render(<RulesUsedView data={data({ book_table: table })} />);
    expect(screen.getByTestId("book-table-count")).toHaveTextContent("2 more books of this review are not listed because you may not read them.");
  });
  it("a missing count renders as nothing, never 0, and no table at all renders no section", () => {
    const t = { ...table, books: [{ ...table.books[0], stored_rules: null }], hidden_books: 0 };
    const { unmount } = render(<RulesUsedView data={data({ book_table: t })} />);
    const row = within(screen.getByRole("table", { name: "Rule books that were candidates for this review" })).getByText("Book A").closest("tr")!;
    expect(within(row).getAllByRole("cell")[2].textContent).toBe("");
    unmount();
    render(<RulesUsedView data={data({ book_table: null })} />);
    expect(screen.queryByTestId("book-table")).toBeNull();
  });
  it("shows the note when no book selection was stored", () => {
    render(<RulesUsedView data={data({ book_table: { ...table, note: "No book selection was stored for this review" } })} />);
    expect(screen.getByTestId("book-table-note")).toHaveTextContent("No book selection was stored");
  });
});
