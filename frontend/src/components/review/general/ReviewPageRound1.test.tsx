/** The review page of the owner's picture (28 Nov 2026, round 1): four tabs, ONE status box beside ONE sign-off box on the Comments
 *  tab only, and on a signed review the sign-off warning said ONCE at the top with a short mark on each decision button.
 *  Invented values only. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralLine, GeneralReview } from "../../../api/generalReview";
import { GeneralResults } from "./GeneralResults";

const card = (n: number, over: Partial<GeneralLine> = {}): GeneralLine => ({
  n, field: `Field ${n}`, page: n, label: "Question", shown_label: "Question", comment: `invented comment ${n}`, quote: "", item_id: `C${n}`,
  standard: "STD-X", clause: "4.1", source: "held standard", severity: "Check a value", title: `Invented problem ${n}`,
  paper_says: "invented paper value", rule_says: "invented rule", we_ask: `Invented ask ${n}.`, applies_to: [{ page: n, field: `Field ${n}`, quote: "" }], ...over,
});

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  const comments = [card(1), card(2)];
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 5, comments: 2, confirmations: 1, by_label: {}, boundary: "this paper, this review" },
    comments, confirmations: [card(3, { severity: "Please confirm" })], points: [...comments, card(4), card(5), card(6)],
    books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: null }, completeness: { ok: true, page: 5, database: 5, file_rows: 5, sentence: null },
    ...over,
  } as GeneralReview;
}
const signoff = (state: "not_signed" | "signed" | "changed") => ({
  state, undecided: [], undecided_count: state === "not_signed" ? 2 : 0, codes: ["B"], can_sign: false, may_sign: true, may_sign_words: null,
  signed: state === "not_signed" ? null : { by: "Dana Engineer", at: "2026-11-28T06:20:00+00:00", code: "B", statement: null, copy_statement: "2 comments sent" },
}) as unknown as GeneralReview["signoff"];
const mount = (r: GeneralReview) => render(<GeneralResults review={r} howTab={null} onViewPage={() => undefined} />);
const tab = (name: string | RegExp) => fireEvent.click(screen.getByRole("tab", { name }));

describe("the review page, round 1", () => {
  it("has four tabs, each with its count, and opens on the comments", () => {
    mount(review({ signoff: signoff("not_signed") }));
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Comments (2)", "To confirm (1)", "All points (5)", "How this review was made"]);
    expect(screen.getByRole("tab", { name: "Comments (2)" })).toHaveAttribute("aria-selected", "true");
  });

  it("the Comments tab holds ONE status box and ONE sign-off box; the other tabs carry one short line instead", () => {
    mount(review({ signoff: signoff("not_signed") }));
    expect(screen.getAllByTestId("general-mark")).toHaveLength(1);
    expect(screen.getAllByTestId("sign-bar")).toHaveLength(1);
    expect(screen.getByTestId("general-mark")).toHaveTextContent("2 comments need your decision.");
    expect(screen.getByTestId("sign-again-note")).toHaveTextContent("If you change a decision after signing, you sign again.");
    for (const name of ["To confirm (1)", "All points (5)", "How this review was made"]) {
      tab(name);
      expect(screen.queryByTestId("general-mark")).toBeNull();
      expect(screen.queryByTestId("sign-bar")).toBeNull();
      expect(screen.getByTestId("general-mark-short")).toHaveTextContent("AI, to be checked");
      expect(screen.getByTestId("general-mark-short")).toHaveTextContent("2 comments need your decision.");
    }
  });

  it("the points to confirm are on their own tab, the comments are not among them, and every point is on All points", () => {
    mount(review({ signoff: signoff("not_signed") }));
    tab("To confirm (1)");
    const confirm = screen.getByTestId("general-confirmations");
    expect(within(confirm).getAllByTestId("general-row")).toHaveLength(1);
    expect(confirm).toHaveTextContent("Invented problem 3");
    expect(confirm).not.toHaveTextContent("Invented problem 1");
    tab("All points (5)");
    expect(within(screen.getByTestId("general-all")).getAllByTestId("general-row")).toHaveLength(5);
  });

  it("a number on the How tab opens its list: the comments, and the points to confirm", () => {
    mount(review({ signoff: signoff("not_signed") }));
    tab("How this review was made");
    fireEvent.click(within(screen.getByTestId("how-numbers")).getByRole("button", { name: /To confirm/ }));
    expect(screen.getByRole("tab", { name: "To confirm (1)" })).toHaveAttribute("aria-selected", "true");
    tab("How this review was made");
    fireEvent.click(within(screen.getByTestId("how-numbers")).getByRole("button", { name: /Comments/ }));
    expect(screen.getByRole("tab", { name: "Comments (2)" })).toHaveAttribute("aria-selected", "true");
  });

  it("a signed review says the sign-off warning ONCE, at the top, with what the three buttons do; each button keeps a short mark", () => {
    mount(review({ signoff: signoff("signed") }));
    const warnings = screen.getAllByTestId("general-signed-warning");
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toHaveTextContent("This review is signed off. A click on Accept, Edit or Reject changes a signed sheet.");
    expect(warnings[0]).toHaveTextContent("The sign-off is undone at once, the contractor copy is held back, and you sign again.");
    expect(warnings[0]).toHaveTextContent("Accept: the comment goes to the contractor as written. Edit: it goes with your wording. Reject: it is left out, and you give a one-line reason.");
    // the warning stands above everything else on the page
    expect(screen.getByTestId("general-results").firstElementChild).toBe(warnings[0]);
    // 3 cards (2 comments + 1 point to confirm) x 3 buttons: a short mark on each, and the long sentence on none of the cards
    expect(screen.getAllByTestId("card-signed-mark")).toHaveLength(9);
    for (const row of screen.getAllByTestId("general-row")) expect(row).not.toHaveTextContent("sign again");
    expect(screen.getAllByRole("button", { name: "Accept" })[0]).toHaveAttribute("title", "This undoes the sign-off");
  });

  it("an unsigned review, and one changed since sign-off, carry no such warning and no mark", () => {
    const { unmount } = mount(review({ signoff: signoff("not_signed") }));
    expect(screen.queryByTestId("general-signed-warning")).toBeNull();
    expect(screen.queryByTestId("card-signed-mark")).toBeNull();
    unmount();
    mount(review({ signoff: signoff("changed") }));
    expect(screen.queryByTestId("general-signed-warning")).toBeNull();
    expect(screen.queryByTestId("card-signed-mark")).toBeNull();
  });

  it("an older answer with no count of confirmations has no To confirm tab, never one with (0)", () => {
    const base = review();
    mount({ ...base, counts: { ...base.counts, confirmations: undefined }, confirmations: undefined });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Comments (2)", "All points (5)", "How this review was made"]);
  });
});
