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

describe("EngineBar: held Schedules the paper cites", () => {
  const OFFER = { id: "s1", title: "invented-schedule.pdf", part: "Schedule C", why: "cited by this paper; tick to compare it" };
  const withOffer = (engine: string, ticked: string[]) => {
    const g = general(engine) as { ok: boolean; data: { documents: Record<string, unknown> & { leaving: unknown[] } } };
    if (engine === "local") return g;
    const on = ticked.includes("s1");
    return { ...g, data: { ...g.data, documents: { ...g.data.documents,
      leaving: on ? [...g.data.documents.leaving, { id: "s1", title: OFFER.title, kind: "reference paper", why: "cited by this paper; chosen by you to compare" }] : g.data.documents.leaving,
      offered: [{ ...OFFER, ticked: on }] } } };
  };

  it("ticking re-asks the plan with the id and the start carries it; unticked it carries nothing extra", async () => {
    plan.mockImplementation(async (_d: string, e: string, ticked: string[] = []) => withOffer(e, ticked));
    start.mockResolvedValue({ ok: true, data: { review_run_id: "run1" } });
    render(<EngineBar documentId="p1" isAdmin onStarted={() => {}} />);
    const box = await screen.findByRole("checkbox", { name: "Compare Schedule C" });
    expect(box).not.toBeChecked();
    expect(screen.getByText(/cited by this paper; tick to compare it/)).toBeInTheDocument();
    fireEvent.click(box);
    await waitFor(() => expect(plan).toHaveBeenLastCalledWith("p1", "automatic", ["s1"]));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Compare Schedule C" })).toBeChecked());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("p1", "automatic", ["p1", "b1", "s1"], ["s1"]));
  });

  it("offers nothing under Local only and forgets a tick when the engine changes", async () => {
    plan.mockImplementation(async (_d: string, e: string, ticked: string[] = []) => withOffer(e, ticked));
    render(<EngineBar documentId="p1" isAdmin onStarted={() => {}} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Compare Schedule C" }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Compare Schedule C" })).toBeChecked());
    fireEvent.click(screen.getByRole("radio", { name: "Local only" }));
    await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Compare Schedule C" })).toBeNull());
    fireEvent.click(screen.getByRole("radio", { name: "Claude" }));
    expect((await screen.findByRole("checkbox", { name: "Compare Schedule C" }))).not.toBeChecked();
  });
});

describe("EngineBar with no paper to plan for", () => {
  it("never says it is checking what a review would do when there is no paper (it would never settle)", () => {
    plan.mockReset();
    render(<EngineBar documentId={null} isAdmin onStarted={vi.fn()} />);
    expect(screen.queryByText(/Checking what this would do/)).toBeNull();
    expect(plan).not.toHaveBeenCalled();
  });
});

describe("EngineBar: a paper Automatic holds back has a way forward", () => {
  it("offers one click to choose Claude, and that switches the engine and asks for the Claude plan", async () => {
    plan.mockReset();
    plan.mockImplementation(async (_d: string, engine: string) => engine === "automatic"
      ? { ok: true, data: { ...base, choice: "automatic", text_leaves: false, refused: "Automatic will not send this paper to Claude on its own: choose Claude to send it", refused_code: "UNSCORED",
          documents: { paper: false, rule_books: [], rule_books_note: null, leaving: [], not_sent: [], not_readable: 0 } } }
      : general(engine));
    render(<EngineBar documentId="doc1" isAdmin onStarted={vi.fn()} />);
    const button = await screen.findByTestId("v2-choose-claude");
    fireEvent.click(button);
    await waitFor(() => expect(plan).toHaveBeenCalledWith("doc1", "claude"));
    expect(screen.queryByTestId("v2-choose-claude")).toBeNull();
  });

  it("offers nothing when the plan is not held back", async () => {
    plan.mockReset();
    plan.mockImplementation(async (_d: string, engine: string) => general(engine));
    render(<EngineBar documentId="doc1" isAdmin onStarted={vi.fn()} />);
    await waitFor(() => expect(plan).toHaveBeenCalled());
    expect(screen.queryByTestId("v2-choose-claude")).toBeNull();
  });
});

