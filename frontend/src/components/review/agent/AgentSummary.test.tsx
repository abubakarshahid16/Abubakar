/**
 * MUTATION PROOF: render `usd ?? 0` and the null-cost test fails; sum the
 * classes into one number and the apart-counts test fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentRunSummary } from "../../../types/api";
import { AgentSummary } from "./AgentSummary";

function summary(over: Partial<AgentRunSummary> = {}): AgentRunSummary {
  return {
    paper_kind: "datasheet", paper_kind_source: "title page", equipment_type: "pump", counts_by_class: {
      "Proven by code": 4, "AI opinion, engineer to confirm": 2, "AI opinion, rule not yet approved": 1,
    }, usd: 1.5, models: ["model-a"], stop_reason: null, missing_books: ["Book Z"], equipment_state: null, equipment_notes: [], not_reviewed: 0, mode: "rule review", project_papers_used: [], ...over,
  };
}

describe("AgentSummary", () => {
  it("shows paper kind and how it was decided, equipment, cost and the missing books", () => {
    render(<AgentSummary summary={summary()} />);
    expect(screen.getByText(/datasheet/)).toBeInTheDocument();
    expect(screen.getByText(/decided by: title page/)).toBeInTheDocument();
    expect(screen.getByText("pump")).toBeInTheDocument();
    expect(screen.getByText("USD 1.50")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rule books we do not hold" })).toBeInTheDocument();
    expect(screen.getByText("Book Z")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-stop-reason")).toBeNull();
  });
  it("counts each class apart, with no percentage", () => {
    const { container } = render(<AgentSummary summary={summary()} />);
    expect(screen.getByTestId("count-Proven by code")).toHaveTextContent("Proven by code: 4");
    expect(screen.getByTestId("count-AI opinion, rule not yet approved")).toHaveTextContent(": 1");
    expect(container.textContent).not.toMatch(/%/);
  });
  it("a null cost renders nothing, never 0; a null equipment type says not known", () => {
    render(<AgentSummary summary={summary({ usd: null, equipment_type: null })} />);
    expect(screen.queryByText("Cost")).toBeNull();
    expect(screen.queryByText(/USD/)).toBeNull();
    expect(screen.getByText("not known")).toBeInTheDocument();
  });
  it("says why a run stopped early", () => {
    render(<AgentSummary summary={summary({ stop_reason: "spend cap reached" })} />);
    expect(screen.getByTestId("agent-stop-reason")).toHaveTextContent("stopped early: spend cap reached");
  });
  it("states that the second reading of pages stopped early, with the count; null renders nothing, never 0", () => {
    const { rerender } = render(<AgentSummary summary={summary({ page_reread_stopped: { why: "a spending cap refused a call", not_reread: 3 } })} />);
    expect(screen.getByTestId("agent-page-reread-stopped")).toHaveTextContent("The second reading of pages stopped early: 3 lines were not re-read");
    rerender(<AgentSummary summary={summary({ page_reread_stopped: null })} />);
    expect(screen.queryByTestId("agent-page-reread-stopped")).toBeNull();
    rerender(<AgentSummary summary={summary()} />);
    expect(screen.queryByText(/second reading/)).toBeNull();
  });
  it("honest empty states", () => {
    render(<AgentSummary summary={summary({ counts_by_class: {}, missing_books: [] })} />);
    expect(screen.getByText("No lines were written for this review.")).toBeInTheDocument();
    expect(screen.getByText(/None: every rule book/)).toBeInTheDocument();
  });
});

describe("AgentSummary: Not reviewed", () => {
  it("counts Not reviewed on its own line with its meaning", () => {
    render(<AgentSummary summary={summary({ counts_by_class: { "Query for the engineer": 2, "Not reviewed": 3 } })} />);
    expect(screen.getByTestId("count-Not reviewed")).toHaveTextContent("Not reviewed: 3 (the AI gave no answer for these items)");
    expect(screen.getByTestId("count-Query for the engineer")).toHaveTextContent("Query for the engineer: 2");
  });
});

describe("AgentSummary: equipment notes", () => {
  it("shows the true sentences about the paper's equipment, and none when there are none", () => {
    const { rerender } = render(<AgentSummary summary={summary({ equipment_notes: ["The paper names equipment the equipment list does not know; 12 rules were left out for it."] })} />);
    expect(screen.getByTestId("equipment-notes")).toHaveTextContent("12 rules were left out for it");
    rerender(<AgentSummary summary={summary()} />);
    expect(screen.queryByTestId("equipment-notes")).toBeNull();
  });
});

describe("AgentSummary: mode and project papers", () => {
  it("a rule review says Rule review and shows no project paper line", () => {
    render(<AgentSummary summary={summary()} />);
    expect(screen.getByTestId("agent-mode")).toHaveTextContent(/^Rule review$/);
    expect(screen.queryByTestId("agent-project-papers")).toBeNull();
  });
  it("a general review says so in plain words and names the project papers, or says none was given", () => {
    const { rerender } = render(<AgentSummary summary={summary({ mode: "general review", project_papers_used: [{ document_id: "d1", name: "Paper A" }, { document_id: "d2", name: "Paper B" }] })} />);
    expect(screen.getByTestId("agent-mode")).toHaveTextContent("General review: no rule book held; AI notes and queries only, internal");
    expect(screen.getByTestId("agent-project-papers")).toHaveTextContent("Project papers used: Paper A, Paper B");
    rerender(<AgentSummary summary={summary({ mode: "general review" })} />);
    expect(screen.getByTestId("agent-project-papers")).toHaveTextContent("No project paper was given to check against");
  });
  it("counts the two general-review classes apart", () => {
    render(<AgentSummary summary={summary({ mode: "general review", counts_by_class: { "Not checked: rule book not held": 4, "AI note, no rule book": 9 } })} />);
    expect(screen.getByTestId("count-Not checked: rule book not held")).toHaveTextContent(": 4");
    expect(screen.getByTestId("count-AI note, no rule book")).toHaveTextContent(": 9");
  });
});

describe("AgentSummary: two readers agree", () => {
  it("counts the class apart from Pass and Fail and says what the second-reader step did", () => {
    render(<AgentSummary summary={summary({
      counts_by_class: { "Proven by code": 2, "AI verdict, two readers agree": 3 },
      two_reader_step: { candidates: 5, asked: 5, calls: 1, agreed: 3, disagreed: 1, unconfirmed: 1, skipped: 0, off: null },
    })} />);
    expect(screen.getByTestId("count-AI verdict, two readers agree")).toHaveTextContent("AI verdict, two readers agree: 3");
    expect(screen.getByTestId("count-Proven by code")).toHaveTextContent("Proven by code: 2");
    expect(screen.getByTestId("two-reader-step")).toHaveTextContent("5 lines were candidates, 5 asked in 1 calls; 3 agreed, 1 disagreed, 1 not confirmed.");
  });
  it("says when the step was switched off for the rest of the run", () => {
    render(<AgentSummary summary={summary({
      two_reader_step: { candidates: 4, asked: 0, calls: 0, agreed: 0, disagreed: 0, unconfirmed: 0, skipped: 0, off: "cap_refused" },
    })} />);
    expect(screen.getByTestId("two-reader-step")).toHaveTextContent("switched off for the rest of this run (cap refused)");
  });
  it("shows nothing about the step when the run has none", () => {
    render(<AgentSummary summary={summary()} />);
    expect(screen.queryByTestId("two-reader-step")).toBeNull();
  });
});

describe("AgentSummary: decisions", () => {
  it("states the one count of decisions: code Pass/Fail plus two-reader verdicts", () => {
    render(<AgentSummary summary={summary({ decisions: { code: 2, two_reader: 5, not_stated: 2, total: 7 } })} />);
    expect(screen.getByTestId("agent-decisions")).toHaveTextContent("Decisions: 7 = code Pass/Fail 2 + two-reader verdicts 5; of which: not stated on the paper 2");
  });
  it("prints no 'of which' when no line is not stated", () => {
    render(<AgentSummary summary={summary({ decisions: { code: 2, two_reader: 5, not_stated: 0, total: 7 } })} />);
    expect(screen.getByTestId("agent-decisions")).not.toHaveTextContent("of which");
  });
  it("shows nothing for a run stored before it", () => {
    render(<AgentSummary summary={summary()} />);
    expect(screen.queryByTestId("agent-decisions")).toBeNull();
  });
});
