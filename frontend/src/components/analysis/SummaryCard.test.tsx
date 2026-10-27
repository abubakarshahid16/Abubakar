/**
 * SummaryCard: generated prose, counted in passages, with citation markers that
 * are live only when a source stands behind them.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SummaryCard } from "./SummaryCard";
import { summaryBoundary } from "./summaryBoundary";
import { toAnalysisResult } from "../../views/analysis/analysisModel";
import type { AnalysisResult, EvidenceItem } from "../../types/analysis";

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

describe("SummaryCard: evidence removal", () => {
  it("explains evidence removed before the summary was written", () => {
    render(<SummaryCard result={makeResult({ evidence_removed: [{ index: 2, filename: "appendix.pdf", page_start: 9, action: "dropped", characters_kept: 0, characters_dropped: 1200 }] })} onCite={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("appendix.pdf");
    expect(screen.getByRole("status")).toHaveTextContent("not used");
  });
});

describe("SummaryCard: null summary", () => {
  it("renders no prose block and no claim about why, when there is no summary", () => {
    // Stage 3 shipped synthesis, so the API never sends "synthesis" in
    // not_implemented_sections and the card must not say it is unavailable.
    // A null summary renders as NOTHING rather than as a sentence explaining
    // itself: this card does not know whether synthesis was refused, was not
    // run, or produced nothing, and guessing would be a claim.
    const result = makeResult({ summary: null, not_implemented_sections: ["synthesis"] });
    expect(result.summary).toBeNull();
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.queryByText(/not available in this build/)).toBeNull();
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

function ledgerFor(ids: string[], documents: string[]): EvidenceItem[] {
  return ids.map((id, i) => ({
    evidence_id: id,
    document_id: documents[i],
    filename: `${documents[i]}.pdf`,
    page_start: 1,
    page_end: 1,
    section: null,
    exact_span: "invented passage",
    text_source: "extracted" as const,
    ocr_min_conf: null,
    ocr_alphabet_violations: 0,
    relevance_score: null,
    relevance_score_type: null,
  }));
}

describe("SummaryCard: the summary states its boundary (#1026)", () => {
  const inScope = (n: number) => ({ ...makeResult().coverage, authorized_documents_selected: n });

  it("says how many of the documents in scope the cited passages come from", () => {
    const result = makeResult({
      evidence_ledger: ledgerFor(IDS, ["doc_a", "doc_a", "doc_b"]),
      coverage: inScope(5),
    });
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.getByTestId("summary-boundary")).toHaveTextContent(
      "Passages from 2 of the 5 documents this search could reach (the ones you can read)",
    );
    // The header still counts passages only, as before.
    expect(screen.getByText(/^Summary of \d+ passages?$/)).toHaveTextContent("Summary of 3 passages");
  });

  it("singular: one document in scope", () => {
    const result = makeResult({
      evidence_ledger: ledgerFor(IDS, ["doc_a", "doc_a", "doc_a"]),
      coverage: inScope(1),
    });
    expect(summaryBoundary(result)).toBe("Passages from 1 of the 1 document this search could reach (the ones you can read)");
  });

  it("states nothing when a cited passage is not in the ledger (never a guessed or zero count)", () => {
    const result = makeResult({
      evidence_ledger: ledgerFor(IDS.slice(0, 2), ["doc_a", "doc_b"]),
      coverage: inScope(5),
    });
    expect(summaryBoundary(result)).toBeNull();
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.queryByTestId("summary-boundary")).toBeNull();
  });

  it("states nothing for a placeholder 0, a missing count, or more documents cited than in scope", () => {
    const ledger = ledgerFor(IDS, ["a", "b", "c"]);
    expect(summaryBoundary(makeResult({ evidence_ledger: ledger, coverage: inScope(0) }))).toBeNull();
    const noCount = makeResult({ evidence_ledger: ledger });
    (noCount.coverage as unknown as Record<string, unknown>).authorized_documents_selected = null;
    expect(summaryBoundary(noCount)).toBeNull();
    expect(summaryBoundary(makeResult({ evidence_ledger: ledger, coverage: inScope(2) }))).toBeNull();
  });

  it("states nothing when a cited passage has no document, or nothing is cited", () => {
    const noDocument = ledgerFor(IDS, ["a", "b", "c"]);
    (noDocument[1] as unknown as Record<string, unknown>).document_id = null;
    expect(summaryBoundary(makeResult({ evidence_ledger: noDocument, coverage: inScope(3) }))).toBeNull();
    expect(summaryBoundary(makeResult({ summary_cited_evidence_ids: [], coverage: inScope(3) }))).toBeNull();
  });
});

describe("SummaryCard: the line reaches the live hub (#1026)", () => {
  // What the hub really does: the route response goes through toAnalysisResult, which used to
  // hard-code an empty ledger and a 0 count, so the line could never render.
  const response = (extra: Record<string, unknown> = {}) =>
    ({
      question: "Compare the required DFT.",
      evidence_ledger: ledgerFor(IDS, ["doc_a", "doc_a", "doc_b"]),
      summary: "Both require 280 µm [S1].",
      summary_truncated: false,
      summary_cited_evidence_ids: IDS,
      documented_findings: [],
      evidence_removed: [],
      not_implemented_sections: [],
      applied_scope: { applied: false, types: [], disciplines: [], subject_ids: [], documents_in_scope: 4 },
      ...extra,
    }) as unknown as Parameters<typeof toAnalysisResult>[0];

  it("renders the boundary from the server's own ledger and scope count", () => {
    const result = toAnalysisResult(response(), "Both require 280 µm [S1].", []);
    expect(result.evidence_ledger).toHaveLength(3);
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.getByTestId("summary-boundary")).toHaveTextContent(
      "Passages from 2 of the 4 documents this search could reach (the ones you can read)",
    );
  });

  it("renders nothing when the server sent no scope count (placeholder 0 is absent)", () => {
    const result = toAnalysisResult(response({ applied_scope: undefined }), "Both require 280 µm [S1].", []);
    expect(result.coverage.authorized_documents_selected).toBe(0);
    render(<SummaryCard result={result} onCite={vi.fn()} />);
    expect(screen.queryByTestId("summary-boundary")).toBeNull();
  });
});
