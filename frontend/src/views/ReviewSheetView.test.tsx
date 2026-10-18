/**
 * #967 PR 2: the Sheet screen, on made-up findings.
 *
 * MUTATION PROOF: let Send ignore the server's gate and "Send waits for the
 * server" fails; stop moving to the next open card after an answer and
 * "answering opens the next open card" fails; drop the J handler and the
 * keyboard test fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NavigationContext } from "../components/NavLink";
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
vi.mock("../components/review/sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <p>{`submittal page ${page}`}</p>,
}));
vi.mock("../components/review/EvidencePageImage", () => ({
  EvidencePageImage: ({ side, page }: { side: string; page: number }) => <p>{`${side} page ${page}`}</p>,
}));
vi.mock("../components/review/sheet/PlainPageImage", () => ({
  PlainPageImage: ({ page }: { page: number }) => <p>{`preview page ${page}`}</p>,
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

  it("rule_trust (#947): a safety tick is underlined green on the page, amber is for the rest", async () => {
    findings = [
      f("a", { contractor_page: 1 }),
      f("s", { contractor_page: 1, compliance_status: "COMPLIANT", show_for_engineer_tick: true, trust_label: "AUTO_PROVEN", tier: "SAFETY" }),
    ];
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    expect(screen.getByTestId("sheet-headline")).toHaveTextContent("2 things need your answer");
    // #1090: the selected card ("a", opened first) is on its card, not listed again
    const marks = within(screen.getByRole("list", { name: "Marked on this page" })).getAllByRole("button");
    expect(marks.map((m) => m.dataset.mark)).toEqual(["tick"]);
    expect(marks[0]).toHaveTextContent(/Field s meets the standard/);
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

  it("order 95 piece 2: the header offers the new comment sheet at /review/<run>/crs-sheet through the app's navigation", async () => {
    const navigate = vi.fn();
    render(
      <NavigationContext.Provider value={navigate}>
        <ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />
      </NavigationContext.Provider>,
    );
    await screen.findByTestId("sheet-headline");
    const link = screen.getByRole("link", { name: "Try the new comment sheet" });
    expect(link).toHaveAttribute("href", "/review/run-1/crs-sheet");
    await userEvent.click(link);
    expect(navigate).toHaveBeenCalledWith("review", "run-1", "crs-sheet");
  });

  it("the behind-the-scenes menu lists only its pages, not the two review screens", async () => {
    render(<ReviewSheetView runId="run-1" panel="crs" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    const nav = await screen.findByRole("navigation", { name: "Behind the scenes" });
    expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "← Back to the sheet", "All findings", "The rule books used", "How we checked this document", "AI numbers for this run", "Comment Resolution Sheet",
    ]);
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

describe("#603: cards in chunks", () => {
  it("renders a chunk, grows it on the button, and K from the first card shows a window round the last", async () => {
    // 70 distinct open cards: a different wording each (digits and the field
    // name are folded out of the template, so none collapse into one card)
    findings = Array.from({ length: 70 }, (_, i) => f(`c${i}`, { required_action: `Contractor to ${"re".repeat(i + 1)}fix it.` }));
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    // one card is open (an article); the rest are one-line buttons named by their title
    const cardsOnScreen = () => within(screen.getByTestId("sheet-cards")).getAllByText(/^Field c\d+ does not meet the standard$/).length;
    expect(cardsOnScreen()).toBe(60);
    expect(screen.getByTestId("more-cards")).toHaveTextContent("Showing cards 1-60 of 70 - show 10 more");
    await userEvent.keyboard("k");                                   // wraps to the last card
    expect(screen.getByRole("article", { name: "Field c69 does not meet the standard" })).toBeInTheDocument();
    expect(cardsOnScreen()).toBe(60);                                 // a window, not every card
    expect(screen.getByTestId("more-cards")).toHaveTextContent("Showing cards 11-70 of 70");
    await userEvent.keyboard("j");                                   // and back to the first
    expect(screen.getByTestId("more-cards")).toHaveTextContent("Showing cards 1-60 of 70");
    await userEvent.click(screen.getByTestId("more-cards"));
    expect(cardsOnScreen()).toBe(70);
    expect(screen.queryByTestId("more-cards")).toBeNull();
  });
});

describe("#967 PR 4: show it on the page", () => {
  const scrolled = vi.fn();
  beforeEach(() => {
    scrolled.mockReset();
    (Element.prototype as unknown as Record<string, unknown>).scrollIntoView = scrolled;
  });
  afterEach(() => {
    delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
  });

  const frame = () => document.querySelector("[data-sheet-page]") as HTMLElement;

  it("T scrolls the datasheet into view and pulses its frame once, then the pulse ends", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    scrolled.mockReset(); // the opened card's own scroll is not the page's
    expect(frame().dataset.pulsing).toBeUndefined();
    await userEvent.keyboard("t");
    expect(frame().dataset.pulsing).toBe("true");
    // THE PAGE FRAME scrolled - pinned to [data-sheet-page], not to "the first
    // scroll after T": on a slow runner the opened card's own scroll (its
    // effect, when it becomes selected) can land after the reset above, and
    // this used to take that <article> for the frame (flaky on two gates, 17 Oct).
    expect(scrolled.mock.instances).toContain(frame());
    await waitFor(() => expect(frame().dataset.pulsing).toBeUndefined(), { timeout: 3000 });
  });

  it("the card's own link does the same, and leaves the rule view for the datasheet", async () => {
    findings = [f("a", { contractor_page: 1, standard_document_id: "std-1", standard_page: 1 })];
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    await userEvent.click(screen.getByRole("button", { name: /API 520\.pdf/ }));
    expect(screen.getByText("standard page 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show on the page" }));
    expect(screen.getByText("submittal page 1")).toBeInTheDocument();
    expect(frame().dataset.pulsing).toBe("true");
  });

  it("never fires while typing, and the keys line names T", async () => {
    render(<ReviewSheetView runId="run-1" onBack={vi.fn()} onOpenPanel={vi.fn()} onOpenRun={vi.fn()} />);
    await screen.findByTestId("sheet-headline");
    await userEvent.keyboard("n");
    await userEvent.type(screen.getByLabelText(/why is this comment not needed/i), "t");
    expect(frame().dataset.pulsing).toBeUndefined();
    expect(screen.getByTestId("sheet-keys")).toHaveTextContent("T show it on the page");
  });
});
