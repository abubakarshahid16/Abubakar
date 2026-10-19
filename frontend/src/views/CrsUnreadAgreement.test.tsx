/**
 * Order 127: one unread-pages count on the comment sheet.
 *
 * The header line, the "Before you sign" box and the footer read the same
 * run; they must name the same number of unread pages. On the owner's run the
 * header said "the reader gave up on pages 1-3, 5 and 11" (5: the code
 * readers' unread pages plus the AI reader's time-outs) while the box asked
 * ticks for 11 pages (the server's gate, which since PF3 also counts every
 * page the AI reader did not read). Made-up data only.
 *
 * MUTATION PROOF: make the box count `gate.unread_pages` alone (left to tick,
 * the old count) and "header, box and footer name the same count" fails (10
 * against 11); make the header union pages_not_read_into_fields and
 * timed_out_pages again (the old `headlineFieldsOf`) and the same test and
 * the pure check fail (5 against 11).
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { headlineFieldsOf } from "../components/review/crs/crsRows";
import { unreadPagesCount, unreadPagesLine } from "../components/review/crs/issueGate";
import type { CrsIssueGate, ReviewFinding, ReviewRunSummary, ReviewRunTierSummary } from "../types/api";
import { CrsSheetView } from "./CrsSheetView";

const reviewRuns = vi.fn();
const list = vi.fn();
const reviewRunSummary = vi.fn();
const crsIssueGate = vi.fn();
// Hoisted with vi.mock below, which runs before the module body.
const ok = vi.hoisted(() => (data: unknown) => async () => ({ ok: true, data }));

vi.mock("../api/client", () => ({
  api: { document: async () => ({ ok: true, data: { id: "doc-sub", filename: "made-up.pdf", page_count: 11, equipment_type: "Control valve", revision: "A" } }) },
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    reviewRun: async (id: string) => {
      const r = await reviewRuns(id);
      return r?.ok ? { ok: true, data: r.data.runs.find((x: { review_run_id: string }) => x.review_run_id === id) ?? null } : r;
    },
    list: (...a: unknown[]) => list(...a),
    reviewRunStandards: ok({ standards: [], missing_references: [] }),
    reviewRunSummary: (...a: unknown[]) => reviewRunSummary(...a),
    exportCrs: ok({}),
    confirm: ok({}),
    update: ok({}),
    decideCrsFinding: ok({}),
    crsDecisions: ok({ decisions: [] }),
    crsIssueGate: (...a: unknown[]) => crsIssueGate(...a),
    decideCrsPage: ok({}),
    decideCode: ok({}),
    cancelJob: vi.fn(),
  },
}));
vi.mock("../components/review/sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <p>{`submittal page ${page}`}</p>,
}));

const ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
/** The made-up run: 11 pages, the code readers read no value from 1-3, 5 and
 *  11, and the AI reader was unavailable, so it read none of the 11. */
const COVERAGE = {
  pages_total: 11, fact_pages: [4, 6, 7, 8, 9, 10], pages_not_read_into_fields: [1, 2, 3, 5, 11], not_read_reasons: {},
  pages_ai_not_read: ALL,
};

function theRun(): ReviewRunSummary {
  return {
    review_run_id: "run-u", submittal_document_id: "doc-sub", submittal_filename: "made-up.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-15T08:00:00Z", completed_at: "2026-10-15T08:18:00Z",
    standards_in_scope: 1, findings_total: 1, by_status: { NON_COMPLIANT: 1 },
    recommended_code: "Approved with Comments", recommended_reason: "One value does not meet the standard.",
    requirement_split: null, completeness: null, page_coverage: COVERAGE, unread_pages: ALL, engineer_final_code: "Approved with Comments",
    review_codes: [], table_values_not_compared: [], requirements_not_applied: [], partial_findings: 0,
  } as ReviewRunSummary;
}

function theSummary(): ReviewRunTierSummary {
  return {
    review_run_id: "run-u", status: "completed", boundary: "findings of this run, on the submittal you may read",
    counts: { met: 0, not_applicable: 0, another_document: 0, comment: 1, needs_you: 0, removed: 0, total: 1 },
    rows: [{ finding_id: "x", tier: "B", label: "Comment", reason: null }],
    how_reviewed: {
      requirement_split: null, page_coverage: COVERAGE, completeness: null, reader: null,
      timed_out_pages: [], code_version: null, config_version: null, stage_seconds: null, clauses_by_standard: null,
      unread_pages: ALL,
    },
  };
}

/** The server's gate on the same run: page 4 ticked by an engineer, the other
 *  ten left to tick. */
function theGate(checked: number[] = [4]): CrsIssueGate {
  const left = ALL.filter((p) => !checked.includes(p));
  return {
    review_run_id: "run-u", issuable: false, final_code_recorded: true,
    blockers: ["pages"], unread_pages: left.map((page) => ({ page, reason: null })), open_findings: [],
    checked_pages: checked, pages_total: 11,
  };
}

const COUNT = /(\d+) of (\d+) pages? (?:was|were) not fully read/;

function countIn(testId: string): [number, number] {
  const m = COUNT.exec(screen.getByTestId(testId).textContent ?? "");
  expect(m, `${testId} names no "N of T pages were not fully read"`).not.toBeNull();
  return [Number(m?.[1]), Number(m?.[2])];
}

