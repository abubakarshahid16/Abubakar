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
    }, usd: 1.5, models: ["model-a"], stop_reason: null, missing_books: ["Book Z"], ...over,
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
