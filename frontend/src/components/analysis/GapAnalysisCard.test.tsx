/**
 * GapAnalysisCard: the baseline comes from the user, a typed requirement is not
 * evidence, and "met" is only ever what the backend said.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GapAnalysisCard } from "./GapAnalysisCard";
import type { GapAnalysis, GapItem } from "../../types/analysis";

const DOCS = [
  { id: "doc_norsok", filename: "NORSOK-M-501-Rev5.pdf" },
  { id: "doc_project", filename: "Project-Coating-Spec.pdf" },
];

const REVIEW = "Review and approval by a qualified engineer is required.";

function makeItem(over: Partial<GapItem> = {}): GapItem {
  return {
    facet: "Nominal DFT",
    status: "possible_gap",
    baseline_citation_id: "ev_1111222233334444",
    baseline_span: "Coating system no. 1 shall have a nominal dry film thickness of 280 um.",
    project_citation_ids: [],
    note: null,
    ...over,
  };
}

function applicable(items: GapItem[]): GapAnalysis {
  return {
    applicability: "applicable",
    baseline: { kind: "document", document_id: "doc_norsok", section: null, text: null },
    items,
  };
}

const INSUFFICIENT: GapAnalysis = { applicability: "insufficient_baseline", baseline: null, items: [] };

describe("GapAnalysisCard: insufficient baseline", () => {
  it("explains the need for a baseline and disables submit until a document or text is chosen", () => {
    expect(INSUFFICIENT.applicability).toBe("insufficient_baseline");
    render(
      <GapAnalysisCard gaps={INSUFFICIENT} onNominateBaseline={vi.fn()} documents={DOCS} onCite={vi.fn()} />,
    );
    expect(screen.getByText(/Gap analysis needs a baseline/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use as baseline" })).toBeDisabled();
  });

  it("renders no form when onNominateBaseline is not supplied", () => {
    render(<GapAnalysisCard gaps={INSUFFICIENT} documents={DOCS} onCite={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Use as baseline" })).toBeNull();
  });

  it("choosing a document enables submit", async () => {
    const user = userEvent.setup();
    render(
      <GapAnalysisCard gaps={INSUFFICIENT} onNominateBaseline={vi.fn()} documents={DOCS} onCite={vi.fn()} />,
    );
    await user.selectOptions(screen.getByLabelText("Baseline document"), "doc_norsok");
    expect(screen.getByRole("button", { name: "Use as baseline" })).toBeEnabled();
  });

  it("typing a requirement says it is the requirement, not evidence", async () => {
    const user = userEvent.setup();
    render(
      <GapAnalysisCard gaps={INSUFFICIENT} onNominateBaseline={vi.fn()} documents={DOCS} onCite={vi.fn()} />,
    );
    expect(screen.queryByText(/This is the requirement, not evidence/)).toBeNull();
    await user.type(screen.getByLabelText("Or state the requirement"), "DFT shall be at least 300 µm");
    expect(screen.getByText(/This is the requirement, not evidence/)).toBeInTheDocument();
  });

  it("submitting a typed requirement nominates a stated_requirement with no document", async () => {
    const onNominate = vi.fn();
    const user = userEvent.setup();
    render(
      <GapAnalysisCard gaps={INSUFFICIENT} onNominateBaseline={onNominate} documents={DOCS} onCite={vi.fn()} />,
    );
    await user.type(screen.getByLabelText("Or state the requirement"), "DFT shall be at least 300 µm");
    await user.click(screen.getByRole("button", { name: "Use as baseline" }));
    expect(onNominate).toHaveBeenCalledTimes(1);
    expect(onNominate).toHaveBeenCalledWith({
      kind: "stated_requirement",
      document_id: null,
      section: null,
      text: "DFT shall be at least 300 µm",
    });
  });
});

describe("GapAnalysisCard: applicable", () => {
  it("a possible_gap item says 'possible' and carries the retrieval caption", () => {
    const item = makeItem({ status: "possible_gap" });
    expect(item.status).toBe("possible_gap");
    render(<GapAnalysisCard gaps={applicable([item])} documents={DOCS} onCite={vi.fn()} />);
    expect(screen.getByText("Possible gap")).toBeInTheDocument();
    expect(
      screen.getByText("Retrieval found nothing addressing this. That is not proof the documents say nothing."),
    ).toBeInTheDocument();
  });

  it("renders the engineer approval sentence", () => {
    render(<GapAnalysisCard gaps={applicable([makeItem()])} documents={DOCS} onCite={vi.fn()} />);
    expect(screen.getByText(REVIEW)).toBeInTheDocument();
  });

  it("a met item says positive matching evidence was found", () => {
    const item = makeItem({ status: "met", project_citation_ids: ["ev_5555666677778888"] });
    expect(item.status).toBe("met");
    render(<GapAnalysisCard gaps={applicable([item])} documents={DOCS} onCite={vi.fn()} />);
    expect(screen.getByText("Met")).toBeInTheDocument();
    expect(screen.getByText("Positive matching evidence was found.")).toBeInTheDocument();
    expect(screen.queryByText(/Possible gap/)).toBeNull();
  });
});
