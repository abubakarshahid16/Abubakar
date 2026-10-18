/**
 * Order 95 piece 2: the CRS-first Sheet on made-up findings.
 *
 * MUTATION PROOF: show Tier A by default and "Tier A is hidden" fails; let
 * Remove go through without a reason and "Remove requires a reason" fails;
 * let Accept all touch a Needs-you row and that test fails; enable Sign
 * before every Needs-you row was opened and "Sign waits" fails; drop the J
 * handler and the keyboard test fails.
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NavigationContext } from "../components/NavLink";
import type { ReviewFinding, ReviewRunSummary, ReviewRunTierSummary, RunSummaryTierRow } from "../types/api";
import { CrsSheetView } from "./CrsSheetView";

const reviewRuns = vi.fn();
/** Marks the shim's read of the fixture, so a real list call can be told apart. */
const FIXTURE = "fixture";
const list = vi.fn();
const exportCrs = vi.fn();
const reviewRunStandards = vi.fn();
const reviewRunSummary = vi.fn();
const confirm = vi.fn();
const update = vi.fn();
const decideCrsFinding = vi.fn();
const crsDecisions = vi.fn();

vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "doc-sub", filename: "psv.pdf", page_count: 12, equipment_type: "Pressure safety valve", revision: "B" } }) },
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    // Order 109: the screen asks for its one run; served from the same fixture.
    reviewRun: async (id: string) => {
      const r = await reviewRuns(FIXTURE, id);
      return r?.ok ? { ok: true, data: r.data.runs.find((x: { review_run_id: string }) => x.review_run_id === id) ?? null } : r;
    },
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
    reviewRunSummary: (...a: unknown[]) => reviewRunSummary(...a),
    exportCrs: (...a: unknown[]) => exportCrs(...a),
    confirm: (...a: unknown[]) => confirm(...a),
    update: (...a: unknown[]) => update(...a),
    decideCrsFinding: (...a: unknown[]) => decideCrsFinding(...a),
    crsDecisions: (...a: unknown[]) => crsDecisions(...a),
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
  // A server without #1111's route: 404, as `request()` reports it.
  reviewRunSummary.mockReset().mockResolvedValue({ ok: false, disconnected: false, error: { code: "internal", message: "That is not something the backend knows about." } });
  exportCrs.mockReset().mockResolvedValue({ ok: false, error: { code: "conflict", message: "2 findings are still open." } });
  confirm.mockReset().mockResolvedValue({ ok: true, data: {} });
  update.mockReset().mockResolvedValue({ ok: true, data: {} });
  decideCrsFinding.mockReset().mockResolvedValue({ ok: true, data: {} });
  crsDecisions.mockReset().mockResolvedValue({ ok: true, data: { decisions: [] } });
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
  it("order 112: the headline counts rows and names the findings behind them; no internal code in the Observation", async () => {
    findings = [
      ...Array.from({ length: 13 }, (_, i) => f(`k${i}`, {
        compliance_status: "MISSING_INFORMATION", finding: `Field k${i} is blank`, required_action: `Contractor to give Field k${i}.`,
      })),
      f("nf", { contractor_page: 2, finding: "no_field_matched: the datasheet has no row for this value" }),
    ];
    mount();
    // 13 blanks make one row, plus one more: 2 rows on the table, 14 findings behind them.
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent(/^2 comments \(14 findings\)/);
    expect(rows()).toHaveLength(2);
    const sheet = screen.getByRole("grid", { name: "Comment resolution sheet" });
    expect(sheet).toHaveTextContent("the datasheet has no row for this value");
    expect(sheet).not.toHaveTextContent("no_field_matched");
  });

  it("order 117: a slow answer for the run the reader left never replaces the run they moved to", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    reviewRuns.mockImplementation(async (_fixture: string, id: string) => {
      if (id === "run-1") {
        await gate;
        return { ok: true, data: { runs: [run()] } };
      }
      return { ok: true, data: { runs: [run({ review_run_id: "run-2", submittal_filename: "second.pdf" })] } };
    });
    const view = mount();
    view.rerender(<CrsSheetView runId="run-2" onBack={vi.fn()} onOpenCards={vi.fn()} />);
    expect(await screen.findByRole("heading", { level: 1, name: "second.pdf" })).toBeInTheDocument();
    await act(async () => { release(); await gate; });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("second.pdf");
  });

  it("order 109: asks the server for its one run, never for the whole list", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    expect(reviewRuns.mock.calls.length).toBeGreaterThan(0);
    expect(reviewRuns.mock.calls.every((c) => c[0] === FIXTURE && c[1] === "run-1")).toBe(true);
  });

  it("renders the headline from the rows and the run's stored fields, the code and the seven columns", async () => {
    mount();
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent(
      "5 comments, 2 need your judgement. 1 value met, 4,362 clauses not applicable (hidden). The reader gave up on pages 4 and 9.",
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

  describe("order 95 piece 6c: Save decisions", () => {
    it("a Keep stays on screen, holds both exports, and one Save confirms its finding", async () => {
      mount();
      await screen.findByTestId("crs-headline");
      expect(screen.queryByTestId("save-bar")).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Keep comment 1" }));
      expect(confirm).not.toHaveBeenCalled();
      expect(screen.getByTestId("save-bar")).toHaveTextContent("1 decision not saved yet");
      expect(screen.getByRole("button", { name: /Sign and export/ })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Download working copy" })).toBeDisabled();
      await userEvent.click(screen.getByRole("button", { name: "Save decisions" }));
      expect(confirm).toHaveBeenCalledWith("a");
      expect(await screen.findByText("1 decision saved to the record.")).toBeInTheDocument();
      expect(screen.queryByTestId("save-bar")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Download working copy" })).toBeEnabled();
    });

    it("an edit saves the Required action as the engineer's comment; the Observation is read only", async () => {
      mount();
      await screen.findByTestId("crs-headline");
      await userEvent.click(screen.getByRole("button", { name: "Edit wording of comment 1" }));
      expect(screen.getByLabelText("Observation for comment 1")).toHaveAttribute("readonly");
      const action = screen.getByLabelText("Required action for comment 1");
      await userEvent.clear(action);
      await userEvent.type(action, "Contractor to state the set pressure in barg.");
      await userEvent.click(screen.getByRole("button", { name: "Save wording" }));
      await userEvent.click(screen.getByRole("button", { name: "Save decisions" }));
      expect(update).toHaveBeenCalledWith("a", { engineer_comment: "Contractor to state the set pressure in barg." });
      expect(confirm).not.toHaveBeenCalled();
    });

    it("a Remove sends a reject with its listed reason code", async () => {
      mount();
      await screen.findByTestId("crs-headline");
      await userEvent.click(screen.getByRole("button", { name: "Remove comment 1" }));
      await userEvent.selectOptions(screen.getByLabelText("Why remove comment 1?"), "Duplicate");
      await userEvent.click(screen.getByRole("button", { name: "Remove" }));
      await userEvent.click(screen.getByRole("button", { name: "Save decisions" }));
      expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "a", "reject", "", "duplicate");
    });

    it("a row the server refuses stays unsaved and says why", async () => {
      confirm.mockResolvedValue({ ok: false, error: { code: "forbidden", message: "Not allowed." } });
      mount();
      await screen.findByTestId("crs-headline");
      await userEvent.click(screen.getByRole("button", { name: "Keep comment 1" }));
      await userEvent.click(screen.getByRole("button", { name: "Save decisions" }));
      expect(await screen.findByText(/1 not saved: Comment 1: Not allowed\./)).toBeInTheDocument();
      expect(screen.getByTestId("save-bar")).toHaveTextContent("1 decision not saved yet");
      expect(screen.getByRole("button", { name: /Sign and export/ })).toBeDisabled();
    });

    it("leaving with unsaved decisions warns first", async () => {
      const onBack = vi.fn();
      render(<CrsSheetView runId="run-1" onBack={onBack} onOpenCards={vi.fn()} />);
      await screen.findByTestId("crs-headline");
      await userEvent.click(screen.getByRole("button", { name: "Keep comment 1" }));
      const unload = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(unload);
      expect(unload.defaultPrevented).toBe(true);
      const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
      await userEvent.click(screen.getByRole("button", { name: "← Reviews" }));
      expect(ask).toHaveBeenCalled();
      expect(onBack).not.toHaveBeenCalled();
      ask.mockRestore();
    });
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

  it("piece 4: the drawer moves comment to comment and page to page on a long document", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: /Open evidence for Comment 1/ }));
    const dialog = () => screen.getByRole("dialog");
    const position = () => within(dialog()).getByTestId("drawer-position").textContent ?? "";
    expect(position()).toMatch(/^Row 1 of \d+$/);
    expect(within(dialog()).getByRole("button", { name: "← Previous" })).toBeDisabled();
    expect(within(dialog()).getByTestId("drawer-page")).toHaveTextContent("Page 1 of 12");
    // the strip: the comment pages plus the first and the last page (12)
    const strip = within(within(dialog()).getByTestId("drawer-strip")).getAllByRole("button").map((b) => b.textContent);
    expect(strip[0]).toBe("1");
    expect(strip[strip.length - 1]).toBe("12");
    // Next, and the J key, move along the rows shown
    await userEvent.click(within(dialog()).getByRole("button", { name: "Next →" }));
    expect(position()).toMatch(/^Row 2 of /);
    await userEvent.keyboard("j");
    expect(position()).toMatch(/^Row 3 of /);
    await userEvent.keyboard("k");
    expect(position()).toMatch(/^Row 2 of /);
    // a page with no comment can be looked at, and says so
    await userEvent.type(within(dialog()).getByLabelText("Go to page"), "11{Enter}");
    expect(within(dialog()).getByTestId("drawer-page")).toHaveTextContent("Page 11 of 12 - no comment on this page");
    expect(dialog()).toHaveTextContent("submittal page 11");
    // a page outside the document is refused in words
    await userEvent.type(within(dialog()).getByLabelText("Go to page"), "40{Enter}");
    expect(within(dialog()).getByRole("alert")).toHaveTextContent("Type a page from 1 to 12.");
    // PageUp from page 11 opens the last comment page before it
    await userEvent.keyboard("{PageUp}");
    expect(within(dialog()).getByTestId("drawer-page")).toHaveTextContent(/^Page 4 of 12$/);
  });

  it("piece 4: the drawer's history reads the run's decision record, earlier decisions and reasons included", async () => {
    crsDecisions.mockResolvedValue({ ok: true, data: { decisions: [
      { id: "2", review_run_id: "run-1", kind: "finding", subject: "a", decision: "reject", reason: "same point as comment 3",
        decided_by: "Ali", decided_at: "2026-10-17T09:00:00Z", reason_code: "duplicate" },
      { id: "1", review_run_id: "run-1", kind: "finding", subject: "a", decision: "accept", reason: "breach confirmed by eye",
        decided_by: "Ali", decided_at: "2026-10-16T09:00:00Z", reason_code: null },
    ] } });
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: /Open evidence for Comment 1/ }));
    const history = await screen.findByTestId("drawer-history");
    await waitFor(() => expect(history).toHaveTextContent("Comment removed by Ali (Duplicate): same point as comment 3"));
    expect(history).toHaveTextContent("Comment accepted by Ali: breach confirmed by eye");
    expect(crsDecisions).toHaveBeenCalledWith("run-1");
    expect(screen.queryByTestId("drawer-history-partial")).toBeNull();
  });

  it("piece 4: when the decision record cannot be read, the drawer says its history may be missing decisions", async () => {
    crsDecisions.mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "Cannot reach the backend." } });
    mount();
    await screen.findByTestId("crs-headline");
    await userEvent.click(screen.getByRole("button", { name: /Open evidence for Comment 1/ }));
    expect(await screen.findByTestId("drawer-history-partial")).toHaveTextContent("could not be loaded");
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
    expect(screen.getByLabelText("Required action for comment 1")).toHaveFocus();
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

