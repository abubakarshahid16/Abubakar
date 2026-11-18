/** The comment cards of the general review (planner's design, 18 Nov 2026). Invented values only. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GeneralLine, GeneralReview } from "../../../api/generalReview";
import { CommentCards, SeverityTiles } from "./CommentCards";

const MARK = "AI, to be checked";

const card = (n: number, over: Partial<GeneralLine> = {}): GeneralLine => ({
  n, field: `Field ${n}`, page: n, label: "Question", shown_label: "Question", comment: `invented comment ${n}`, quote: `invented quote ${n}`,
  item_id: `C00${n}`, standard: "STD-X", clause: `4.${n}`, source: "held standard",
  severity: "Check a value", title: `Invented problem ${n}`, paper_says: `paper value ${n}`, rule_says: `STD-X clause 4.${n}`, we_ask: `please confirm ${n}`,
  applies_to: [{ page: n, field: `Field ${n}`, quote: `invented quote ${n}` }], proven: MARK, ...over,
});

function review(comments: GeneralLine[], confirmations: GeneralLine[] = [], by?: GeneralReview["counts"]["by_severity"]): GeneralReview {
  return {
    comments, confirmations, counts: { points: 9, comments: comments.length, by_label: {}, boundary: "this paper", by_severity: by },
  } as unknown as GeneralReview;
}

function mount(r: GeneralReview, onViewPage = vi.fn()) {
  render(<CommentCards review={r} mark={MARK} onViewPage={onViewPage} renderPlain={(l) => <li key={l.n} data-testid="plain-row">{l.field}</li>} />);
  return onViewPage;
}

const THREE = [
  card(1, { severity: "Must fix", proven: "compared by code", title: "Backpressure over the limit" }),
  card(2, { severity: "Check a value" }),
  card(3, { severity: "Missing information", applies_to: [{ page: 3, field: "Size", quote: "q3" }, { page: 4, field: "Flow", quote: "q4" }] }),
];

describe("comment cards", () => {
  it("one card per comment: title, severity word, paper says, rule says, we ask, in that order", () => {
    mount(review(THREE));
    const first = screen.getAllByTestId("general-row")[0];
    expect(within(first).getByTestId("card-title")).toHaveTextContent("Backpressure over the limit");
    expect(within(first).getByTestId("card-severity")).toHaveTextContent("Must fix");
    const text = first.textContent ?? "";
    expect(text.indexOf("Paper says")).toBeLessThan(text.indexOf("Rule says"));
    expect(text.indexOf("Rule says")).toBeLessThan(text.indexOf("We ask"));
    expect(within(first).getByTestId("card-mark")).toHaveTextContent("AI, to be checked · compared by code");
  });

  it("a card with several places has one chip per place, each opening its page; quotes are folded", () => {
    const open = mount(review(THREE));
    const third = screen.getAllByTestId("general-row")[2];
    expect(within(third).getByRole("button", { name: "page 3" })).toBeInTheDocument();
    fireEvent.click(within(third).getByRole("button", { name: "page 4" }));
    expect(open).toHaveBeenCalledWith(4);
    const evidence = within(third).getByTestId("card-evidence");
    expect(evidence.tagName).toBe("DETAILS");
    expect(evidence).not.toHaveAttribute("open");
    expect(evidence).toHaveTextContent("Show evidence (2 quotes)");
  });

  it("a card never says 'AI, to be checked' twice when the card was not proven by code", () => {
    mount(review([card(2)]));
    expect(screen.getByTestId("card-mark").textContent).toBe("AI, to be checked");
  });

  it("the summary tiles count each severity and filter the list; a second press clears it", () => {
    const by = { "Must fix": 1, "Check a value": 1, "Missing information": 1, "Please confirm": 4 };
    const r = review(THREE, [], by);
    mount(r);
    const tiles = screen.getByTestId("severity-tiles");
    expect(tiles).toHaveTextContent("Please confirm (separate part, not sent)");
    fireEvent.click(within(tiles).getByRole("button", { name: /Missing information/ }));
    expect(screen.getAllByTestId("general-row")).toHaveLength(1);
    expect(screen.getByTestId("card-filter-count")).toHaveTextContent("1 of 3");
    fireEvent.click(within(tiles).getByRole("button", { name: /Missing information/ }));
    expect(screen.getAllByTestId("general-row")).toHaveLength(3);
  });

  it("the page filter keeps the comments that apply to that page", () => {
    mount(review(THREE));
    fireEvent.change(screen.getByLabelText("Show comments that apply to this page"), { target: { value: "4" } });
    expect(screen.getAllByTestId("general-row")).toHaveLength(1);
    expect(within(screen.getAllByTestId("general-row")[0]).getByTestId("card-title")).toHaveTextContent("Invented problem 3");
  });

  it("a severity with no count is left out of the tiles, never shown as 0", () => {
    render(<SeverityTiles counts={{ "Must fix": 2 }} active={null} onPick={() => undefined} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("an older answer without cards keeps the plain rows and shows no tiles or filters", () => {
    const plain = [{ ...card(1), severity: undefined, title: undefined }];
    mount(review(plain as GeneralLine[]));
    expect(screen.getAllByTestId("plain-row")).toHaveLength(1);
    expect(screen.queryByTestId("severity-tiles")).toBeNull();
  });

  it("the confirmations are cards too, in a closed part that is not among the comments", () => {
    mount(review([card(1)], [card(5, { severity: "Please confirm" })]));
    const part = screen.getByTestId("general-confirmations");
    expect(part).not.toHaveAttribute("open");
    expect(within(part).getByTestId("card-severity")).toHaveTextContent("Please confirm");
    expect(screen.getAllByTestId("general-row").filter((r) => !part.contains(r))).toHaveLength(1);
  });
});
