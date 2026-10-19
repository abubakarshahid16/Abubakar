/**
 * v2.1 W1: the table's own words are plain: the "Show" choices are
 * explained, and no message says "rows", "depth" or "clauses".
 * MUTATION PROOF: put back "No row to show at this depth." and the first
 * test fails; drop the explanation line and the second fails.
 */
import { render, screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewFinding, RunSummaryTierRow } from "../../../types/api";
import { CrsTable } from "./CrsTable";
import { buildCrsRows } from "./crsRows";
import { EMPTY_FACTS, serverTiersOf } from "./tiers";
import { useCrsDecisions } from "./useCrsDecisions";

function table(over: Partial<Parameters<typeof CrsTable>[0]> = {}) {
  const decisions = renderHook(() => useCrsDecisions()).result.current;
  return (
    <CrsTable
      rows={[]} allRows={[]} counts={{ met: 3, notApplicable: 1, anotherDocument: 0, comment: 0, needsYou: 0 }}
      depth="everything" onDepth={vi.fn()} showMet={false} onShowMet={vi.fn()} spot={new Set()} selectedKey={null}
      onSelect={vi.fn()} onOpenEvidence={vi.fn()} mode={null} onMode={vi.fn()} decisions={decisions}
      clausesNotApplicable={12} {...over}
    />
  );
}

describe("CrsTable words (v2.1 W1)", () => {
  it("an empty list and the not-applicable line use plain words", () => {
    render(table());
    const text = document.body.textContent ?? "";
    expect(text).toContain("Nothing to show with this choice.");
    expect(text).toContain("12 requirements in the standards were judged not to apply to this equipment");
    expect(text).not.toMatch(/\bdepth\b|\bclauses?\b|No row to show|counted on the run/);
  });

  it("explains each Show choice", () => {
    render(table());
    expect(screen.getByTestId("crs-depth-help")).toHaveTextContent(
      "Critical only: only what needs your judgement and clear failures. Standard: every comment for the contractor. Everything: also what met the standard or does not apply.");
  });
});

/** Order 139 part 2: each row shows its rank word - the file's Priority
 *  column - when the run summary sent one; the screen never ranks a row of
 *  its own. MUTATION PROOF: drop the label from `CrsRow` (or stop
 *  `serverTiersOf` carrying `crs_priority_label`) and the first test fails;
 *  show a made-up word when none was sent and the second fails. */
describe("CrsTable rank word (order 139 part 2)", () => {
  function finding(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
    return {
      id, compliance_status: "MISSING_INFORMATION", matched_phrase: `Field ${id}`, finding: `${id} found`,
      required_action: `Contractor to provide ${id}.`, contractor_page: 1, approval_status: "pending",
      standard_document_id: "std-1", standard_clause: "4.1", ...over,
    } as ReviewFinding;
  }
  function summaryRow(id: string, label: RunSummaryTierRow["crs_priority_label"]): RunSummaryTierRow {
    return { finding_id: id, tier: "B", label: "Comment", reason: null, crs_priority: label ? 2 : null, crs_priority_label: label };
  }

  it("shows the server's rank word on the row", () => {
    const server = serverTiersOf([summaryRow("a", "Missing value")]);
    const rows = buildCrsRows([finding("a")], EMPTY_FACTS, new Map(), server);
    render(table({ rows, allRows: rows }));
    expect(screen.getByTestId("row-priority")).toHaveTextContent("Missing value");
  });

  it("shows no rank word when the server sent none", () => {
    const server = serverTiersOf([summaryRow("a", null)]);
    const rows = buildCrsRows([finding("a")], EMPTY_FACTS, new Map(), server);
    render(table({ rows, allRows: rows }));
    expect(screen.queryByTestId("row-priority")).toBeNull();
  });
});