function summaryOf(rows: RunSummaryTierRow[], over: Partial<ReviewRunTierSummary> = {}): ReviewRunTierSummary {
  return {
    review_run_id: "run-1", status: "completed", boundary: "findings of this run, on the submittal you may read",
    counts: { met: 40, not_applicable: 2, another_document: 1, comment: 11, needs_you: 3, removed: 4, total: 61 },
    rows,
    how_reviewed: {
      requirement_split: { checked: 90, applies_not_checked: 0, does_not_apply: 1200, total: 1290, applies_not_checked_reasons: [], does_not_apply_reasons: [], repeats_ignored: null, unchecked_share: 0 },
      page_coverage: { pages_total: 12, fact_pages: [1, 2, 3], pages_not_read_into_fields: [4], not_read_reasons: {} },
      completeness: null, reader: null, timed_out_pages: [7], code_version: null, config_version: null,
      stage_seconds: null, clauses_by_standard: null,
    },
    ...over,
  };
}

function tierRow(finding_id: string, tier: RunSummaryTierRow["tier"], label: RunSummaryTierRow["label"], reason: RunSummaryTierRow["reason"] = null): RunSummaryTierRow {
  return { finding_id, tier, label, reason };
}

/** The server's answer for this file's findings when it agrees with the screen. */
function agreeingRows(): RunSummaryTierRow[] {
  return [
    tierRow("a", "B", "Comment"), tierRow("b", "B", "Comment"), tierRow("blank", "B", "Comment"),
    tierRow("cond", "C", "Needs you", "condition unsettled"), tierRow("unread", "C", "Needs you", "page not read"),
    tierRow("met", "A", "Met"), tierRow("scope", "A", "Another document"),
  ];
}

