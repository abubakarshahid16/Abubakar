/**
 * R21 (#785): one screen per CRS row - the submittal page next to the
 * standard clause, and why the standard applies - so an engineer decides the
 * row without opening the PDFs separately. Invented documents only.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewFinding, ReviewRunStandard } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

const documentCall = vi.fn();
const update = vi.fn();
const decideCrsFinding = vi.fn();
const findingEvidence = vi.fn();

vi.mock("../../api/client", () => ({
  api: { document: (...args: unknown[]) => documentCall(...args) },
  reviews: {
    update: (...args: unknown[]) => update(...args),
    decideCrsFinding: (...args: unknown[]) => decideCrsFinding(...args),
    findingEvidence: (...args: unknown[]) => findingEvidence(...args),
    confirm: vi.fn(),
    rejectPairing: vi.fn(),
  },
}));

// The panes fetch the boxed page from the finding's evidence route; here they
// only say which finding, side, page and kind of box they would show.
vi.mock("./EvidencePageImage", () => ({
  EvidencePageImage: ({ findingId, side, page, box, reason }: {
    findingId: string; side: string; page: number; box?: string | null; reason?: string | null;
  }) => (
    <div data-testid="preview">{`${findingId} ${side} p${page}${box ? ` ${box}` : ""}${reason ? ` (${reason})` : ""}`}</div>
  ),
}));
// The one-page view (opened from a citation) is not under test here.
vi.mock("../DocumentPreview", () => ({
  DocumentPreview: ({ doc, page }: { doc: DocumentRecord; page?: number | null }) => (
    <div data-testid="single-page">{`${doc.filename} p${page}`}</div>
  ),
}));

const SUB = { id: "doc-sub", filename: "pump-datasheet.pdf" } as DocumentRecord;
const STD = { id: "doc-std", filename: "std-noise.pdf" } as DocumentRecord;

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id: "f-1",
    review_run_id: "run-1",
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
  // By default the evidence route is unavailable: the panes use the
  // finding's own cited pages (the pre-#785 behaviour these tests pin).
  findingEvidence.mockReset();
  findingEvidence.mockResolvedValue({ ok: false, error: { message: "unavailable" } });
});

async function openSideBySide(props: Partial<Parameters<typeof FindingDetail>[0]> = {}) {
  render(<FindingDetail finding={finding()} documents={[SUB, STD]} onChanged={vi.fn()} {...props} />);
  await userEvent.click(screen.getByRole("button", { name: /side by side/i }));
  await screen.findAllByRole("group", { name: /Submittal|Standard/ });
  await waitFor(() => expect(screen.queryByText("Finding the cited page…")).toBeNull());
}

describe("side by side", () => {
  it("shows both cited pages at once, each with its own text verbatim", async () => {
    await openSideBySide();
    const sub = screen.getByRole("group", { name: "Submittal" });
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(sub).getByTestId("preview")).toHaveTextContent("f-1 submittal p2");
    expect(within(sub).getByText("95 dB(A)")).toBeInTheDocument();
    expect(within(sub).getByText("Read: Noise level")).toBeInTheDocument();
    expect(within(std).getByTestId("preview")).toHaveTextContent("f-1 standard p12");
    expect(within(std).getByText("Clause 6.1.14")).toBeInTheDocument();
    expect(within(std).getByText("The noise level shall not exceed 90 dB(A) at 1 m.")).toBeInTheDocument();
  });

  it("decides the row from the same screen: not needed asks why, then goes to the run's finding route", async () => {
    decideCrsFinding.mockResolvedValue({ ok: true, data: {} });
    await openSideBySide();
    expect(screen.getByRole("group", { name: "Standard" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Not needed" }));
    await userEvent.type(screen.getByLabelText(/Say why it is not needed/), "covered by the vendor's own sheet");
    await userEvent.click(screen.getByRole("button", { name: "Not needed" }));
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "f-1", "reject", "covered by the vendor's own sheet");
    expect(update).not.toHaveBeenCalledWith("f-1", { approval_status: "rejected" });
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
    await waitFor(() => expect(screen.queryByText("Finding the cited page…")).toBeNull());
    expect(within(std).queryByTestId("preview")).toBeNull();
    expect(within(std).getByText("The cited document could not be opened from this screen.")).toBeInTheDocument();
  });

  it("opening one cited page closes the side-by-side view", async () => {
    await openSideBySide();
    await userEvent.click(screen.getAllByRole("button", { name: /Open (standard|datasheet) at page/ })[0]);
    expect(screen.queryByRole("group", { name: "Standard" })).toBeNull();
    expect(screen.getByTestId("single-page")).toHaveTextContent("std-noise.pdf p12");
  });
});

describe("#785: the server finds the page and names the box", () => {
  const side = (over: Record<string, unknown>) => ({
    document_id: null, filename: null, page: null, box: null, reason: null, ...over });

  it("a checklist row shows its clause's page in the held standard, boxed", async () => {
    findingEvidence.mockResolvedValue({ ok: true, data: {
      finding_id: "f-1",
      submittal: side({ document_id: "doc-sub", filename: "pump-datasheet.pdf", page: 2, box: "label" }),
      standard: side({ document_id: "doc-std", filename: "std-noise.pdf", page: 7, box: "clause_text" }),
    } });
    await openSideBySide({ finding: finding({ standard_document_id: null, standard_page: null,
      standard_clause: "STD-NOISE 6.1.14" }) });
    expect(findingEvidence).toHaveBeenCalledWith("f-1");
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(std).getByTestId("preview")).toHaveTextContent("f-1 standard p7 clause_text");
    expect(within(std).getByText("std-noise.pdf — page 7")).toBeInTheDocument();
    const sub = screen.getByRole("group", { name: "Submittal" });
    expect(within(sub).getByTestId("preview")).toHaveTextContent("f-1 submittal p2 label");
  });

  it("a standard the server could not find is said in its words, with no page", async () => {
    findingEvidence.mockResolvedValue({ ok: true, data: {
      finding_id: "f-1",
      submittal: side({ document_id: "doc-sub", filename: "pump-datasheet.pdf", page: 2, box: "quote" }),
      standard: side({ reason: "API 999 1.2: the standard is not in the library you may read, or the clause was not found in it" }),
    } });
    await openSideBySide();
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(std).queryByTestId("preview")).toBeNull();
    expect(within(std).getByText(/^API 999 1\.2: the standard is not in the library/)).toBeInTheDocument();
  });
});

describe("#508: a scanned page", () => {
  const side = (over: Record<string, unknown>) => ({
    document_id: null, filename: null, page: null, box: null, reason: null, ...over });

  it("shows the page and passes on why it has no box", async () => {
    findingEvidence.mockResolvedValue({ ok: true, data: {
      finding_id: "f-1",
      submittal: side({ document_id: "doc-sub", filename: "scan.pdf", page: 3,
        reason: "page 3 is a scanned image with no text layer" }),
      standard: side({ document_id: "doc-std", filename: "std-noise.pdf", page: 7, box: "ocr_line" }),
    } });
    await openSideBySide();
    const sub = screen.getByRole("group", { name: "Submittal" });
    expect(within(sub).getByTestId("preview"))
      .toHaveTextContent("f-1 submittal p3 (page 3 is a scanned image with no text layer)");
    const std = screen.getByRole("group", { name: "Standard" });
    expect(within(std).getByTestId("preview")).toHaveTextContent("f-1 standard p7 ocr_line");
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
