/**
 * Owner order section 3 (screen, part A), on made-up runs and findings:
 *  - the readiness strip: pages read N of M, standards held / missing, and
 *    the link to upload the missing ones;
 *  - "Nothing changed since the last run" is asked BEFORE a re-run;
 *  - the four totals and the counts by kind, with their boundary;
 *  - Review notes collapsed, fetched when opened;
 *  - runs grouped per document, earlier runs collapsed.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewReadiness, ReviewRunSummary } from "../types/api";
import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const list = vi.fn();
const readiness = vi.fn();
const previewCrs = vi.fn();
const startReviewRun = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    list: (...args: unknown[]) => list(...args),
    readiness: (...args: unknown[]) => readiness(...args),
    previewCrs: (...args: unknown[]) => previewCrs(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
    reviewRunStandards: async () => ({ ok: true, data: { standards: [] } }),
    exportCrs: vi.fn(),
    decideCode: vi.fn(),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-2",
    submittal_document_id: "doc-sub",
    submittal_filename: "vessel.pdf",
    equipment_tags: [],
    status: "completed",
    created_at: "2026-09-21T00:00:00Z",
    standards_in_scope: 1,
    findings_total: 0,
    by_status: {},
    ...over,
  } as ReviewRunSummary;
}

function ready(over: Partial<ReviewReadiness> = {}): ReviewReadiness {
  return {
    submittal_document_id: "doc-sub",
    pages_total: 5,
    pages_read: 3,
    unread_pages: [4, 5],
    standards_cited: 3,
    standards_held: ["API 999.pdf"],
    standards_missing: ["API 998", "API 997"],
    last_run_id: "run-2",
    nothing_changed: false,
    changes: ["2 datasheet value(s) read since the last run"],
    ...over,
  };
}

function finding(over: Partial<ReviewFinding>): ReviewFinding {
  return { id: Math.random().toString(36), document_id: "doc-sub", finding: "x", ...over } as ReviewFinding;
}

beforeEach(() => {
  for (const mock of [documents, reviewRuns, list, readiness, previewCrs, startReviewRun]) mock.mockReset();
  documents.mockResolvedValue({
    ok: true,
    data: [{ id: "doc-sub", filename: "vessel.pdf", document_role: "CONTRACTOR_SUBMITTAL" }],
  });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run()] } });
  list.mockResolvedValue({ ok: true, data: { findings: [] } });
  readiness.mockResolvedValue({ ok: true, data: ready() });
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-3" } });
});

async function pickSubmittal() {
  await userEvent.selectOptions(await screen.findByLabelText("Submittal"), "doc-sub");
  return screen.findByTestId("readiness-strip");
}

describe("the readiness strip", () => {
  it("states pages read and standards held and missing, with denominators", async () => {
    const onOpenStandards = vi.fn();
    render(<ReviewRunsView onOpenStandards={onOpenStandards} />);
    const strip = within(await pickSubmittal());

    expect(readiness).toHaveBeenCalledWith("doc-sub");
    expect(strip.getByText(/Pages read: 3 of 5/)).toBeInTheDocument();
    expect(strip.getByText(/not read: 4/)).toBeInTheDocument();
    expect(strip.getByText(/Standards cited: 1 held, 2 missing \(of 3\)/)).toBeInTheDocument();
    expect(strip.getByText(/2 datasheet value\(s\) read since the last run/)).toBeInTheDocument();

    await userEvent.click(strip.getByRole("button", { name: "Upload missing standards" }));
    expect(onOpenStandards).toHaveBeenCalled();
  });

  it("offers no upload link when nothing is missing", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ standards_missing: [], standards_cited: 1 }) });
    render(<ReviewRunsView onOpenStandards={vi.fn()} />);
    const strip = within(await pickSubmittal());
    expect(strip.queryByRole("button", { name: "Upload missing standards" })).toBeNull();
  });
});

describe("a re-run that cannot say anything new", () => {
  it("is asked about first when nothing changed", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ nothing_changed: true, changes: [] }) });
    render(<ReviewRunsView />);
    await pickSubmittal();

    await userEvent.click(screen.getByRole("button", { name: "Run AI review" }));
    expect(screen.getByRole("alertdialog", { name: "Nothing changed since the last run" }))
      .toBeInTheDocument();
    expect(startReviewRun).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Run again anyway" }));
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
  });

  it("runs straight away when something changed", async () => {
    render(<ReviewRunsView />);
    await pickSubmittal();
    await userEvent.click(screen.getByRole("button", { name: "Run AI review" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
  });
});

describe("the run summary", () => {
  it("gives the four totals and the counts by kind, AI drafts not counted", async () => {
    list.mockResolvedValue({
      ok: true,
      data: {
        findings: [
          finding({ compliance_status: "COMPLIANT" }),
          finding({ compliance_status: "NON_COMPLIANT" }),
          finding({ compliance_status: "NON_COMPLIANT", origin: "datasheet_check" }),
          finding({ compliance_status: "NEEDS_ENGINEER_REVIEW" }),
          finding({ compliance_status: "MISSING_INFORMATION" }),
          finding({ compliance_status: "NOT_IN_DOCUMENT_SCOPE" }),
          finding({ compliance_status: null, origin: "ai_engineering_check" }),
          finding({ compliance_status: null, origin: "ai_engineering_check", confirmed_by: "u1" }),
          finding({ compliance_status: "NON_COMPLIANT", approval_status: "rejected" }),
        ],
      },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /vessel\.pdf/i }));
    const summary = within(await screen.findByTestId("run-summary"));

    const value = (label: string) => summary.getByText(label).nextElementSibling?.textContent;
    expect(value("Meets")).toBe("1");
    expect(value("Does not meet")).toBe("2");
    expect(value("Needs a decision")).toBe("1");
    expect(value("Could not be checked")).toBe("2");
    expect(summary.getByText(/Of 6 requirement checks in this run/)).toBeInTheDocument();
    expect(summary.getByTestId("kind-counts").textContent).toMatch(
      /A - checked against a standard 5 · B - datasheet check 1 · C - AI engineering check 1 confirmed, 1 to confirm/);
  });
});

describe("review notes on screen", () => {
  it("are collapsed and fetched only when opened", async () => {
    previewCrs.mockResolvedValue({
      ok: true,
      data: { rows: [], review_notes: [
        { note: "Requires another document", standard: "API 999.pdf", count: 12, detail: "name their own evidence" },
      ] },
    });
    render(<ReviewRunsView />);
    await userEvent.click(await screen.findByRole("button", { name: /vessel\.pdf/i }));
    const notes = await screen.findByTestId("review-notes");
    expect(notes).not.toHaveAttribute("open");
    expect(previewCrs).not.toHaveBeenCalled();

    await userEvent.click(within(notes).getByText("Review notes - internal"));
    expect(await within(notes).findByText("Requires another document")).toBeInTheDocument();
    expect(previewCrs).toHaveBeenCalledWith("run-2");
  });
});

describe("runs grouped per document", () => {
  it("shows the latest run and collapses the earlier ones", async () => {
    reviewRuns.mockResolvedValue({
      ok: true,
      data: { runs: [
        run({ review_run_id: "run-1", created_at: "2026-09-20T00:00:00Z", recommended_code: "Code 1" }),
        run({ review_run_id: "run-2", created_at: "2026-09-21T00:00:00Z", recommended_code: "Code 2" }),
        run({ review_run_id: "run-9", submittal_document_id: "doc-other", submittal_filename: "pump.pdf" }),
      ] },
    });
    render(<ReviewRunsView />);
    const earlier = await screen.findByTestId("earlier-runs");
    expect(earlier).not.toHaveAttribute("open");
    expect(within(earlier).getByText("1 earlier run of this document")).toBeInTheDocument();
    // The latest is the card outside the collapsed group.
    const latestCards = screen.getAllByRole("button", { name: /vessel\.pdf/i })
      .filter((card) => !earlier.contains(card));
    expect(latestCards).toHaveLength(1);
    expect(latestCards[0]).toHaveTextContent("Code 2");
    expect(within(earlier).getByRole("button", { name: /vessel\.pdf/i })).toHaveTextContent("Code 1");
    expect(screen.getAllByTestId("earlier-runs")).toHaveLength(1);
  });
});
