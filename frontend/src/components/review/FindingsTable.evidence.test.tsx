/**
 * #925 item 6: the contractor's cited page, beside each finding, without
 * first opening its full detail. Invented documents only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FindingsTable } from "./FindingsTable";
import type { DocumentRecord, ReviewFinding } from "../../types/api";

const documentCall = vi.fn();
const findingEvidence = vi.fn();
vi.mock("../../api/client", () => ({
  api: { document: (...args: unknown[]) => documentCall(...args) },
  reviews: { findingEvidence: (...args: unknown[]) => findingEvidence(...args) },
}));

// The panes fetch the boxed page from the finding's evidence route; here
// they only say which finding, side and page they would show.
vi.mock("./EvidencePageImage", () => ({
  EvidencePageImage: ({ findingId, side, page }: {
    findingId: string; side: string; page: number;
  }) => <div data-testid="preview">{`${findingId} ${side} p${page}`}</div>,
}));

function finding(over: Partial<ReviewFinding> & { id: string }): ReviewFinding {
  return {
    document_id: "doc_sub", standard_document_id: "doc_std",
    baseline_document_id: null, template_id: null,
    discipline: null, confidence: "medium", category: "requirement_deviation",
    severity: "major", requirement: "A requirement.", finding: "",
    required_action: "", governing_sources: [], unresolved_evidence: [],
    response_text: null, disposition: null, citation_ids: [],
    owner_user_id: null, due_date: null, status: "open",
    approval_status: "pending", approved_by: null, approved_at: null,
    escalation_level: 0, created_by: null, created_at: "", updated_at: "",
    compliance_status: "NEEDS_ENGINEER_REVIEW",
    standard_page: 6, contractor_page: 2,
    contractor_evidence_text: "95 dB(A)",
    ...over,
  } as ReviewFinding;
}

const SUB = { id: "doc_sub", filename: "pump-datasheet.pdf" } as DocumentRecord;
const STD = { id: "doc_std", filename: "std-noise.pdf" } as DocumentRecord;

beforeEach(() => {
  documentCall.mockReset();
  findingEvidence.mockReset();
  findingEvidence.mockResolvedValue({ ok: false, error: { message: "unavailable" } });
});

describe("the evidence toggle", () => {
  it("is collapsed by default and fetches nothing", async () => {
    render(
      <FindingsTable
        findings={[finding({ id: "a" })]} selectedId={null} onSelect={vi.fn()}
        documents={[SUB, STD]}
      />,
    );

    expect(screen.queryByText("Submittal and standard, side by side")).toBeNull();
    expect(documentCall).not.toHaveBeenCalled();
  });

  it("shows both cited pages beside the row on request, without opening the finding", async () => {
    render(
      <FindingsTable
        findings={[finding({ id: "a" })]} selectedId={null} onSelect={vi.fn()}
        documents={[SUB, STD]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Evidence" }));

    expect(await screen.findByText("Submittal and standard, side by side")).toBeInTheDocument();
    expect(screen.getByText("a submittal p2")).toBeInTheDocument();
    expect(screen.getByText("a standard p6")).toBeInTheDocument();
  });

  it("fetches a cited document not already in the page's list, same as the full detail view", async () => {
    documentCall.mockResolvedValue({ ok: true, data: STD });
    render(
      <FindingsTable
        // Only the submittal is already in hand - the standard is not on
        // this page of the Documents list, as happens in practice.
        findings={[finding({ id: "a" })]} selectedId={null} onSelect={vi.fn()}
        documents={[SUB]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Evidence" }));

    expect(await screen.findByText("a standard p6")).toBeInTheDocument();
    expect(documentCall).toHaveBeenCalledWith("doc_std");
  });

  it("does not open the finding's own detail when the toggle is clicked", async () => {
    const onSelect = vi.fn();
    render(
      <FindingsTable
        findings={[finding({ id: "a" })]} selectedId={null} onSelect={onSelect}
        documents={[SUB, STD]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Evidence" }));

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("closes again on request", async () => {
    render(
      <FindingsTable
        findings={[finding({ id: "a" })]} selectedId={null} onSelect={vi.fn()}
        documents={[SUB, STD]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Evidence" }));
    expect(await screen.findByText("Submittal and standard, side by side")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Hide evidence" }));
    expect(screen.queryByText("Submittal and standard, side by side")).toBeNull();
  });
});
