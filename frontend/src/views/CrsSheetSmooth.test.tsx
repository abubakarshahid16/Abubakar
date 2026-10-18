/**
 * Order 117: the CRS sheet stays smooth on large reviews.
 *
 * MUTATION PROOF: drop the React.memo on CrsRow, or give it fresh inline
 * callbacks per render, or let useCrsDecisions return a new object each
 * render, and "a J press re-renders only the rows whose selection changed"
 * fails; put the drawer's focus effect back on [row.key] and "the drawer
 * keeps focus steady" fails (the opener is focused again on J); draw every
 * row and "a long list shows 200 rows" fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../types/api";
import { CrsSheetView } from "./CrsSheetView";

const list = vi.fn();
// Counts row renders: CrsRow calls `wordingOf` exactly once per render.
const wordingCalls = vi.hoisted(() => ({ count: 0 }));

vi.mock("../components/review/crs/useCrsDecisions", async (importOriginal) => {
  const real = await importOriginal<typeof import("../components/review/crs/useCrsDecisions")>();
  return {
    ...real,
    wordingOf: (...a: Parameters<typeof real.wordingOf>) => { wordingCalls.count += 1; return real.wordingOf(...a); },
  };
});

vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "doc-sub", filename: "psv.pdf", page_count: 12 } }) },
  reviews: {
    reviewRuns: async () => ({ ok: true, data: { runs: [run()] } }),
    // Since order 109 (#1125) the screen asks for its one run; the same fixture run.
    reviewRun: async () => ({ ok: true, data: run() }),
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: async () => ({ ok: true, data: {
      standards: [{ standard_document_id: "std-1", filename: "API 520.pdf", included: true }], missing_references: [],
    } }),
    reviewRunSummary: async () => ({ ok: false, disconnected: false, error: { code: "internal", message: "not here" } }),
    exportCrs: vi.fn(),
    confirm: vi.fn(),
    update: vi.fn(),
    decideCrsFinding: vi.fn(),
    crsDecisions: async () => ({ ok: true, data: { decisions: [] } }),
    cancelJob: vi.fn(),
  },
}));
vi.mock("../components/review/sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <p>{`submittal page ${page}`}</p>,
}));

function run(): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "psv.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-15T08:00:00Z", completed_at: "2026-10-15T08:18:00Z",
    standards_in_scope: 1, findings_total: 6, by_status: {}, recommended_code: null, recommended_reason: null,
    page_coverage: { pages_total: 12, fact_pages: [1, 2, 3, 4, 5], pages_not_read_into_fields: [], not_read_reasons: {} },
    engineer_final_code: null,
  } as unknown as ReviewRunSummary;
}

function f(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: 1, approval_status: "pending",
    standard_document_id: "std-1", standard_clause: "4.1", ...over,
  } as ReviewFinding;
}

let findings: ReviewFinding[];
beforeEach(() => {
  findings = ["a", "b", "c", "d", "e", "g"].map((id, i) => f(id, { contractor_page: i + 1 }));
  list.mockReset().mockImplementation(async () => ({ ok: true, data: { findings } }));
  wordingCalls.count = 0;
});

function rows(): HTMLElement[] {
  return within(screen.getByRole("grid", { name: "Comment resolution sheet" })).getAllByRole("row").slice(1);
}

describe("CrsSheetView stays smooth (order 117)", () => {
  it("a J press re-renders only the rows whose selection changed", async () => {
    render(<CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />);
    await screen.findByTestId("crs-headline");
    expect(rows()).toHaveLength(6);
    await userEvent.keyboard("j");
    expect(rows()[0]).toHaveAttribute("aria-selected", "true");
    wordingCalls.count = 0;
    await userEvent.keyboard("j");
    expect(rows()[1]).toHaveAttribute("aria-selected", "true");
    // Row 1 loses the selection, row 2 gains it; the other four stay as drawn.
    expect(wordingCalls.count).toBe(2);
    wordingCalls.count = 0;
    await userEvent.keyboard("{Enter}");
    expect(within(rows()[1]).getByTestId("row-status")).toHaveTextContent("Kept");
    // A decision on one row re-renders that row only.
    expect(wordingCalls.count).toBe(1);
  });

  it("the drawer keeps focus steady: Close once on open, nothing on J, back to the opener on close", async () => {
    render(<CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />);
    await screen.findByTestId("crs-headline");
    const opener = screen.getByRole("button", { name: /Open evidence for Comment 1/ });
    await userEvent.click(opener);
    const close = screen.getByRole("button", { name: "Close evidence" });
    expect(close).toHaveFocus();
    const openerFocus = vi.fn();
    const closeFocus = vi.fn();
    opener.addEventListener("focus", openerFocus);
    close.addEventListener("focus", closeFocus);
    await userEvent.keyboard("j");
    expect(within(screen.getByRole("dialog")).getByTestId("drawer-position")).toHaveTextContent(/^Row 2 of /);
    expect(openerFocus).not.toHaveBeenCalled();
    expect(closeFocus).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Close evidence" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("closing a drawer opened by a click on the row gives the keyboard to that row's button", async () => {
    render(<CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />);
    await screen.findByTestId("crs-headline");
    await userEvent.click(within(rows()[2]).getAllByRole("cell")[3]);
    expect(screen.getByRole("button", { name: "Close evidence" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(within(rows()[2]).getByRole("button", { name: /Open evidence for Comment 3/ })).toHaveFocus();
  });

  it("a long list shows 200 rows, says so, and Show more draws the next ones", async () => {
    const met = Array.from({ length: 250 }, (_, i) => f(`m${i}`, { compliance_status: "COMPLIANT", contractor_page: 5 }));
    findings = [...findings, ...met];
    render(<CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />);
    await screen.findByTestId("crs-headline");
    expect(screen.queryByTestId("crs-more")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Everything"));
    const total = 256;
    expect(rows()).toHaveLength(200);
    expect(screen.getByTestId("crs-more")).toHaveTextContent(`Showing the first 200 of ${total} rows at this depth.`);
    await userEvent.click(screen.getByRole("button", { name: "Show 56 more" }));
    expect(rows()).toHaveLength(total);
    expect(screen.queryByTestId("crs-more")).not.toBeInTheDocument();
  }, 20000);
});