function tierOfRow(item: string): string {
  const row = rows().find((r) => within(r).getAllByRole("cell")[3].textContent === item);
  return within(row as HTMLElement).getAllByRole("cell")[0].textContent ?? "";
}

describe("CrsSheetView reads the run summary (order 95 piece 1, #1111)", () => {
  it("when the summary answers, the headline counts the table's rows and reads the server's stored fields, with no fallback note", async () => {
    const base = summaryOf(agreeingRows());
    reviewRunSummary.mockResolvedValue({ ok: true, data: { ...base, how_reviewed: { ...base.how_reviewed, stage_seconds: { extract: 900, compare: 180 } } } });
    mount();
    // Order 112: the server's finding counts (11 + 3 comments, 40 met) do not
    // make the headline: the table's 5 comment rows and 1 met row do. The
    // server's does_not_apply (1,200), its unread pages (4 read into no
    // field, 7 timed out) and its stored trace (900 + 180 s) do.
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent(
      "5 comments, 2 need your judgement. 1 value met, 1,200 clauses not applicable (hidden). Read in 18 min; the reader gave up on pages 4 and 7.",
    );
    expect(rows().filter((r) => !/^Met/.test(within(r).getAllByRole("cell")[0].textContent ?? ""))).toHaveLength(5);
    expect(reviewRunSummary).toHaveBeenCalledWith("run-1");
    expect(screen.queryByTestId("crs-tier-source")).not.toBeInTheDocument();
    // The engineer-removed count is the server's too.
    expect(screen.getByTestId("crs-rejected")).toHaveTextContent("Left off this sheet: 4 findings already rejected by an engineer.");
  });

  it("when the summary 404s (route not on this server), the screen's own tiers stand in and one small note says so", async () => {
    mount();
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent(
      "5 comments, 2 need your judgement. 1 value met, 4,362 clauses not applicable (hidden). The reader gave up on pages 4 and 9.",
    );
    expect(screen.getByTestId("crs-tier-source")).toHaveTextContent("Tiers worked out on this screen: the run summary was not available from the server.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(tierOfRow("Field cond")).toContain("Needs you: condition unsettled");
  });

  it("when the summary read fails outright, the sheet still renders on the screen's tiers", async () => {
    reviewRunSummary.mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "Cannot reach the backend." } });
    mount();
    await screen.findByTestId("crs-headline");
    expect(screen.getByTestId("crs-tier-source")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(rowItems()).toEqual(["Field a", "Field blank", "Field b", "Field cond", "Field unread", "Field met"]);
  });

  it("when server and screen tiers disagree, the server wins", async () => {
    // The screen would call "a" a Comment (NON_COMPLIANT) and "cond" Needs you
    // (CONDITIONAL); the server says the opposite, with its own reason.
    reviewRunSummary.mockResolvedValue({ ok: true, data: summaryOf(agreeingRows().map((r) => (
      r.finding_id === "a" ? tierRow("a", "C", "Needs you", "value conflict")
        : r.finding_id === "cond" ? tierRow("cond", "B", "Comment")
          : r))) });
    mount();
    await screen.findByTestId("crs-headline");
    expect(tierOfRow("Field a")).toContain("Needs you: value conflict");
    expect(tierOfRow("Field cond")).toBe("Comment");
    expect(screen.getByTestId("sign-waits")).toHaveTextContent('opened the 2 rows marked "Needs you"');
    // "a" (page 1) is still comment 1, now a Needs-you row; Sign waits for it and
    // "unread", not for "cond", which the server calls a plain Comment.
    expect(rows()[0]).toHaveAttribute("data-tier", "C");
    await userEvent.click(screen.getByRole("button", { name: "Open evidence for Comment 1: Field a" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Why it needs you: value conflict");
    await userEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    await userEvent.click(screen.getByRole("button", { name: "Open evidence for Comment 5: Field unread" }));
    await userEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(screen.getByRole("button", { name: /Sign and export/ })).toBeEnabled();
  });

  it("the header links to How this was reviewed at /review/<run>/how through the app's navigation", async () => {
    const navigate = vi.fn();
    render(
      <NavigationContext.Provider value={navigate}>
        <CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />
      </NavigationContext.Provider>,
    );
    await screen.findByTestId("crs-headline");
    const link = screen.getByRole("link", { name: "How this was reviewed" });
    expect(link).toHaveAttribute("href", "/review/run-1/how");
    await userEvent.click(link);
    expect(navigate).toHaveBeenCalledWith("review", "run-1", "how");
  });

  it("order 115: the header opens the card view at /review/<run>/cards", async () => {
    const navigate = vi.fn();
    render(
      <NavigationContext.Provider value={navigate}>
        <CrsSheetView runId="run-1" onBack={vi.fn()} onOpenCards={vi.fn()} />
      </NavigationContext.Provider>,
    );
    await screen.findByTestId("crs-headline");
    const link = screen.getByRole("link", { name: "Open the card view" });
    expect(link).toHaveAttribute("href", "/review/run-1/cards");
    await userEvent.click(link);
    expect(navigate).toHaveBeenCalledWith("review", "run-1", "cards");
  });
});
