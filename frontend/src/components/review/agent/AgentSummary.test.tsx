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
