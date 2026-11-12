/**
 * MUTATION PROOF: in agentWords.lineView return the sent word for every
 * class and the "data error" test fails; merge the "rule not yet approved"
 * block into another and the own-block test fails; drop the cursor and the
 * paging test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentLine } from "../../../types/api";
import { AgentLines } from "./AgentLines";
import { CLASS_ORDER, DATA_ERROR_NOTE, displayWord, lineView } from "./agentWords";

const lines = vi.fn();
vi.mock("../../../api/agentReview", () => ({ agentReview: { lines: (...a: unknown[]) => lines(...a) } }));
beforeEach(() => lines.mockReset());

function line(over: Partial<AgentLine>): AgentLine {
  return {
    item_id: "L1", verdict_class: "Proven by code", word: "Pass", page: 3, clause: "4.2", rule_book: "Book A",
    reason: "value agrees", rule_tier: "Engineer", ...over,
  };
}
const ok = (ls: AgentLine[], next: string | null = null) => ({ ok: true, data: { lines: ls, next } });

describe("AgentLines three-line text (order 13)", () => {
  it("shows the three lines of the file's comment, one per line", async () => {
    const three = "Rule requires X.\nThe paper states Y.\nContractor to revise Z.";
    lines.mockResolvedValue(ok([line({ item_id: "T1", reason: three })]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    const cell = await screen.findByTestId("reason-T1");
    expect(cell.textContent).toContain("Rule requires X.\nThe paper states Y.\nContractor to revise Z.");
    expect(cell.className).toContain("whitespace-pre-line");
  });
});

describe("AgentLines", () => {
  it("renders every class and word exactly, each class in its own block", async () => {
    lines.mockResolvedValue(ok([
      line({ item_id: "A", word: "Pass" }),
      line({ item_id: "B", word: "Fail" }),
      line({ item_id: "C", verdict_class: "AI opinion, engineer to confirm", word: "AI thinks: met", rule_tier: "AI approved" }),
      line({ item_id: "D", verdict_class: "AI opinion, rule not yet approved", word: "AI thinks: not met", rule_tier: "Not AI approved" }),
      line({ item_id: "E", verdict_class: "Query for the engineer", word: "Query" }),
      line({ item_id: "F", verdict_class: "Not applicable", word: "Not applicable", page: null }),
      line({ item_id: "G", verdict_class: "AI verdict, two readers agree", word: "AI verdict: not met", rule_tier: "AI approved" }),
    ]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("block-Proven by code");
    const expected: Record<string, [string, string]> = {
      A: ["Proven by code", "Pass"], B: ["Proven by code", "Fail"],
      C: ["AI opinion, engineer to confirm", "AI thinks: met"],
      D: ["AI opinion, rule not yet approved", "AI thinks: not met"],
      E: ["Query for the engineer", "Query"], F: ["Not applicable", "Not applicable"],
      G: ["AI verdict, two readers agree", "AI verdict: not met"],
    };
    for (const [id, [klass, word]] of Object.entries(expected)) {
      const block = screen.getByTestId(`block-${klass}`);
      expect(within(block).getByTestId(`word-${id}`)).toHaveTextContent(new RegExp(`^${displayWord(word).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
    }
    expect(CLASS_ORDER).toHaveLength(10);
    expect(screen.getByRole("table", { name: "AI opinion, rule not yet approved" })).toBeInTheDocument();
  });

  it("the two-readers class carries only its own two words and never Pass or Fail", () => {
    expect(lineView({ verdict_class: "AI verdict, two readers agree", word: "AI verdict: met" }).word).toBe("AI verdict: met");
    expect(lineView({ verdict_class: "AI verdict, two readers agree", word: "Pass" })).toMatchObject({ word: null, dataError: true });
    expect(lineView({ verdict_class: "AI verdict, two readers agree", word: "Fail" })).toMatchObject({ word: null, dataError: true });
    expect(lineView({ verdict_class: "Proven by code", word: "AI verdict: met" })).toMatchObject({ word: null, dataError: true });
    expect(lineView({ verdict_class: "AI opinion, engineer to confirm", word: "AI verdict: not met" })).toMatchObject({ word: null, dataError: true });
  });

  it("never shows Pass or Fail on a line that is not proven, even if the API sent it", async () => {
    lines.mockResolvedValue(ok([
      line({ item_id: "X", verdict_class: "AI opinion, engineer to confirm", word: "Pass" }),
      line({ item_id: "Y", verdict_class: "AI opinion, rule not yet approved", word: "Fail" }),
    ]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("word-X");
    expect(screen.queryByText("Pass")).toBeNull();
    expect(screen.queryByText("Fail")).toBeNull();
    expect(screen.getByTestId("word-X")).toHaveTextContent("AI opinion, engineer to confirm");
    expect(screen.getAllByText(DATA_ERROR_NOTE)).toHaveLength(2);
    // They stay in their own class blocks, not under "Proven by code".
    expect(screen.queryByTestId("block-Proven by code")).toBeNull();
  });

  it("an unknown class is a data error and never shows Pass", () => {
    expect(lineView({ verdict_class: "Made up", word: "Pass" })).toEqual({ klass: null, word: null, dataError: true });
  });

  it("pages by cursor and says what it has loaded", async () => {
    lines.mockResolvedValueOnce(ok([line({ item_id: "P1" })], "cur-2"));
    lines.mockResolvedValueOnce(ok([line({ item_id: "P2", word: "Fail" })], null));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    expect(await screen.findByTestId("agent-lines-boundary")).toHaveTextContent("1 line loaded so far; more lines are waiting.");
    await userEvent.click(screen.getByRole("button", { name: "Load more lines" }));
    expect(lines).toHaveBeenLastCalledWith("r1", "cur-2");
    expect(await screen.findByTestId("word-P2")).toBeInTheDocument();
    expect(screen.getByTestId("agent-lines-boundary")).toHaveTextContent("2 lines loaded so far; that is every line of this review.");
    expect(screen.queryByRole("button", { name: "Load more lines" })).toBeNull();
  });

  it("empty review says so; a click on a line asks for its trace", async () => {
    lines.mockResolvedValueOnce(ok([]));
    const { unmount } = render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    expect(await screen.findByText("This review has no lines.")).toBeInTheDocument();
    unmount();
    lines.mockResolvedValueOnce(ok([line({ item_id: "T1" })]));
    const onOpen = vi.fn();
    render(<AgentLines runId="r1" onOpenTrace={onOpen} />);
    await userEvent.click(await screen.findByRole("button", { name: /^Open the trace of Point/ }));
    expect(onOpen).toHaveBeenCalledWith("T1");
  });
});

describe("AgentLines: Not reviewed and checklist items", () => {
  /** MUTATION PROOF: put "Not reviewed" under Query and this fails. */
  it("Not reviewed has its own block with its note, apart from Query", async () => {
    lines.mockResolvedValue(ok([
      line({ item_id: "N1", verdict_class: "Not reviewed" as never, word: "Not reviewed" as never }),
      line({ item_id: "Q1", verdict_class: "Query for the engineer", word: "Query" }),
    ]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    const nr = await screen.findByTestId("block-Not reviewed");
    expect(within(nr).getByTestId("word-N1")).toHaveTextContent(/^Not reviewed$/);
    expect(nr).toHaveTextContent("the AI gave no answer for these items");
    expect(within(nr).queryByTestId("word-Q1")).toBeNull();
    expect(within(screen.getByTestId("block-Query for the engineer")).getByTestId("word-Q1")).toBeInTheDocument();
  });
  it("a null rule tier (checklist item) renders as checklist item, not blank or null", async () => {
    lines.mockResolvedValue(ok([line({ item_id: "C1", rule_tier: null })]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    expect((await screen.findByText("Checklist item"))).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/null/);
  });
});

describe("AgentLines: guards both ways, tier words, the not-approved block", () => {
  /** MUTATION PROOF: make the guard one-way again and the first test fails. */
  it("Proven by code with an opinion word is a data error and the word is not shown", async () => {
    lines.mockResolvedValue(ok([line({ item_id: "W1", verdict_class: "Proven by code", word: "AI thinks: met" })]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("word-W1");
    expect(screen.queryByText("AI thinks: met")).toBeNull();
    expect(screen.getByTestId("word-W1")).toHaveTextContent(DATA_ERROR_NOTE);
  });
  it("a null tier is Checklist item only where the contract allows it, else tier not given", async () => {
    lines.mockResolvedValue(ok([
      line({ item_id: "T1", rule_tier: null }),
      line({ item_id: "T2", verdict_class: "AI opinion, rule not yet approved", word: "AI thinks: met", rule_tier: null }),
    ]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("word-T1");
    expect(within(screen.getByTestId("word-T1").closest("tr")!).getByText("Checklist item")).toBeInTheDocument();
    expect(within(screen.getByTestId("word-T2").closest("tr")!).getByText("tier not given")).toBeInTheDocument();
  });
  it("the not-yet-approved block says none was asked when there are none (all pages loaded)", async () => {
    lines.mockResolvedValue(ok([line({ item_id: "E1" })]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    expect(await screen.findByTestId("block-empty-not-approved")).toHaveTextContent("No rule was asked that is not AI approved.");
  });
  it("it makes no such claim while more pages wait", async () => {
    lines.mockResolvedValue(ok([line({ item_id: "E1" })], "c2"));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("word-E1");
    expect(screen.queryByTestId("block-empty-not-approved")).toBeNull();
  });
});

describe("AgentLines: general review", () => {
  const g = (over: Partial<AgentLine>) => line({ rule_tier: null, rule_book: "", clause: "", ...over });
  const GEN = "general review" as const;
  /** MUTATION PROOF: drop a class from CLASS_WORDS or the mode check and these fail. */
  it("each new class renders its exact word, in its own block, in the general order", async () => {
    lines.mockResolvedValue(ok([
      g({ item_id: "R1", verdict_class: "Not reviewed", word: "Not reviewed" }),
      g({ item_id: "Q1", verdict_class: "Query for the engineer", word: "Query" }),
      g({ item_id: "N1", verdict_class: "AI note, no rule book", word: "AI note", part: "engineering comment" }),
      g({ item_id: "H1", verdict_class: "Not checked: rule book not held", word: "Not checked", part: "not held" }),
    ]));
    render(<AgentLines runId="r1" mode={GEN} onOpenTrace={() => {}} />);
    await screen.findByTestId("word-H1");
    expect(screen.getByTestId("word-H1")).toHaveTextContent(/^Not checked$/);
    expect(screen.getByTestId("word-N1")).toHaveTextContent(/^AI note$/);
    const order = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent ?? "");
    const idx = (t: string) => order.findIndex((o) => o.includes(t));
    expect(idx("Not checked: rule book not held")).toBeLessThan(idx("AI note, no rule book"));
    expect(idx("AI note, no rule book")).toBeLessThan(idx("Query for the engineer"));
    expect(idx("Query for the engineer")).toBeLessThan(idx("Not reviewed"));
    expect(screen.queryByTestId("block-empty-not-approved")).toBeNull();
  });
  it("shows the Part column in plain words, sorts notes by part, and marks the model's words", async () => {
    lines.mockResolvedValue(ok([
      g({ item_id: "N2", verdict_class: "AI note, no rule book", word: "AI note", part: "engineering comment", text_source: "the model's words" }),
      g({ item_id: "N1", verdict_class: "AI note, no rule book", word: "AI note", part: "paper against itself", text_source: "quote" }),
    ]));
    render(<AgentLines runId="r1" mode={GEN} onOpenTrace={() => {}} />);
    await screen.findByTestId("word-N1");
    expect(screen.getByRole("columnheader", { name: "Part" })).toBeInTheDocument();
    expect(screen.getByText("Paper checked against itself")).toBeInTheDocument();
    expect(screen.getByText("Engineering comment")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    expect(rows.findIndex((r) => r.includes("N1"))).toBeLessThan(rows.findIndex((r) => r.includes("N2")));
    expect(screen.getByTestId("model-words-N2")).toHaveTextContent("the model's words, not a quote");
    expect(screen.queryByTestId("model-words-N1")).toBeNull();
  });
  it("a rule review has no Part column", async () => {
    lines.mockResolvedValue(ok([line({ item_id: "X" })]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("word-X");
    expect(screen.queryByRole("columnheader", { name: "Part" })).toBeNull();
  });
  it("a general review never shows Pass or Fail, even if the API sent them; no proven styling", async () => {
    lines.mockResolvedValue(ok([
      g({ item_id: "P1", verdict_class: "Proven by code", word: "Pass" }),
      g({ item_id: "P2", verdict_class: "AI note, no rule book", word: "Fail", part: "checklist" }),
    ]));
    render(<AgentLines runId="r1" mode={GEN} onOpenTrace={() => {}} />);
    await screen.findByTestId("word-P1");
    expect(screen.queryByText("Pass")).toBeNull();
    expect(screen.queryByText("Fail")).toBeNull();
    expect(screen.getAllByText(DATA_ERROR_NOTE)).toHaveLength(2);
  });
  it("a class the screen does not know shows as unknown class with the data-error note", async () => {
    lines.mockResolvedValue(ok([g({ item_id: "U1", verdict_class: "Future class" as AgentLine["verdict_class"], word: "Future" as AgentLine["word"] })]));
    render(<AgentLines runId="r1" mode={GEN} onOpenTrace={() => {}} />);
    await screen.findByTestId("word-U1");
    expect(screen.getByTestId("word-U1")).toHaveTextContent("unknown class");
    expect(screen.getByTestId("word-U1")).toHaveTextContent(DATA_ERROR_NOTE);
  });
  it("a new class carrying a word of another class is a data error", async () => {
    lines.mockResolvedValue(ok([g({ item_id: "B1", verdict_class: "AI note, no rule book", word: "AI thinks: met" })]));
    render(<AgentLines runId="r1" mode={GEN} onOpenTrace={() => {}} />);
    await screen.findByTestId("word-B1");
    expect(screen.queryByText("AI thinks: met")).toBeNull();
    expect(screen.getByTestId("word-B1")).toHaveTextContent(DATA_ERROR_NOTE);
  });
});

describe("the owner's words for a two-reader verdict", () => {
  it("shows Met / Not met (AI, two readers agree, quotes verified) and every other word as stored", () => {
    expect(displayWord("AI verdict: met")).toBe("Met (AI, two readers agree, quotes verified)");
    expect(displayWord("AI verdict: not met")).toBe("Not met (AI, two readers agree, quotes verified)");
    expect(displayWord("AI verdict: not stated")).toBe("AI verdict: not stated");
    expect(displayWord("Pass")).toBe("Pass");
  });
});
