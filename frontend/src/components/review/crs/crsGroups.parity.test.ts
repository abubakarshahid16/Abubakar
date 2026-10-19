/**
 * Order 139 part 2, spec b: the shared case table, screen side.
 *
 * `contracts/fixtures/crs_group_cases.json` is the ONE list of grouping and
 * order cases the server (`backend/tests/test_139_crs_group_cases.py`) and the
 * screen must both pass. Here each case's expected rows become the run
 * summary's per-finding fields exactly as the server sends them (crs_group =
 * "row-<index>", crs_order = index, crs_action, crs_priority,
 * crs_priority_label; `review_notes` as crs_note), and `buildCrsRows` must show
 * one comment row per expected row, with exactly those findings, in that
 * order; no `not_on_sheet` finding in a grouped row; no Review-note finding
 * as a row at all. The screen does no grouping of its own: drop the server's
 * fields and the same findings fall apart into one row each.
 *
 * Invented data only.
 */
import { describe, expect, it } from "vitest";

import cases from "../../../../../contracts/fixtures/crs_group_cases.json";
import type { ReviewFinding, ReviewRunTierSummary, RunSummaryTierRow } from "../../../types/api";
import { buildCrsRows, serverGroupsOf, supportingClauseLines } from "./crsRows";
import { EMPTY_FACTS } from "./tiers";

interface ExpectedRow { finding_ids: string[]; priority: number; priority_label: string; action: string | null; clause_count: number }
interface Case { name: string; findings: Record<string, unknown>[]; expected_rows: ExpectedRow[]; not_on_sheet: string[]; review_notes?: string[] }

const names = new Map([["std-1", "STD-100.pdf"], ["std-2", "STD-200.pdf"]]);

function findingsOf(c: Case): ReviewFinding[] {
  return c.findings.map((f) => ({ ...cases.base_finding, ...f }) as unknown as ReviewFinding);
}

function summaryOf(c: Case): ReviewRunTierSummary {
  const rows: Partial<RunSummaryTierRow>[] = c.expected_rows.flatMap((r, i) => r.finding_ids.map((finding_id) => ({
    finding_id, tier: "B" as const, label: "Comment" as const, crs_group: `row-${i}`, crs_order: i, crs_action: r.action,
    crs_priority: r.priority, crs_priority_label: r.priority_label as RunSummaryTierRow["crs_priority_label"],
  })));
  for (const finding_id of c.review_notes ?? []) rows.push({ finding_id, tier: "C", label: "Needs you", crs_note: true });
  return { review_run_id: "run-1", rows, crs_grouping: true } as unknown as ReviewRunTierSummary;
}

describe("crs grouping parity with the server (contracts/fixtures/crs_group_cases.json)", () => {
  for (const c of cases.cases as Case[]) {
    it(c.name, () => {
      const findings = findingsOf(c);
      const rows = buildCrsRows(findings, EMPTY_FACTS, names, null, serverGroupsOf(summaryOf(c)));
      const grouped = rows.filter((r) => r.crsGroup);
      expect(grouped.map((r) => new Set(r.findings.map((f) => f.id)))).toEqual(c.expected_rows.map((r) => new Set(r.finding_ids)));
      expect(grouped.map((r) => r.commentNo)).toEqual(c.expected_rows.map((_r, i) => i + 1));
      expect(grouped.map((r) => r.clauseCount)).toEqual(c.expected_rows.map((r) => r.clause_count));
      expect(grouped.map((r) => r.priorityLabel)).toEqual(c.expected_rows.map((r) => r.priority_label));
      expect(grouped.map((r) => supportingClauseLines(r)[0] ?? null)).toEqual(
        c.expected_rows.map((r) => (r.action && r.clause_count >= 2 ? `Supporting clauses (${r.clause_count}):` : null)));
      const onGrouped = new Set(grouped.flatMap((r) => r.findings.map((f) => f.id)));
      for (const id of c.not_on_sheet) expect(onGrouped.has(id)).toBe(false);
      const onAny = new Set(rows.flatMap((r) => r.findings.map((f) => f.id)));
      for (const id of c.review_notes ?? []) expect(onAny.has(id)).toBe(false);
    });
  }

  it("the table really tests grouping: without the server's fields its merged rows fall apart", () => {
    const merged = (cases.cases as Case[]).filter((c) => c.expected_rows.some((r) => r.finding_ids.length > 1));
    expect(merged.length).toBeGreaterThanOrEqual(4);
    for (const c of merged) {
      const rows = buildCrsRows(findingsOf(c), EMPTY_FACTS, names);
      expect(rows.every((r) => r.findings.length === 1)).toBe(true);
    }
    expect((cases.cases as Case[]).some((c) => (c.review_notes ?? []).length > 0)).toBe(true);
  });
});
