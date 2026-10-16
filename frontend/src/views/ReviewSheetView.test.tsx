/**
 * #967 PR 2: the Sheet screen, on made-up findings.
 *
 * MUTATION PROOF: let Send ignore the server's gate and "Send waits for the
 * server" fails; stop moving to the next open card after an answer and
 * "answering opens the next open card" fails; drop the J handler and the
 * keyboard test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsIssueGate, ReviewFinding, ReviewRunSummary } from "../types/api";
import { ReviewSheetView } from "./ReviewSheetView";

const reviewRuns = vi.fn();
const list = vi.fn();
const crsIssueGate = vi.fn();
const decideCrsFinding = vi.fn();
const exportCrs = vi.fn();
const reviewRunStandards = vi.fn();

vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "doc-sub", filename: "psv.pdf", page_count: 3 } }) },
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    list: (...a: unknown[]) => list(...a),
    crsIssueGate: (...a: unknown[]) => crsIssueGate(...a),
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
    decideCrsFinding: (...a: unknown[]) => decideCrsFinding(...a),
    exportCrs: (...a: unknown[]) => exportCrs(...a),
    // The run control, the job control and the standards page: not what these tests are about.
    readiness: async () => ({ ok: false, error: { message: "not in this test" } }),
    rereadPages: vi.fn(), cancelJob: vi.fn(), visionReaderStatus: async () => ({ ok: false, error: { message: "n/a" } }),
    reviewRunStandardsAll: async () => ({ ok: true, data: { standards: [] } }), overrideRunStandard: vi.fn(),
    reviewTrace: async () => ({ ok: false, error: { message: "not in this test" } }),
    runCoverage: async () => ({ ok: false, error: { message: "not in this test" } }),
  },
}));
vi.mock("../components/review/EvidencePageImage", () => ({
  EvidencePageImage: ({ side, page }: { side: string; page: number }) => <p>{`${side} page ${page}`}</p>,
}));
vi.mock("../components/DocumentPreview", () => ({
  DocumentPreview: ({ page }: { page: number }) => <p>{`preview page ${page}`}</p>,
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "psv.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-15T00:00:00Z",
    standards_in_scope: 2, findings_total: 3, by_status: {}, recommended_code: "Approved with Comments",
    engineer_final_code: null, ...over,
  } as ReviewRunSummary;
}

function f(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: 1, approval_status: "pending", ...over,
  } as ReviewFinding;
}

function gate(over: Partial<CrsIssueGate> = {}): CrsIssueGate {
  return { review_run_id: "run-1", issuable: false, final_code_recorded: false, blockers: [],
    unread_pages: [], open_findings: [], ...over };
}

let findings: ReviewFinding[];
beforeEach(() => {
  findings = [
    f("a", { contractor_page: 1 }),
    f("b", { contractor_page: 3, required_action: "Contractor to confirm b grade." }),
    f("p", { compliance_status: "COMPLIANT" }),
  ];
  reviewRuns.mockReset().mockResolvedValue({ ok: true, data: { runs: [run()] } });
  list.mockReset().mockImplementation(async () => ({ ok: true, data: { findings } }));
  crsIssueGate.mockReset().mockResolvedValue({ ok: true, data: gate() });
  reviewRunStandards.mockReset().mockResolvedValue({ ok: true, data: { standards: [
    { standard_document_id: "std-1", filename: "API 520.pdf", included: true },
    { standard_document_id: "std-2", filename: "API 526.pdf", included: false },
  ] } });
  decideCrsFinding.mockReset().mockImplementation(async (_r: string, id: string) => {
    findings = findings.map((x) => (x.id === id ? { ...x, confirmed_by: "eng" } : x));
    return { ok: true, data: {} };
  });
  exportCrs.mockReset();
});

describe("ReviewSheetView", () => {
  it("says how many things need an answer, and opens the first card at its page", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    expect(await screen.findByTestId("sheet-headline"))
      .toHaveTextContent("2 things need your answer. Everything else checked out.");
    expect(screen.getByRole("img", { name: "0 of 2 answered" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Field a does not meet the standard" })).toBeInTheDocument();
    expect(screen.getByText("submittal page 1")).toBeInTheDocument();
    expect(screen.getByText(/1 passed quietly/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /the rule books used \(1 of 2\)/ })).toBeInTheDocument();
  });

  it("answering opens the next open card and moves the document to its page", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Agree, ask the contractor" }));
    expect(await screen.findByRole("article", { name: "Field b does not meet the standard" })).toBeInTheDocument();
    expect(screen.getByText("submittal page 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "1 of 2 answered" })).toBeInTheDocument();
  });

  it("after answering a card you picked, opens the next open card after it, not the first", async () => {
    findings = [...findings, f("c", { contractor_page: 2, required_action: "Contractor to give c." })];
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Field c does not meet/ }));
    await userEvent.click(screen.getByRole("button", { name: "Agree, ask the contractor" }));
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "c", "accept", expect.any(String));
    expect(await screen.findByRole("article", { name: "Field b does not meet the standard" })).toBeInTheDocument();
    expect(screen.getByText("submittal page 3")).toBeInTheDocument();
  });

  it("marks pages with open cards and moves between cards with J and K", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    const pages = screen.getByRole("navigation", { name: "Pages" });
    // Page 2 has no card: it is listed only once the datasheet's page count arrives.
    expect(await within(pages).findByRole("button", { name: "Page 2" })).toBeInTheDocument();
    expect(within(pages).getByRole("button", { name: "Page 3, needs your answer" })).toBeInTheDocument();
    await userEvent.keyboard("j");
    expect(screen.getByRole("article", { name: "Field b does not meet the standard" })).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(screen.getByRole("article", { name: "Field a does not meet the standard" })).toBeInTheDocument();
  });

  it("a card spanning two pages marks both, and opening its second page stays there", async () => {
    findings = [
      f("m1", { compliance_status: "MISSING_INFORMATION", contractor_page: 1, required_action: "Contractor to state Field m1." }),
      f("m2", { compliance_status: "MISSING_INFORMATION", contractor_page: 2, required_action: "Contractor to state Field m2." }),
    ];
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    const pages = await screen.findByRole("navigation", { name: "Pages" });
    await userEvent.click(await within(pages).findByRole("button", { name: "Page 2, needs your answer" }));
    expect(screen.getByText("submittal page 2")).toBeInTheDocument();
    expect(within(pages).getByRole("button", { name: "Page 2, needs your answer" })).toHaveAttribute("aria-current", "page");
  });

  it("Enter agrees and N asks why, but never while typing", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    await userEvent.keyboard("n");
    const why = screen.getByLabelText(/why is this comment not needed/i);
    await userEvent.type(why, "n{Enter}");
    expect(decideCrsFinding).not.toHaveBeenCalled();
    (document.activeElement as HTMLElement).blur();
    await userEvent.keyboard("{Enter}");
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "a", "accept", expect.any(String));
  });

  it("Send waits for every answer, the decision and the server's gate", async () => {
    findings = findings.map((x) => ({ ...x, confirmed_by: "eng" }));
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ engineer_final_code: "Approved with Comments" })] } });
    crsIssueGate.mockResolvedValue({ ok: true, data: gate({ issuable: false, blockers: ["1 page(s) of the submittal were not read and no engineer has recorded checking them"] }) });
    const { unmount } = render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "What is your overall decision?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send comments to contractor" })).toBeDisabled();
    expect(screen.getByTestId("sheet-headline")).toHaveTextContent(/^Not ready to send yet: 1 page\(s\)/);
    unmount();

    crsIssueGate.mockResolvedValue({ ok: true, data: gate({ issuable: true }) });
    exportCrs.mockResolvedValue({ ok: false, error: { message: "refused by the server" } });
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    const send = await screen.findByRole("button", { name: "Send comments to contractor" });
    await vi.waitFor(() => expect(send).toBeEnabled());
    await userEvent.click(send);
    expect(exportCrs).toHaveBeenCalledWith("run-1", "issue");
    expect(await screen.findByRole("alert")).toHaveTextContent("refused by the server");
  });

  it("keeps the technical pages behind links, each its own route (#967 PR 3)", async () => {
    const onOpenPanel = vi.fn();
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={onOpenPanel} onOpenRun={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "see all" }));
    expect(onOpenPanel).toHaveBeenLastCalledWith("findings");
    await userEvent.click(screen.getByRole("button", { name: "how we checked this document" }));
    expect(onOpenPanel).toHaveBeenLastCalledWith("steps");
    await userEvent.click(screen.getByRole("button", { name: /the rule books used \(1 of 2\)/ }));
    expect(onOpenPanel).toHaveBeenLastCalledWith("standards");
    await userEvent.click(screen.getByRole("button", { name: "the CRS" }));
    expect(onOpenPanel).toHaveBeenLastCalledWith("crs");
  });

  it("audit 2026-09-30: a standards list that could not be loaded says so on its page", async () => {
    reviewRunStandards.mockResolvedValueOnce({ ok: false, error: { message: "the standards list failed" } });
    render(<ReviewSheetView runId="run-1" panel="standards" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    expect(await screen.findByText(/The standards for this run could not be loaded/)).toHaveTextContent("the standards list failed");
    expect(screen.queryByText("No standards were selected for this run.")).toBeNull();
  });

  it("renders a behind-the-scenes page for the run, with the way back", async () => {
    const onOpenPanel = vi.fn();
    render(<ReviewSheetView runId="run-1" panel="standards" onBack={vi.fn()} onOpenPanel={onOpenPanel} onOpenRun={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: /The rule books used · psv\.pdf/ })).toBeInTheDocument();
    expect(screen.getByText("API 520.pdf")).toBeInTheDocument();
    expect(screen.queryByTestId("sheet-headline")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Back to the sheet/ }));
    expect(onOpenPanel).toHaveBeenLastCalledWith(undefined);
  });
});