function footerCount(): [number, number] {
  const m = /Pages not fully read: (\d+) of (\d+)/.exec(screen.getByTestId("crs-footer").textContent ?? "");
  expect(m, "the footer names no \"Pages not fully read: N of T\"").not.toBeNull();
  return [Number(m?.[1]), Number(m?.[2])];
}

let gate: CrsIssueGate;
beforeEach(() => {
  gate = theGate();
  reviewRuns.mockReset().mockResolvedValue({ ok: true, data: { runs: [theRun()] } });
  list.mockReset().mockResolvedValue({ ok: true, data: { findings: [
    { id: "x", compliance_status: "NON_COMPLIANT", matched_phrase: "Body rating", finding: "x found", required_action: "Contractor to fix x.",
      contractor_page: 6, approval_status: "pending", standard_document_id: "std-1", standard_clause: "4.1" } as ReviewFinding,
  ] } });
  reviewRunSummary.mockReset().mockResolvedValue({ ok: true, data: theSummary() });
  crsIssueGate.mockReset().mockImplementation(async () => ({ ok: true, data: gate }));
});

function mount() {
  return render(<CrsSheetView runId="run-u" onBack={vi.fn()} onOpenCards={vi.fn()} />);
}

describe("order 127: header, box and footer name one unread-pages count", () => {
  it("header, box and footer name the same count, from the same run summary and gate", async () => {
    mount();
    await screen.findByTestId("crs-headline");
    await screen.findByTestId("sign-pages");
    const header = countIn("crs-headline");
    const box = countIn("sign-pages");
    expect(box).toEqual([11, 11]);
    expect(header).toEqual(box);
    expect(footerCount()).toEqual(box);
    expect(screen.getByTestId("sign-pages")).toHaveTextContent("11 of 11 pages were not fully read: 1 checked by an engineer, 10 left to tick.");
  });

  it("with the summary route missing (404), the runs list's copy gives the header the same count", async () => {
    reviewRunSummary.mockResolvedValue({ ok: false, disconnected: false, error: { code: "internal", message: "That is not something the backend knows about." } });
    mount();
    await screen.findByTestId("crs-headline");
    await screen.findByTestId("sign-pages");
    expect(countIn("crs-headline")).toEqual([11, 11]);
    expect(countIn("crs-headline")).toEqual(countIn("sign-pages"));
  });

  it("the order's case, nothing ticked yet: the header and the box say the same words", async () => {
    gate = theGate([]);
    mount();
    expect(await screen.findByTestId("crs-headline")).toHaveTextContent("11 of 11 pages were not fully read (1-11).");
    expect(await screen.findByTestId("sign-pages")).toHaveTextContent("11 of 11 pages were not fully read. Tick each one once you have checked it yourself.");
    expect(screen.getByTestId("crs-headline")).not.toHaveTextContent("gave up");
  });

  it("pure: the header's list is the gate's left-to-tick plus checked pages", () => {
    const fields = headlineFieldsOf(theRun(), theSummary().how_reviewed);
    const { left, checked, notRead } = unreadPagesCount(gate);
    expect(left + checked).toBe(notRead);
    expect(fields.unreadPages).toHaveLength(notRead);
    expect(headlineFieldsOf(theRun()).unreadPages).toHaveLength(notRead);
  });
});

describe("order 127: the box's words (spec section 5)", () => {
  const g = (left: number[], checked: number[] | undefined, total: number | null | undefined): CrsIssueGate => ({
    review_run_id: "r", issuable: false, final_code_recorded: true, blockers: [], open_findings: [],
    unread_pages: left.map((page) => ({ page, reason: null })), checked_pages: checked, pages_total: total,
  });

  it("says the count with its total, then what is checked and what is left", () => {
    expect(unreadPagesLine(g(ALL, [], 11))).toEqual({ done: false, text: "11 of 11 pages were not fully read. Tick each one once you have checked it yourself." });
    expect(unreadPagesLine(g([1, 2, 3, 5, 6, 7, 8, 9, 10], [4, 11], 11)).text).toBe("11 of 11 pages were not fully read: 2 checked by an engineer, 9 left to tick.");
    expect(unreadPagesLine(g([4], [], 12)).text).toBe("1 of 12 pages was not fully read. Tick each one once you have checked it yourself.");
  });

  it("is done when every unread page was checked, or every page was read", () => {
    expect(unreadPagesLine(g([], ALL, 11))).toEqual({ done: true, text: "11 of 11 pages were not fully read; an engineer checked all 11." });
    expect(unreadPagesLine(g([], [4], 12))).toEqual({ done: true, text: "1 of 12 pages was not fully read; an engineer checked it." });
    expect(unreadPagesLine(g([], [], 12))).toEqual({ done: true, text: "Every page was read." });
  });

  it("drops 'of T' when the total is not sent, and never calls pages read when the server says no record is stored", () => {
    expect(unreadPagesLine(g([4, 9], undefined, undefined)).text).toBe("2 pages were not fully read. Tick each one once you have checked it yourself.");
    expect(unreadPagesLine(g([], undefined, undefined))).toEqual({ done: true, text: "Every page was read or checked by an engineer." });
    expect(unreadPagesLine(g([], [], null))).toEqual({ done: false, text: "Which pages were read is not recorded on this run." });
  });
});
