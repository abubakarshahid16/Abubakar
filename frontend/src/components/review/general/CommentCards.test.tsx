/** The comment cards of the general review (planner's design, 18 Nov 2026). Invented values only. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const decide = vi.fn();
vi.mock("../../../api/generalReview", async (orig) => ({
  ...(await orig<typeof import("../../../api/generalReview")>()),
  generalReview: { decide: (...a: unknown[]) => decide(...a) },
}));

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
    paper_document_id: "doc1", run_id: "run1", comments, confirmations, counts: { points: 9, comments: comments.length, by_label: {}, boundary: "this paper", by_severity: by },
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
  it("shows a small tag when the two readers differ and never puts it in the comment's text", () => {
    mount(review([card(1, { we_ask: "State the editions.", readers: { first: "AI opinion", second: "Met", reason: "Standards are stated." } })]));
    expect(screen.getByTestId("card-readers")).toHaveTextContent("Two readers differ (AI opinion / Met)");
    expect(screen.getByText("State the editions.")).toBeInTheDocument();
    expect(screen.queryByText(/First reader/)).toBeNull();
  });

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


const ok = (state: string, extra: Record<string, unknown> = {}) => ({
  ok: true, data: { run_id: "run1", comment: 1, part: "comment", decision: { state, words: state === "accept" ? "Accepted" : state === "edit" ? "Edited" : "Rejected", text: null, reason: null, by: "Dana Engineer", at: "2026-11-18T12:00:00+00:00", revisions: 1, ...extra } },
});

describe("H10: Accept / Edit / Reject on each card", () => {
  beforeEach(() => decide.mockReset());
  const first = () => screen.getAllByTestId("general-row")[0];

  it("says 'Not decided yet' and offers the three buttons", () => {
    mount(review(THREE));
    expect(within(first()).getByTestId("card-decision")).toHaveTextContent("Not decided yet");
    for (const name of ["Accept", "Edit", "Reject"]) expect(within(first()).getByRole("button", { name })).toBeInTheDocument();
  });

  it("Accept records the decision on the server and the card then says who decided", async () => {
    decide.mockResolvedValue(ok("accept"));
    mount(review(THREE));
    fireEvent.click(within(first()).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(within(first()).getByTestId("card-decision-state")).toHaveTextContent("Accepted by Dana Engineer"));
    expect(decide).toHaveBeenCalledWith("doc1", { run_id: "run1", comment: 1, part: "comment", state: "accept", text: undefined, reason: undefined });
  });

  it("Edit opens the AI's text, sends the engineer's own, and cannot be saved empty", async () => {
    decide.mockResolvedValue(ok("edit", { text: "My own words." }));
    mount(review(THREE));
    fireEvent.click(within(first()).getByRole("button", { name: "Edit" }));
    const box = within(first()).getByLabelText(/Your text for this comment/) as HTMLTextAreaElement;
    expect(box.value).toBe("please confirm 1");
    fireEvent.change(box, { target: { value: "  " } });
    expect(within(first()).getByRole("button", { name: "Save my text" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "My own words." } });
    fireEvent.click(within(first()).getByRole("button", { name: "Save my text" }));
    await waitFor(() => expect(within(first()).getByTestId("card-decision-state")).toHaveTextContent("Engineer's text: My own words."));
    expect(decide.mock.calls[0][1]).toMatchObject({ state: "edit", text: "My own words." });
  });

  it("Reject needs a one-line reason of at least ten characters before it can be saved", async () => {
    decide.mockResolvedValue(ok("reject", { reason: "The paper states it on page 3." }));
    mount(review(THREE));
    fireEvent.click(within(first()).getByRole("button", { name: "Reject" }));
    const save = within(first()).getByRole("button", { name: "Save rejection" });
    expect(save).toBeDisabled();
    fireEvent.change(within(first()).getByLabelText(/why this comment is rejected/), { target: { value: "too short" } });
    expect(save).toBeDisabled();
    fireEvent.change(within(first()).getByLabelText(/why this comment is rejected/), { target: { value: "The paper states it on page 3." } });
    fireEvent.click(save);
    await waitFor(() => expect(within(first()).getByTestId("card-decision-state")).toHaveTextContent("Reason: The paper states it on page 3."));
    expect(decide.mock.calls[0][1]).toMatchObject({ state: "reject", reason: "The paper states it on page 3." });
  });

  it("shows the server's own sentence when it refuses, and says to sign in on a 401, and records nothing on the card", async () => {
    decide.mockResolvedValueOnce({ ok: false, error: { code: "invalid_parameter", message: "a rejected comment needs a one-line reason" } });
    mount(review(THREE));
    fireEvent.click(within(first()).getByRole("button", { name: "Accept" }));
    expect(await within(first()).findByTestId("card-decision-problem")).toHaveTextContent("a rejected comment needs a one-line reason");
    decide.mockResolvedValueOnce({ ok: false, error: { code: "unauthenticated", message: "sign in to continue" } });
    fireEvent.click(within(first()).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(within(first()).getByTestId("card-decision-problem")).toHaveTextContent("Sign in to record a decision."));
    expect(within(first()).getByTestId("card-decision")).toHaveTextContent("Not decided yet");
  });

  it("a confirmation is decided as a confirmation", async () => {
    decide.mockResolvedValue(ok("accept"));
    mount(review([card(1)], [card(5, { severity: "Please confirm" })]));
    const part = screen.getByTestId("general-confirmations");
    fireEvent.click(part.querySelector("summary") as HTMLElement);
    fireEvent.click(within(within(part).getByTestId("general-row")).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(decide).toHaveBeenCalled());
    expect(decide.mock.calls[0][1]).toMatchObject({ comment: 5, part: "confirmation" });
  });

  it("a decision already on record is shown, with how many decisions the comment has", () => {
    const decided = card(1, { decision: { state: "reject", words: "Rejected", text: null, reason: "Not a real problem.", by: "Dana", at: "2026-11-18T12:00:00+00:00", revisions: 3 } });
    mount(review([decided]));
    expect(screen.getByTestId("card-decision-state")).toHaveTextContent("Rejected by Dana");
    expect(screen.getByTestId("card-decision-state")).toHaveTextContent("Not a real problem.");
    expect(screen.getByTestId("card-decision-state")).toHaveTextContent("3 decisions on record; the latest counts");
  });
});

describe("card chips (planner 18 Nov 23:30-3)", () => {
  it("a chip shows the tag, the page and the value; a blank value reads blank", () => {
    const c = card(1, { applies_to: [
      { page: 1, field: "Set pressure (North skid)", quote: "340 psig", tag: "North skid", value: "340 psig" },
      { page: 2, field: "Effective area", quote: "76 Effective area", tag: "", value: "Effective area: blank" },
    ] });
    mount(review([c]));
    expect(screen.getByRole("button", { name: "page 1" })).toHaveTextContent("North skid · p1 · 340 psig");
    expect(screen.getByRole("button", { name: "page 2" })).toHaveTextContent("Effective area · p2 · Effective area: blank");
  });

  it("a long value is cut with a mark and the whole text stays in the chip's title", () => {
    const long = "340 psig (By Contractor, as per Code and the project rules for this unit)";
    const c = card(1, { applies_to: [{ page: 1, field: "Set pressure (Skid one)", quote: long, tag: "Skid one", value: long }] });
    mount(review([c]));
    const chip = screen.getByRole("button", { name: "page 1" });
    expect(chip.textContent).toContain("…");
    expect(chip.getAttribute("title")).toContain(long);
  });
});

describe("paired values tag (A's 1664fa01)", () => {
  it("shows a small tag when the AI paired the values, never inside We ask", () => {
    mount(review([card(1, { we_ask: "State the value on page 2; contractor to confirm the value.", paired: true })]));
    expect(screen.getByTestId("card-paired")).toHaveTextContent("Values paired by the AI; compared by code");
    expect(screen.getByText("State the value on page 2; contractor to confirm the value.")).toBeInTheDocument();
    expect(screen.getByText("State the value on page 2; contractor to confirm the value.")).not.toHaveTextContent("paired");
  });

  it("shows no tag when the values were not paired", () => {
    mount(review([card(1, { paired: false }), card(2)]));
    expect(screen.queryByTestId("card-paired")).toBeNull();
  });
});

