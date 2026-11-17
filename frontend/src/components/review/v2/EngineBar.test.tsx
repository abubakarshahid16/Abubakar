import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EngineBar } from "./EngineBar";

const plan = vi.fn();
const start = vi.fn();
vi.mock("../../../api/reviewPoints", async (orig) => ({
  ...(await orig<typeof import("../../../api/reviewPoints")>()),
  reviewPoints: { plan: (...a: unknown[]) => plan(...a), start: (...a: unknown[]) => start(...a) },
}));

const LOCAL_WORDS = "The general review needs Claude. Invented sentence from the plan.";
const base = {
  method: "general", parts: [{ name: "rule_check", engine: "not_run", why: "the earlier rule check is switched off" }],
  needs_yes: false, unscored: false, wont_run: [], kind: "datasheet", notes: [], sentence: "s", contract_yes: null,
  cost: { at_most_usd: 5, by_part_at_most_usd: { rule_check: null, ai_review: 5 }, basis: "b", last_review_usd: null, last_review_note: null, exact: false },
};
const general = (engine: string) => engine === "local"
  ? { ok: true, data: { ...base, choice: "local", text_leaves: false, refused: LOCAL_WORDS, refused_code: "GENERAL_NOT_ON_LOCAL",
      parts: [...base.parts, { name: "ai_review", engine: "not_run", why: LOCAL_WORDS }],
      cost: { ...base.cost, at_most_usd: null }, documents: { paper: false, rule_books: [], rule_books_note: null, leaving: [], not_sent: [], not_readable: 0 } } }
  : { ok: true, data: { ...base, choice: engine, text_leaves: true, refused: null, refused_code: null,
      parts: [...base.parts, { name: "ai_review", engine: "claude", why: "the general review reads the paper on Claude" }],
      documents: { paper: true, rule_books: ["invented-book.pdf"], rule_books_note: "n",
        leaving: [{ id: "p1", title: "invented-paper.pdf", kind: "paper", why: "paper under review" },
                  { id: "b1", title: "invented-book.pdf", kind: "rule book", why: "cited by the paper" }],
        not_sent: [{ name: "Invented Public Standard 1", kind: "rule book", why: "cited by the paper", reason: "not held in the library" }],
        not_readable: 1 } } };

beforeEach(() => { plan.mockReset(); start.mockReset(); plan.mockImplementation(async (_d: string, e: string) => general(e)); });

describe("EngineBar with the general review (order 14)", () => {
  it("lists the paper and the rule books the review may send before the start", async () => {
    render(<EngineBar documentId="p1" isAdmin onStarted={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("v2-leaving").textContent).toContain("invented-book.pdf"));
    expect(screen.getByTestId("v2-leaving").textContent).toContain("invented-paper.pdf");
    expect(screen.getByTestId("v2-engine-line").textContent).toContain("1 rule book");
  });

  it("shows the Local-only sentence once and offers no start", async () => {
    render(<EngineBar documentId="p1" isAdmin onStarted={() => {}} />);
    await waitFor(() => screen.getByTestId("v2-engine-line"));
    fireEvent.click(screen.getByRole("radio", { name: "Local only" }));
    await waitFor(() => expect(screen.getByTestId("v2-engine-line").textContent).toContain(LOCAL_WORDS));
    expect(screen.getByTestId("v2-engine-line").textContent?.split(LOCAL_WORDS).length).toBe(2);
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
  });
});
