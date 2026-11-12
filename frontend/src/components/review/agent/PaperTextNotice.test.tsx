/**
 * MUTATION PROOF: make paperTextStopped true for "partly readable" and the partly test fails; drop the page list and
 * the pages test fails; show a sentence for "readable" and the readable test fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentPaperText, AgentRulesUsed, AgentRunSummary } from "../../../types/api";
import { AgentSummary } from "./AgentSummary";
import { PaperTextNotice, paperTextStopped } from "./PaperTextNotice";
import { RulesUsedView } from "./RulesUsedPanel";

const NO_TEXT = "This paper has no readable text in the library: re-read it, then review again. No rule was asked and nothing was sent to the AI.";
const stopped: AgentPaperText = { state: "no text", pages_total: 3, pages_not_read: [1, 2, 3], sentence: NO_TEXT };
const partly: AgentPaperText = {
  state: "partly readable", pages_total: 5, pages_not_read: [2, 4],
  sentence: "2 of 5 pages have no stored text and were not read (pages 2, 4). The rules were asked against the other pages only.",
};
const summary = (over: Partial<AgentRunSummary> = {}): AgentRunSummary => ({
  paper_kind: "unknown", paper_kind_source: "no cue found: unknown", equipment_type: null, counts_by_class: {}, usd: null, models: [],
  stop_reason: `no_paper_text: ${NO_TEXT}`, missing_books: [], equipment_state: null, equipment_notes: [], not_reviewed: 0,
  mode: "rule review", project_papers_used: [], paper_text: stopped, ...over,
});
const rules = (over: Partial<AgentRulesUsed> = {}): AgentRulesUsed => ({
  paper_kind: "unknown", equipment_type: null, asked: [], left_out: [], left_out_counts: {}, missing_books: [], rule_set_changed_by: null,
  books: [], equipment_state: null, equipment_notes: [], stop_reason: `no_paper_text: ${NO_TEXT}`, paper_text: stopped, ...over,
});

describe("PaperTextNotice", () => {
  it("a refused paper shows the one sentence as an alert", () => {
    render(<PaperTextNotice paperText={stopped} />);
    expect(screen.getByRole("alert")).toHaveTextContent(NO_TEXT);
    expect(paperTextStopped(stopped)).toBe(true);
    expect(paperTextStopped({ ...stopped, state: "not indexed" })).toBe(true);
  });
  it("a partly readable paper is not a stop and lists the pages not read", () => {
    render(<PaperTextNotice paperText={partly} />);
    expect(paperTextStopped(partly)).toBe(false);
    expect(screen.getByTestId("paper-text-partly")).toHaveTextContent("2 of 5 pages");
    expect(screen.getByTestId("paper-text-pages")).toHaveTextContent("Pages not read: 2, 4");
  });
  it("a readable paper, or a run stored before this was kept, shows nothing", () => {
    const { container, rerender } = render(<PaperTextNotice paperText={{ state: "readable", pages_total: 2, pages_not_read: [], sentence: null }} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PaperTextNotice paperText={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the AI review screen and Rules used say it", () => {
  it("the summary shows the sentence once, not the generic 'stopped early' banner", () => {
    render(<AgentSummary summary={summary()} />);
    expect(screen.getByTestId("paper-text-stop")).toHaveTextContent(NO_TEXT);
    expect(screen.queryByTestId("agent-stop-reason")).toBeNull();
  });
  it("the summary of a partly readable paper still runs: its stop banner is untouched and the pages are listed", () => {
    render(<AgentSummary summary={summary({ paper_text: partly, stop_reason: "spend cap reached" })} />);
    expect(screen.getByTestId("paper-text-pages")).toHaveTextContent("2, 4");
    expect(screen.getByTestId("agent-stop-reason")).toHaveTextContent("spend cap reached");
  });
  it("Rules used never says '0 rules' without words: it gives the sentence", () => {
    render(<RulesUsedView data={rules()} />);
    expect(screen.getByTestId("paper-text-stop")).toHaveTextContent(NO_TEXT);
    expect(screen.getByTestId("asked-empty")).toHaveTextContent(`No rule was asked. ${NO_TEXT}`);
  });
  it("Rules used gives any other stop reason for an empty list", () => {
    render(<RulesUsedView data={rules({ paper_text: null, stop_reason: "refused: the item list failed its checks (1 problem(s))" })} />);
    expect(screen.getByTestId("asked-empty")).toHaveTextContent("No rule was asked: refused: the item list failed its checks");
  });
});
