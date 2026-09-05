/**
 * SummaryCard: generated prose, counted in passages, with citation markers that
 * are live only when a source stands behind them.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SummaryCard } from "./SummaryCard";
import type { AnalysisResult } from "../../types/analysis";

const IDS = ["ev_a1b2c3d4e5f60718", "ev_0f1e2d3c4b5a6978", "ev_9988776655443322"];

function makeResult(over: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    analysis_id: "an_02",
    question: "Compare the required DFT across the coating specifications.",
    run_status: "complete",
    status: "answered",
    coverage: {
      authorized_documents_selected: 2,
      documents_attempted: 2,
      documents_search_completed: 2,
      relevant_documents: 2,
      no_sufficient_evidence_documents: 0,
      failed_documents: 0,
      not_searchable_documents: 0,
      complete: false,
    },
    documents: [],
    evidence_ledger: [],
    documented_findings: [],
    summary: "Both specifications require 280 µm [S1], one adds a stripe coat [S2].",
    summary_truncated: false,
    summary_cited_evidence_ids: IDS,
    claim_clusters: [],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    public_market_findings: [],
    recommendation: null,
    assumptions: [],
    limitations: [],
    not_implemented_sections: [],
    batches_done: null,
    batches_total: null,
    seconds: 3.1,
    ...over,
  };
}

describe("SummaryCard: null summary", () => {
  it("names the omission in one line when synthesis is not implemented, with no prose block", () => {
    const result = makeResult({ summary: null, not_implemented_sections: ["synthesis"] });
    expect(result.summary).toBeNull();
    expect(result.not_implemented_sections).toContain("synthesis");
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.getByText("Generated summary is not available in this build.")).toBeInTheDocument();
    expect(container.querySelector(".model-prose")).toBeNull();
    expect(screen.queryByText(/Written by the model/)).toBeNull();
  });

  it("renders nothing at all when there is no summary, no omission and no findings", () => {
    const result = makeResult({ summary: null, not_implemented_sections: [], documented_findings: [] });
    expect(result.summary).toBeNull();
    expect(result.documented_findings).toHaveLength(0);
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SummaryCard: header counts passages", () => {
  it("says 'Summary of N passages' with N = cited ids, and never 'documents'", () => {
    const result = makeResult();
    expect(result.summary_cited_evidence_ids).toHaveLength(3);
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    const header = screen.getByText(/^Summary of \d+ passages?$/);
    expect(header).toHaveTextContent("Summary of 3 passages");
    expect(header.textContent).not.toMatch(/documents/i);
  });
});

describe("SummaryCard: citation markers", () => {
  it("a [S9] with no evidence id behind it is struck through and not a button", () => {
    const result = makeResult({ summary: "The stripe coat is optional [S9]." });
    expect(result.summary_cited_evidence_ids[8]).toBeUndefined();
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    const dead = screen.getByLabelText("Citation 9 is not among the supplied sources");
    expect(dead.tagName).not.toBe("BUTTON");
    expect(dead.className).toMatch(/line-through/);
    expect(screen.queryByRole("button", { name: "Show source 9" })).toBeNull();
  });

  it("a [S1] with a matching id is a button and calls onCite with that id", async () => {
    const result = makeResult({ summary: "Both require 280 µm [S1]." });
    expect(result.summary_cited_evidence_ids[0]).toBe(IDS[0]);
    const onCite = vi.fn();
    const user = userEvent.setup();
    render(<SummaryCard result={result} onCite={onCite} />);
    await user.click(screen.getByRole("button", { name: "Show source 1" }));
    expect(onCite).toHaveBeenCalledTimes(1);
    expect(onCite).toHaveBeenCalledWith(IDS[0]);
  });
});

describe("SummaryCard: truncation and findings", () => {
  it("summary_truncated: true renders the truncation notice", () => {
    const result = makeResult({ summary_truncated: true });
    expect(result.summary_truncated).toBe(true);
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.getByText(/reached its length limit and stops early/)).toBeInTheDocument();
  });

  it("does not render the truncation notice when summary_truncated is false", () => {
    const result = makeResult({ summary_truncated: false });
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.queryByText(/reached its length limit/)).toBeNull();
  });

  it("a user_stated finding is labelled as stated by the user", () => {
    const result = makeResult({
      documented_findings: [
        {
          claim: "The project is in the North Sea splash zone.",
          citation_ids: [],
          source_kind: "user_stated",
          text_source: "extracted",
        },
      ],
    });
    expect(result.documented_findings[0].source_kind).toBe("user_stated");
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.getByText(/stated by the user/i)).toBeInTheDocument();
  });
});
