/**
 * The findings, standards, steps and numbers pages behind the Sheet (#967
 * PR 3). Ported from the old page's tests (B5, #453, #598, #678, #791, the
 * run summary, audit 2026-09-30); the words are unchanged.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { BehindTheScenes, type BehindTheScenesProps } from "./BehindTheScenes";

vi.mock("../../../api/client", () => ({
  api: { document: vi.fn(async () => ({ ok: false, error: { message: "nf" } })) },
  reviews: {
    reviewTrace: async () => ({ ok: false, error: { message: "not in this test" } }),
    runCoverage: async () => ({ ok: true, data: { line: "4 of 9 applicable requirement(s) checked (44.4%)" } }),
    reviewRunStandardsAll: async () => ({ ok: true, data: { standards: [] } }),
    overrideRunStandard: vi.fn(), update: vi.fn(), confirm: vi.fn(), rejectPairing: vi.fn(),
    previewCrs: vi.fn(), exportCrs: vi.fn(), crsIssueGate: vi.fn(),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "drum.pdf",
    equipment_tags: ["V-101"], status: "completed", created_at: "2026-09-20T00:00:00Z",
    standards_in_scope: 2, findings_total: 1, by_status: { MISSING_INFORMATION: 1 },
    recommended_code: "Manual Review Required", ...over,
  } as ReviewRunSummary;
}

function finding(over: Partial<ReviewFinding>): ReviewFinding {
  return { id: Math.random().toString(36), document_id: "doc-sub", finding: "x", ...over } as ReviewFinding;
}

function page(over: Partial<BehindTheScenesProps> = {}) {
  const props: BehindTheScenesProps = {
    panel: "steps", run: run(), findings: [], documents: [],
    standardsState: { standards: [], missing: [], error: null }, focusStatus: null,
    onOpenPanel: vi.fn(), onFocusStatus: vi.fn(), onStandardsChanged: vi.fn(), onChanged: vi.fn(),
    ...over,
  };
  render(<BehindTheScenes {...props} />);
  return props;
}

describe("#453: requirements about a different kind of equipment", () => {
  it("shows one expandable line per subject, never dropping them silently", async () => {
    page({ run: run({ requirements_not_applied: [{
      subject: "steam turbine", submittal_equipment: "relief valve", count: 12,
      line: "12 requirements not applied: they are about steam turbine, this submittal is relief valve",
      standards: [{ standard_document_id: "s1", standard_name: "SAES-J-600.pdf", count: 12, clauses: ["8.7", "8.8", "8.9.3"] }],
    }] }) });
    const block = await screen.findByTestId("requirements-not-applied");
    expect(within(block).getByText(/12 requirements not applied: they are about steam turbine/)).toBeInTheDocument();
    expect(within(block).getByText(/12 in SAES-J-600\.pdf, clauses 8\.7, 8\.8, 8\.9\.3/)).toBeInTheDocument();
  });

  it("shows nothing when every requirement applied", async () => {
    page();
    await screen.findByTestId("run-coverage");
    expect(screen.queryByTestId("requirements-not-applied")).toBeNull();
  });
});

describe("#598: table values that were not compared", () => {
  it("shows one expandable line per standard, never dropping them silently", async () => {
    page({ run: run({ table_values_not_compared: [{
      standard_document_id: "std-1", standard_name: "NACE-X.pdf", count: 57, table_count: 2,
      line: "57 table values in 2 tables of NACE-X.pdf not compared: no matching field on this submittal",
      tables: [{ page: 4, count: 30, examples: ["UNS S32205"] }, { page: 9, count: 27, examples: [] }],
    }] }) });
    const block = await screen.findByTestId("table-values-not-compared");
    expect(within(block).getByText(/57 table values in 2 tables of NACE-X\.pdf not compared/)).toBeInTheDocument();
    expect(within(block).getByText(/30 on page 4, for example UNS S32205/)).toBeInTheDocument();
  });

  it("shows nothing for a run with no unmatched table values", async () => {
    page();
    await screen.findByTestId("run-coverage");
    expect(screen.queryByTestId("table-values-not-compared")).toBeNull();
  });
});

describe("#678: the three groups of requirements", () => {
  const split = {
    checked: 40, applies_not_checked: 30, does_not_apply: 10, total: 80,
    applies_not_checked_reasons: [
      { reason: "the column name matches no field on this submittal", count: 25 },
      { reason: "no reason recorded", count: 5 }],
    does_not_apply_reasons: [{ reason: "about steam turbine, this submittal is relief valve", count: 10 }],
    repeats_ignored: 4, unchecked_share: 30 / 70,
  };

  it("shows checked, apply-but-not-checked and do-not-apply as three numbers with their reasons", async () => {
    page({ run: run({ requirement_split: split }) });
    const panel = await screen.findByTestId("requirement-split");
    expect(within(panel).getByTestId("split-checked")).toHaveTextContent("40 checked");
    const notChecked = within(panel).getByTestId("split-not-checked");
    expect(notChecked).toHaveTextContent("30 apply but were not checked");
    expect(notChecked).toHaveTextContent("the column name matches no field on this submittal (25)");
    expect(notChecked).toHaveTextContent("no reason recorded (5)");
    expect(within(panel).getByTestId("split-not-apply")).toHaveTextContent("10 do not apply");
    // The share is of the requirements that APPLY (70), never of all 80.
    expect(panel).toHaveTextContent("30 of 70 (43%) of those that apply were not checked");
  });

  it("shows no share when no requirement applies, never 0%", async () => {
    page({ run: run({ requirement_split: { ...split, checked: 0, applies_not_checked: 0, does_not_apply: 5, total: 5,
      applies_not_checked_reasons: [], unchecked_share: null } }) });
    const panel = await screen.findByTestId("requirement-split");
    expect(panel.textContent).not.toMatch(/%/);
  });

  it("shows nothing for a run with no counts", async () => {
    page();
    await screen.findByTestId("run-coverage");
    expect(screen.queryByTestId("requirement-split")).toBeNull();
  });

  it("PF4: shows the run's clause coverage line", async () => {
    page();
    expect(await screen.findByTestId("run-coverage")).toHaveTextContent("4 of 9 applicable requirement(s) checked (44.4%)");
  });
});

describe("#791: a count in the review steps opens the findings it counts", () => {
  it("clicking a status count asks for the findings page with that status", async () => {
    const props = page({ run: run({ findings_total: 2, by_status: { COMPLIANT: 1, NON_COMPLIANT: 1 } }) });
    await userEvent.click(await screen.findByRole("button", { name: /^Compliant 1 of 2/ }));
    expect(props.onFocusStatus).toHaveBeenCalledWith("COMPLIANT");
    expect(props.onOpenPanel).toHaveBeenCalledWith("findings");
  });

  it("the findings page then shows only that status", async () => {
    const findings = [
      finding({ id: "f1", compliance_status: "COMPLIANT", requirement: "Met requirement." }),
      finding({ id: "f2", compliance_status: "NON_COMPLIANT", requirement: "Breached requirement." }),
    ];
    page({ panel: "findings", findings, focusStatus: "COMPLIANT" });
    expect(screen.getByText("Met requirement.")).toBeInTheDocument();
    expect(screen.queryByText("Breached requirement.")).toBeNull();
    expect(screen.getByLabelText("Filter by status")).toHaveValue("COMPLIANT");
  });
});

describe("B5: the standards in scope carry their evidence and the missing ones", () => {
  it("shows the citation line and the cited standards not held", async () => {
    page({ panel: "standards", standardsState: {
      standards: [{
        standard_document_id: "std-610", filename: "API-610.pdf", selection_method: "referenced",
        selection_reason: "named in the submittal as API 610 (page 1)", confidence: 0.9, included: true,
        exclusion_reason: null, evidence_page: 1, evidence_quote: "Pump shall comply with API 610 and API 682.",
        scope_decision: null,
      }],
      missing: [{ identifier: "API 682", status: "MISSING_LOCALLY" }], error: null } });
    expect(screen.getByText("API-610.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Evidence, page 1: “Pump shall comply with API 610 and API 682\.”/)).toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(within(note).getByText(/not held locally - not checked \(1\)/)).toBeInTheDocument();
    expect(within(note).getByText("API 682")).toBeInTheDocument();
  });

  it("names the missing standards even when nothing was selected", async () => {
    page({ panel: "standards", standardsState: { standards: [], missing: [{ identifier: "API 682", status: "MISSING_LOCALLY" }], error: null } });
    expect(screen.getByText("No standards were selected for this run.")).toBeInTheDocument();
    expect(within(screen.getByRole("note")).getByText("API 682")).toBeInTheDocument();
  });

  it("audit 2026-09-30: says the standards could not be loaded, not that none were selected", async () => {
    page({ panel: "standards", standardsState: { standards: null, missing: [], error: "the standards list failed" } });
    const alert = screen.getByText(/The standards for this run could not be loaded/);
    expect(alert).toHaveTextContent("the standards list failed");
    expect(screen.queryByText("No standards were selected for this run.")).toBeNull();
    expect(screen.queryByText(/Loading standards/)).toBeNull();
  });
});

describe("the run summary on the numbers page", () => {
  it("gives the four totals and the counts by kind, AI drafts not counted", async () => {
    page({ panel: "numbers", findings: [
      finding({ compliance_status: "COMPLIANT" }),
      finding({ compliance_status: "NON_COMPLIANT" }),
      finding({ compliance_status: "NON_COMPLIANT", origin: "datasheet_check" }),
      finding({ compliance_status: "NEEDS_ENGINEER_REVIEW" }),
      finding({ compliance_status: "MISSING_INFORMATION" }),
      finding({ compliance_status: "NOT_IN_DOCUMENT_SCOPE" }),
      finding({ compliance_status: null, origin: "ai_engineering_check" }),
      finding({ compliance_status: null, origin: "ai_engineering_check", confirmed_by: "u1" }),
      finding({ compliance_status: "NON_COMPLIANT", approval_status: "rejected" }),
    ] });
    const summary = within(screen.getByTestId("run-summary"));
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

describe("UX GROUP (2026-09-27): the finding detail", () => {
  afterEach(() => {
    delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
  });

  it("opens under the table when a finding is selected", async () => {
    page({ panel: "findings", findings: [
      finding({ id: "f1", compliance_status: "NON_COMPLIANT", requirement: "A requirement." }),
    ] });
    await userEvent.click(screen.getByText("A requirement."));
    expect(screen.getByRole("heading", { name: "Engineer actions" })).toBeInTheDocument();
  });
});
