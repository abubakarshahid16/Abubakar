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
import { CLASS_ORDER, DATA_ERROR_NOTE, lineView } from "./agentWords";

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

describe("AgentLines", () => {
  it("renders every class and word exactly, each class in its own block", async () => {
    lines.mockResolvedValue(ok([
      line({ item_id: "A", word: "Pass" }),
      line({ item_id: "B", word: "Fail" }),
      line({ item_id: "C", verdict_class: "AI opinion, engineer to confirm", word: "AI thinks: met", rule_tier: "AI approved" }),
      line({ item_id: "D", verdict_class: "AI opinion, rule not yet approved", word: "AI thinks: not met", rule_tier: "Not AI approved" }),
      line({ item_id: "E", verdict_class: "Query for the engineer", word: "Query" }),
      line({ item_id: "F", verdict_class: "Not applicable", word: "Not applicable", page: null }),
    ]));
    render(<AgentLines runId="r1" onOpenTrace={() => {}} />);
    await screen.findByTestId("block-Proven by code");
    const expected: Record<string, [string, string]> = {
      A: ["Proven by code", "Pass"], B: ["Proven by code", "Fail"],
      C: ["AI opinion, engineer to confirm", "AI thinks: met"],
      D: ["AI opinion, rule not yet approved", "AI thinks: not met"],
      E: ["Query for the engineer", "Query"], F: ["Not applicable", "Not applicable"],
    };
    for (const [id, [klass, word]] of Object.entries(expected)) {
      const block = screen.getByTestId(`block-${klass}`);
      expect(within(block).getByTestId(`word-${id}`)).toHaveTextContent(new RegExp(`^${word}$`));
    }
    expect(CLASS_ORDER).toHaveLength(6);
    expect(screen.getByRole("table", { name: "AI opinion, rule not yet approved" })).toBeInTheDocument();
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
    expect(lineView({ verdict_class: "Made up" as never, word: "Pass" })).toEqual({ klass: null, word: null, dataError: true });
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
    await userEvent.click(await screen.findByRole("button", { name: "Open the trace of line T1" }));
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
    expect((await screen.findByText("checklist item"))).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/null/);
  });
});
