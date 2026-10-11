/**
 * R21 (#785): one screen per CRS row - the submittal page next to the
 * standard clause, and why the standard applies - so an engineer decides the
 * row without opening the PDFs separately. Invented documents only.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewFinding, ReviewRunStandard } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

const documentCall = vi.fn();
const update = vi.fn();

vi.mock("../../api/client", () => ({
  api: { document: (...args: unknown[]) => documentCall(...args) },
  reviews: {
    update: (...args: unknown[]) => update(...args),
    confirm: vi.fn(),
    rejectPairing: vi.fn(),
  },
}));

// The preview fetches page images; here it only says which page it shows.
vi.mock("../DocumentPreview", () => ({
  DocumentPreview: ({ doc, page }: { doc: DocumentRecord; page?: number | null }) => (
    <div data-testid="preview">{`${doc.filename} p${page}`}</div>
  ),
}));

const SUB = { id: "doc-sub", filename: "pump-datasheet.pdf" } as DocumentRecord;
const STD = { id: "doc-std", filename: "std-noise.pdf" } as DocumentRecord;

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id: "f-1",
    document_id: "doc-sub",
    standard_document_id: "doc-std",
    finding: "the noise level exceeds 90 dB(A)",
    requirement: "noise level",
    requirement_source_text: "The noise level shall not exceed 90 dB(A) at 1 m.",
    contractor_section: "Noise level",
    contractor_evidence_text: "95 dB(A)",
    contractor_page: 2,
    standard_page: 12,
    standard_clause: "6.1.14",
    compliance_status: "NON_COMPLIANT",
    confirmed_by: null,
    confirmed_at: null,
    engineer_comment: null,
    approval_status: null,
    requirement_id: "req-1",
    fact_id: "fact-1",
    ...over,
  } as unknown as ReviewFinding;
}

const WHY: ReviewRunStandard = {
  standard_document_id: "doc-std",
  filename: "std-noise.pdf",
  selection_method: "referenced",
  selection_reason: "The datasheet cites this standard on page 1.",
  confidence: null,
  included: true,
  exclusion_reason: null,
  evidence_page: 1,
  evidence_quote: "Noise per STD-NOISE",
};

beforeEach(() => {
  documentCall.mockReset();
  update.mockReset();
  documentCall.mockResolvedValue({ ok: false, error: { message: "not found" } });
  update.mockResolvedValue({ ok: true, data: finding() });
});

async function openSideBySide(props: Partial<Parameters<typeof FindingDetail>[0]> = {}) {
  render(<FindingDetail finding={finding()} documents={[SUB, STD]} onChanged={vi.fn()} {...props} />);
  await userEvent.click(screen.getByRole("button", { name: /side by side/i }));
}

describe("side by side", () => {
  it("shows both cited pages at once, each with its own text verbatim", async () => {
    await openSideBySide();
    const sub = screen.getByRole("group", { name: "Submittal" });
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(sub).getByTestId("preview")).toHaveTextContent("pump-datasheet.pdf p2");
    expect(within(sub).getByText("95 dB(A)")).toBeInTheDocument();
    expect(within(sub).getByText("Read: Noise level")).toBeInTheDocument();
    expect(within(std).getByTestId("preview")).toHaveTextContent("std-noise.pdf p12");
    expect(within(std).getByText("Clause 6.1.14")).toBeInTheDocument();
    expect(within(std).getByText("The noise level shall not exceed 90 dB(A) at 1 m.")).toBeInTheDocument();
  });

  it("decides the row from the same screen: reject goes to the finding route", async () => {
    await openSideBySide();
    expect(screen.getByRole("group", { name: "Standard" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reject comment" }));
    expect(update).toHaveBeenCalledWith("f-1", { approval_status: "rejected" });
  });

  it("a side with no cited page says so instead of showing an empty pane", async () => {
    await openSideBySide({ finding: finding({ standard_page: null, contractor_evidence_text: null }) });
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(std).queryByTestId("preview")).toBeNull();
    expect(within(std).getByText(/cites no standard page/)).toBeInTheDocument();
    const sub = screen.getByRole("group", { name: "Submittal" });
    expect(within(sub).getByText("No value was read from the submittal for this requirement.")).toBeInTheDocument();
  });

  it("a document the screen could not open is said, not shown as another page", async () => {
    render(<FindingDetail finding={finding()} documents={[SUB]} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /side by side/i }));
    const std = await screen.findByRole("group", { name: "Standard" });
    expect(within(std).queryByTestId("preview")).toBeNull();
    expect(within(std).getByText("The cited document could not be opened from this screen.")).toBeInTheDocument();
  });

  it("opening one cited page closes the side-by-side view", async () => {
    await openSideBySide();
    await userEvent.click(screen.getAllByRole("button", { name: /Open at page/ })[0]);
    expect(screen.queryByRole("group", { name: "Standard" })).toBeNull();
  });
});

describe("why this standard applies", () => {
  it("prints the run's reason and evidence verbatim", () => {
    render(<FindingDetail finding={finding()} documents={[SUB, STD]} whyApplies={WHY} onChanged={vi.fn()} />);
    const why = screen.getByTestId("why-standard-applies");
    expect(within(why).getByText("referenced")).toBeInTheDocument();
    expect(within(why).getByText("The datasheet cites this standard on page 1.")).toBeInTheDocument();
    expect(within(why).getByText(/Evidence, page 1: “Noise per STD-NOISE”/)).toBeInTheDocument();
  });

  it("says loading while the run's standards load, and 'no record' only when there is none", () => {
    const { rerender } = render(
      <FindingDetail finding={finding()} documents={[]} whyApplies={undefined} onChanged={vi.fn()} />);
    expect(screen.getByTestId("why-standard-applies")).toHaveTextContent("Loading the run's standards");
    rerender(<FindingDetail finding={finding()} documents={[]} whyApplies={null} onChanged={vi.fn()} />);
    expect(screen.getByTestId("why-standard-applies"))
      .toHaveTextContent("This run holds no record of why this standard was selected.");
  });

  it("a finding with no standard (a checklist item) shows no such section", () => {
    render(<FindingDetail finding={finding({ standard_document_id: null })} documents={[]} whyApplies={null} onChanged={vi.fn()} />);
    expect(screen.queryByTestId("why-standard-applies")).toBeNull();
  });
});

describe("why this requirement applies (R21, run ledger)", () => {
  const decided = { state: "applies", reason_code: "applies", reason: "Applies: the sheet states a pump", decided_by: "code" };

  it("prints the requirement's own reason and who decided, verbatim", () => {
    render(<FindingDetail finding={finding({ scope_decision: decided } as Partial<ReviewFinding>)}
      documents={[]} whyApplies={WHY} onChanged={vi.fn()} />);
    expect(screen.getByTestId("requirement-scope"))
      .toHaveTextContent("This requirement: Applies: the sheet states a pump(decided by code)");
  });

  it("is shown even when the run holds no standard-level record", () => {
    render(<FindingDetail finding={finding({ scope_decision: decided } as Partial<ReviewFinding>)}
      documents={[]} whyApplies={null} onChanged={vi.fn()} />);
    expect(screen.getByTestId("why-standard-applies")).toHaveTextContent("holds no record");
    expect(screen.getByTestId("requirement-scope")).toBeInTheDocument();
  });

  it("no ledger row shows no line, never an invented reason", () => {
    render(<FindingDetail finding={finding({ scope_decision: null } as Partial<ReviewFinding>)}
      documents={[]} whyApplies={WHY} onChanged={vi.fn()} />);
    expect(screen.queryByTestId("requirement-scope")).toBeNull();
  });
});
