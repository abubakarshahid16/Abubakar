/**
 * CoverageLedger: a null renders NOTHING, a null count is not a 0, and the
 * status enum never reaches the reader. Every fixture asserts the precondition
 * it depends on before rendering, so a fixture that could not produce the
 * condition fails here rather than passing vacuously.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CoverageLedger } from "./CoverageLedger";
import type { AnalysisDocumentRow, AnalysisResult } from "../../types/analysis";

function row(over: Partial<AnalysisDocumentRow> = {}): AnalysisDocumentRow {
  return {
    document_id: "doc_norsok",
    filename: "NORSOK-M-501-Rev5.pdf",
    status: "relevant",
    validated_evidence_count: 3,
    error_code: null,
    ...over,
  };
}

function makeResult(over: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    analysis_id: "an_01",
    question: "What dry film thickness does coating system 1 require?",
    run_status: "complete",
    status: "answered",
    coverage: {
      authorized_documents_selected: 4,
      documents_attempted: 4,
      documents_search_completed: 4,
      relevant_documents: 1,
      no_sufficient_evidence_documents: 2,
      failed_documents: 1,
      not_searchable_documents: 0,
      complete: false,
    },
    documents: [row()],
    evidence_ledger: [],
    documented_findings: [],
    summary: null,
    summary_truncated: false,
    summary_cited_evidence_ids: [],
    claim_clusters: [],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    public_market_findings: [],
    recommendation: null,
    assumptions: [],
    limitations: [],
    not_implemented_sections: [],
    batches_done: null,
    batches_total: null,
    seconds: 4.2,
    ...over,
  };
}

describe("CoverageLedger: complete is false | null, never a positive state", () => {
  it("complete: null renders no 'complete' word and no tick", () => {
    const result = makeResult();
    result.coverage.complete = null;
    expect(result.coverage.complete).toBeNull();

    const { container } = render(<CoverageLedger result={result} />);
    expect(screen.queryByText(/complete/i)).toBeNull();
    expect(container.textContent).not.toMatch(/[✓✔]/);
  });

  it("complete: false says the analysis is partial", () => {
    const result = makeResult();
    expect(result.coverage.complete).toBe(false);
    render(<CoverageLedger result={result} />);
    expect(screen.getByText("This analysis is partial")).toBeInTheDocument();
  });
});

describe("CoverageLedger: null count is not a zero count", () => {
  it("renders a null count as — and a zero count as 0 in the same table", () => {
    const notSearched = row({
      document_id: "doc_failed",
      filename: "failed-scan.pdf",
      status: "failed",
      validated_evidence_count: null,
      error_code: "ocr_timeout",
    });
    const searchedNothing = row({
      document_id: "doc_empty",
      filename: "unrelated-hse-plan.pdf",
      status: "no_sufficient_evidence",
      validated_evidence_count: 0,
    });
    expect(notSearched.validated_evidence_count).toBeNull();
    expect(searchedNothing.validated_evidence_count).toBe(0);

    render(<CoverageLedger result={makeResult({ documents: [notSearched, searchedNothing] })} />);

    const failedRow = screen.getByText("failed-scan.pdf").closest("tr")!;
    expect(within(failedRow).getByLabelText("not searched")).toHaveTextContent("—");
    expect(within(failedRow).queryByText("0")).toBeNull();

    const emptyRow = screen.getByText("unrelated-hse-plan.pdf").closest("tr")!;
    expect(within(emptyRow).getByText("0")).toBeInTheDocument();
    expect(within(emptyRow).queryByText("—")).toBeNull();
  });
});

describe("CoverageLedger: status wording", () => {
  it("renders no_sufficient_evidence as 'Searched, nothing credible', not the enum", () => {
    const r = row({ status: "no_sufficient_evidence", validated_evidence_count: 0 });
    expect(r.status).toBe("no_sufficient_evidence");
    render(<CoverageLedger result={makeResult({ documents: [r] })} />);
    expect(screen.getByText("Searched, nothing credible")).toBeInTheDocument();
    expect(screen.queryByText(/no_sufficient_evidence/)).toBeNull();
  });
});

describe("CoverageLedger: cancelled run", () => {
  it("renders the cancelled sentence and nothing that reads as a summary", () => {
    const result = makeResult({ run_status: "cancelled", status: "cancelled" });
    expect(result.run_status).toBe("cancelled");
    render(<CoverageLedger result={result} />);
    expect(screen.getByText(/Cancelled — partial results below are batches/)).toBeInTheDocument();
    // No summary line, no batch-progress line: cancelled is not "still running".
    expect(screen.queryByText(/summar(y|ised)/i)).toBeNull();
    expect(screen.queryByText(/synthesis/i)).toBeNull();
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
});

describe("CoverageLedger: pagination", () => {
  it("shows 20 of 25 rows, then the remaining 5 after Next", async () => {
    const docs = Array.from({ length: 25 }, (_, i) =>
      row({ document_id: `doc_${i}`, filename: `spec-${String(i).padStart(2, "0")}.pdf` }),
    );
    expect(docs).toHaveLength(25);
    const user = userEvent.setup();
    render(<CoverageLedger result={makeResult({ documents: docs })} pageSize={20} />);

    const body = () => screen.getByRole("table").querySelector("tbody")!;
    expect(body().querySelectorAll("tr")).toHaveLength(20);
    expect(screen.getByText("1–20 of 25 documents")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /next page/i }));
    expect(body().querySelectorAll("tr")).toHaveLength(5);
    expect(screen.getByText("21–25 of 25 documents")).toBeInTheDocument();
    expect(screen.getByText("spec-24.pdf")).toBeInTheDocument();
    expect(screen.queryByText("spec-00.pdf")).toBeNull();
  });
});

describe("CoverageLedger: progress while running", () => {
  it("batches_total: null renders a progress line with no digits", () => {
    const result = makeResult({
      run_status: "synthesising",
      batches_done: null,
      batches_total: null,
    });
    expect(result.batches_total).toBeNull();
    render(<CoverageLedger result={result} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/synthesising/);
    expect(status.textContent).not.toMatch(/\d/);
  });

  it("a measured batches_total renders the fraction", () => {
    const result = makeResult({ run_status: "synthesising", batches_done: 2, batches_total: 5 });
    expect(result.batches_total).toBe(5);
    render(<CoverageLedger result={result} />);
    expect(screen.getByRole("status")).toHaveTextContent("2 of 5 batches synthesised");
  });
});
