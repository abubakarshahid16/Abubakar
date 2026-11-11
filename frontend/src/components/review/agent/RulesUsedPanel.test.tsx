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
vi.mock("../../../api/agentReview", () => ({
  agentReview: { rulesUsed: (...a: unknown[]) => rulesUsed(...a) },
  isFeatureOff: (r: { ok: boolean; error?: { code: string } }) => !r.ok && r.error?.code === "not_found",
}));
beforeEach(() => rulesUsed.mockReset());

function data(over: Partial<AgentRulesUsed> = {}): AgentRulesUsed {
  return {
    paper_kind: "datasheet", equipment_type: "pump",
    asked: [
      { rule_book: "Book A", clause: "1.1", quote: "q one", paper_kind: "datasheet", field: "rated flow", equipment: null, tier: "AI approved" },
      { rule_book: "Book B", clause: "2.1", quote: "q two", paper_kind: "datasheet", field: null, equipment: "pump", tier: "Engineer" },
      { rule_book: "Book B", clause: "2.2", quote: "q three", paper_kind: "datasheet", field: "head", equipment: "pump", tier: "Not AI approved" },
      { rule_book: "Book C", clause: "3.1", quote: "q four", paper_kind: "datasheet", field: "x", equipment: "pump", tier: "Owner" },
    ],
    left_out: [
      { rule_book: "Book A", clause: "9.1", reason: "needs another paper" },
      { rule_book: "Book D", clause: "9.2", reason: "needs a human" },
      { rule_book: "Book D", clause: "9.3", reason: "needs a human" },
    ],
    left_out_counts: { "needs another paper": 1, "needs a human": 2 },
    missing_books: [{ name: "Book Q", why: "not in the library" }],
    rule_set_changed_by: null, ...over,
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
