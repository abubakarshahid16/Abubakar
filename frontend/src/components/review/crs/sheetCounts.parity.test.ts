/**
 * Order 152.2: the shared case table, screen side.
 *
 * `contracts/fixtures/sheet_count_cases.json` is the ONE list of sheet-count
 * cases the server (`backend/tests/test_1520_sheet_counts.py`) and the screen
 * must both pass. The server's `review_counts.sheet_counts` and the screen's
 * own count of its rows (`buildCrsRows` + `rowCounts`) give the same numbers,
 * so switching the screen to read the server's counts changes none.
 *
 * Invented data only.
 */
import { describe, expect, it } from "vitest";

import cases from "../../../../../contracts/fixtures/sheet_count_cases.json";
import type { ReviewFinding, ReviewRunTierSummary } from "../../../types/api";
import { buildCrsRows, serverGroupsOf, sheetCountsOf } from "./crsRows";
import { EMPTY_FACTS } from "./tiers";

interface Case {
  name: string;
  findings: Record<string, unknown>[];
  groups: Record<string, { crs_group?: string; crs_note?: boolean }>;
  expected: Record<string, number>;
}

describe("the sheet's counts: server and screen agree on the shared cases", () => {
  for (const c of cases.cases as unknown as Case[]) {
    it(c.name, () => {
      const findings = c.findings.map((f) => ({ ...cases.base_finding, ...f }) as unknown as ReviewFinding);
      const summary = {
        review_run_id: "run-1",
        rows: Object.entries(c.groups).map(([finding_id, g], i) => ({
          finding_id, tier: "B", label: "Comment", crs_group: g.crs_group, crs_order: i, crs_note: g.crs_note,
        })),
        crs_grouping: true,
      } as unknown as ReviewRunTierSummary;
      const rows = buildCrsRows(findings, EMPTY_FACTS, new Map(), null, serverGroupsOf(summary));
      const e = c.expected;
      // The screen's own count of its rows, and the server's `sheet` (the
      // expected object is what the server sends) read through the switch.
      const withSheet = { ...summary, sheet: e } as unknown as ReviewRunTierSummary;
      for (const got of [sheetCountsOf(rows, null, false), sheetCountsOf(rows, withSheet, true)]) {
        expect(got.counts.comment + got.counts.needsYou).toBe(e.comments);
        expect(got.counts.needsYou).toBe(e.needs_you);
        expect(got.counts.met).toBe(e.met);
        expect(got.counts.notApplicable).toBe(e.not_applicable);
        expect(got.counts.anotherDocument).toBe(e.another_document);
        expect(got.findingsInComments).toBe(e.findings_in_comments);
      }
    });
  }
});
