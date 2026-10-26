/**
 * Order 225: every row opens the standard at its page, or says plainly that the
 * page was not located (never a page 1 in its place). Invented documents only.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewFinding } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

vi.mock("../../api/client", () => ({
  api: { document: vi.fn(async () => ({ ok: false, error: { message: "not found" } })) },
  reviews: {
    update: vi.fn(), decideCrsFinding: vi.fn(), confirm: vi.fn(), rejectPairing: vi.fn(),
    findingEvidence: vi.fn(async () => ({ ok: false, error: { message: "unavailable" } })),
  },
}));
vi.mock("./EvidencePageImage", () => ({ EvidencePageImage: () => <div /> }));
vi.mock("../DocumentPreview", () => ({ DocumentPreview: () => <div /> }));

const SUB = { id: "doc-sub", filename: "valve-datasheet.pdf" } as DocumentRecord;
const STD = { id: "doc-std", filename: "API-520-I.pdf" } as DocumentRecord;

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id: "f-1", review_run_id: "run-1", document_id: "doc-sub", standard_document_id: "doc-std",
    finding: "the MAWP is not stated", requirement: "MAWP is stated",
    requirement_source_text: "Datasheet check PSV-02: the MAWP is stated.",
    contractor_section: "MAWP", contractor_evidence_text: null, contractor_page: 1,
    standard_page: 14, standard_clause: "API 520-I 3.26", compliance_status: "MISSING_INFORMATION",
    confirmed_by: null, confirmed_at: null, engineer_comment: null, approval_status: null,
    requirement_id: null, fact_id: null, ...over,
  } as unknown as ReviewFinding;
}

beforeEach(() => vi.clearAllMocks());

describe("the standard link on a row", () => {
  it("a located clause opens the standard at its page and the datasheet at its page", () => {
    render(<FindingDetail finding={finding()} documents={[SUB, STD]} onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Open standard at page 14" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open datasheet at page 1" })).toBeInTheDocument();
    expect(screen.queryByText("standard page not located")).toBeNull();
  });

  it("a checklist clause that was not located (no standard, no page stored) says so", () => {
    render(
      <FindingDetail
        finding={finding({ standard_page: null, standard_document_id: null })} documents={[SUB]} onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText("standard page not located")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open (the )?standard/ })).toBeNull();
  });

  it("a requirement row whose standard is known but whose page is not says so and offers no invented page", () => {
    render(<FindingDetail finding={finding({ standard_page: null })} documents={[SUB, STD]} onChanged={vi.fn()} />);
    expect(screen.getByText("standard page not located")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the standard" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open standard at page/ })).toBeNull();
  });

  it("a row that cites no clause says nothing about a page", () => {
    render(
      <FindingDetail
        finding={finding({ standard_page: null, standard_clause: null })} documents={[SUB, STD]} onChanged={vi.fn()}
      />,
    );
    expect(screen.queryByText("standard page not located")).toBeNull();
  });
});
