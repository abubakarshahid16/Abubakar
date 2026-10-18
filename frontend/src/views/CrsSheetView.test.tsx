/**
 * Order 95 piece 2: the CRS-first Sheet on made-up findings.
 *
 * MUTATION PROOF: show Tier A by default and "Tier A is hidden" fails; let
 * Remove go through without a reason and "Remove requires a reason" fails;
 * let Accept all touch a Needs-you row and that test fails; enable Sign
 * before every Needs-you row was opened and "Sign waits" fails; drop the J
 * handler and the keyboard test fails.
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../types/api";
import { CrsSheetView } from "./CrsSheetView";

const reviewRuns = vi.fn();
const list = vi.fn();
const exportCrs = vi.fn();
const reviewRunStandards = vi.fn();

vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "doc-sub", filename: "psv.pdf", page_count: 12, equipment_type: "Pressure safety valve", revision: "B" } }) },
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
    exportCrs: (...a: unknown[]) => exportCrs(...a),
    cancelJob: vi.fn(),
  },
}));
vi.mock("../components/review/sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <p>{`submittal page ${page}`}</p>,
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "psv.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-15T08:00:00Z", completed_at: "2026-10-15T08:18:00Z",
    standards_in_scope: 2, findings_total: 6, by_status: { COMPLIANT: 94, NON_COMPLIANT: 2 },
    recommended_code: "Approved with Comments", recommended_reason: "Two values do not meet the standard.",
    requirement_split: { checked: 100, applies_not_checked: 0, does_not_apply: 4362, total: 4462, applies_not_checked_reasons: [], does_not_apply_reasons: [], repeats_ignored: null, unchecked_share: 0 },
    page_coverage: { pages_total: 12, fact_pages: [1, 2, 3], pages_not_read_into_fields: [4, 9], not_read_reasons: {} },
    engineer_final_code: null, ...over,
  } as ReviewRunSummary;
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
  findings = [
    f("a", { contractor_page: 1 }),
    f("b", { contractor_page: 3 }),
    f("blank", { compliance_status: "MISSING_INFORMATION", contractor_page: 2, finding: "blank is not given" }),
    f("cond", { compliance_status: "CONDITIONAL", contractor_page: 3 }),
    f("unread", { contractor_page: 4 }),
    f("met", { compliance_status: "COMPLIANT" }),
    f("scope", { compliance_status: "NOT_IN_DOCUMENT_SCOPE" }),
  ];
  reviewRuns.mockReset().mockResolvedValue({ ok: true, data: { runs: [run()] } });
  list.mockReset().mockImplementation(async () => ({ ok: true, data: { findings } }));
  reviewRunStandards.mockReset().mockResolvedValue({ ok: true, data: {
    standards: [{ standard_document_id: "std-1", filename: "API 520.pdf", included: true }],
    missing_references: [{ identifier: "API 526", status: "MISSING_LOCALLY" }],
  } });
  exportCrs.mockReset().mockResolvedValue({ ok: false, error: { code: "conflict", message: "2 findings are still open." } });
});

function mount() {
  return render(<CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />);
}

function rows(): HTMLElement[] {
  const table = screen.getByRole("grid", { name: "Comment resolution sheet" });
  return within(table).getAllByRole("row").slice(1);
}

function rowItems(): string[] {
  return rows().map((r) => within(r).getAllByRole("cell")[3].textContent ?? "");
}

describe("CrsSheetView", () => {
  it("renders the headline from the rows and the run's stored fields, the code and the seven columns", async () => {
    mount();
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent(
      "5 comments, 2 need your judgement. 1 value met, 4,362 clauses not applicable (hidden). Read in 18 min; the reader gave up on pages 4 and 9.",
    );
    expect(screen.getByTestId("crs-code")).toHaveTextContent("Proposed code: Approved with Comments. Two values do not meet the standard.");
    expect(await screen.findByText(/Equipment: Pressure safety valve · Revision B/)).toBeInTheDocument();
    const headers = within(screen.getByRole("grid")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Tier", "Comment no.", "Page or section", "Item", "Clause and standard", "Observation", "Required action", "Status", "Actions"]);
    expect(screen.getByTestId("crs-footer")).toHaveTextContent("Run run-1");
    expect(screen.getByTestId("crs-footer")).toHaveTextContent("Pages read: 3 of 12; not read: 4, 9.");
    expect(screen.getByTestId("crs-footer")).toHaveTextContent("Standards used: 1 (API 520.pdf); missing from the library: 1 (API 526).");
    expect(screen.queryByTestId("crs-rejected")).not.toBeInTheDocument();
    expect(screen.getByTestId("crs-footer")).toHaveTextContent("Rows on this sheet: 3 Comment, 2 Needs you, 1 Met, 0 Not applicable, 1 Another document");
  });

  it("hides Tier A by default behind one line, except the spot check, and shows it on click", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    // One Met row exists, so the spot check (at least one) surfaces it; the not-applicable row stays hidden.
    expect(rowItems()).toEqual(["Field a", "Field blank", "Field b", "Field cond", "Field unread", "Field met"]);
    expect(screen.getByText("spot check")).toBeInTheDocument();
    expect(screen.getByTestId("met-line")).toHaveTextContent("1 met, 0 not applicable, 1 for another document (1 shown above as a spot check): show");
    await userEvent.click(screen.getByRole("button", { name: "show" }));
    expect(rowItems()).toContain("Field scope");
    expect(screen.getByText(/4,362 clauses of the standards were judged not applicable/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "hide" }));
    expect(rowItems()).not.toContain("Field scope");
  });

  it("a finding already rejected is filtered off the sheet and counted in the footer", async () => {
    findings = [...findings, f("gone", { approval_status: "rejected", contractor_page: 2 })];
    mount();
    await screen.findByTestId("crs-headline");
    expect(rowItems()).not.toContain("Field gone");
    expect(screen.getByTestId("crs-rejected")).toHaveTextContent("Left off this sheet: 1 finding already rejected by an engineer.");
  });

  it("a finding for another document says so when Tier A is shown", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByLabelText("Everything"));
    const scope = rows().find((r) => within(r).getAllByRole("cell")[3].textContent === "Field scope");
    expect(within(scope as HTMLElement).getAllByRole("cell")[0]).toHaveTextContent("Another document");
  });

  it("the depth selector filters: Critical drops the blank, Everything adds Tier A", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByLabelText("Critical only"));
    expect(rowItems()).toEqual(["Field a", "Field b", "Field cond", "Field unread"]);
    await userEvent.click(screen.getByLabelText("Everything"));
    expect(rowItems()).toEqual(["Field a", "Field blank", "Field b", "Field cond", "Field unread", "Field met", "Field scope"]);
    expect(screen.queryByTestId("met-line")).not.toBeInTheDocument();
  });

  it("marks each row with a tier word and the reason, never a percentage", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    const tiers = rows().map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(tiers[0]).toBe("Comment");
    expect(tiers[3]).toContain("Needs you: condition unsettled");
    expect(tiers[4]).toContain("Needs you: page not read");
    expect(tiers[5]).toContain("Met");
    expect(screen.getByRole("grid").textContent).not.toMatch(/\d+ ?%/);
  });

  it("Remove requires a reason from the closed list", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: "Remove comment 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a reason first.");
    expect(within(rows()[0]).getByTestId("row-status")).toHaveTextContent("Open");
    await userEvent.selectOptions(screen.getByLabelText("Why remove comment 1?"), "Duplicate");
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(within(rows()[0]).getByTestId("row-status")).toHaveTextContent("Removed: Duplicate");
    await userEvent.click(screen.getByRole("button", { name: "Put comment 1 back" }));
    expect(within(rows()[0]).getByTestId("row-status")).toHaveTextContent("Open");
  });

  it("Edit wording changes the observation and required action on the row only", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: "Edit wording of comment 1" }));
    const action = screen.getByLabelText("Required action for comment 1");
    await userEvent.clear(action);
    await userEvent.type(action, "Contractor to state the set pressure in barg.");
    await userEvent.click(screen.getByRole("button", { name: "Save wording" }));
    expect(within(rows()[0]).getAllByRole("cell")[6]).toHaveTextContent("Contractor to state the set pressure in barg.");
    expect(within(rows()[0]).getByTestId("row-status")).toHaveTextContent("Kept, your wording");
    expect(within(rows()[2]).getAllByRole("cell")[6]).toHaveTextContent("Contractor to fix b.");
  });

  it("Accept all remaining says how many first, skips Needs you, and Undo restores", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: "Keep comment 1" }));
    await userEvent.click(screen.getByRole("button", { name: /Accept all remaining Comments \(2\)/ }));
    expect(screen.getByRole("status")).toHaveTextContent("2 comments will be kept.");
    await userEvent.click(screen.getByRole("button", { name: "Yes, keep them" }));
    const statuses = () => rows().map((r) => within(r).getByTestId("row-status").textContent);
    expect(statuses()).toEqual(["Kept", "Kept", "Kept", "Open", "Open", "Met"]);
    expect(screen.getByRole("button", { name: /Accept all remaining Comments/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(statuses()).toEqual(["Kept", "Open", "Open", "Open", "Open", "Met"]);
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("says by Sign that decisions on this screen are not in the exported file", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    expect(screen.queryByTestId("sign-local-note")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep comment 1" }));
    expect(screen.getByTestId("sign-local-note")).toHaveTextContent("Your 1 decision on this screen (Keep, edited wording, Remove) is not in the exported file yet");
  });

  it("Sign and export is disabled until every Needs-you row has been opened, then calls the existing CRS issue export", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    const sign = () => screen.getByRole("button", { name: /Sign and export/ });
    expect(sign()).toBeDisabled();
    expect(screen.getByTestId("sign-waits")).toHaveTextContent('opened the 2 rows marked "Needs you"');
    await userEvent.click(screen.getByRole("button", { name: /Open evidence for Comment 4/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Why it needs you: condition unsettled");
    expect(screen.getByRole("dialog")).toHaveTextContent("submittal page 3");
    expect(screen.getByRole("button", { name: "Close evidence" })).toHaveFocus();
    expect(sign()).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Open evidence for Comment 5/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Why it needs you: page not read");
    await userEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(sign()).toBeEnabled();
    await userEvent.click(sign());
    expect(exportCrs).toHaveBeenCalledWith("run-1", "issue");
    expect(await screen.findByRole("alert")).toHaveTextContent("2 findings are still open.");
  });

  it("the keyboard: J / K move, Enter keeps, E edits, R asks why", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.keyboard("j");
    expect(rows()[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("j");
    expect(rows()[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("k");
    expect(rows()[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    expect(within(rows()[0]).getByTestId("row-status")).toHaveTextContent("Kept");
    await userEvent.keyboard("e");
    expect(screen.getByLabelText("Observation for comment 1")).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.keyboard("r");
    expect(screen.getByLabelText("Why remove comment 1?")).toHaveFocus();
  });

  it("a running review shows its progress, not an empty sheet", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run({ status: "running", job: { id: "j", state: "running", progress_done: 3, progress_total: 12, progress_label: "pages", cancel_requested: false } })] } });
    mount();
    expect(await screen.findByTestId("review-progress")).toBeInTheDocument();
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
    await act(async () => {});
  });
});
