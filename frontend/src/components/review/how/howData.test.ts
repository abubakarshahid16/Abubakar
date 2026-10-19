/** Order 95 piece 5: the pure helpers behind "How this was reviewed". */
import { describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { AI_STEP_DEFAULTS, NOT_RECORDED, clauseFacts, defaultLine, durationLabel, durationSeconds, pageFacts, pagesMeaning, uncheckedShare } from "./howData";

const base = { review_run_id: "r", submittal_document_id: "d", equipment_tags: [], status: "completed",
  standards_in_scope: 0, findings_total: 0, by_status: {}, recommended_code: null, recommended_reason: null,
  completeness: null } as unknown as ReviewRunSummary;

describe("uncheckedShare", () => {
  it("is the two stored counts, never the stored share", () => {
    const run = { ...base, requirement_split: { checked: 3, applies_not_checked: 1, does_not_apply: 0, total: 4,
      applies_not_checked_reasons: [], does_not_apply_reasons: [], repeats_ignored: null, unchecked_share: 0.9 } } as ReviewRunSummary;
    expect(uncheckedShare(run)).toEqual({ percent: 25, numerator: 1, denominator: 4 });
  });
  it("is null with no split, and null when nothing applies (no percentage without a denominator)", () => {
    expect(uncheckedShare(base)).toBeNull();
    const none = { ...base, requirement_split: { checked: 0, applies_not_checked: 0, does_not_apply: 9, total: 9,
      applies_not_checked_reasons: [], does_not_apply_reasons: [], repeats_ignored: null, unchecked_share: null } } as ReviewRunSummary;
    expect(uncheckedShare(none)).toBeNull();
  });
});

describe("pageFacts and clauseFacts", () => {
  it("leave every value null on a run with no record, and name the source anyway", () => {
    const p = pageFacts(base);
    expect(p.total.value).toBeNull();
    expect(p.total.source).toBe("page_coverage.pages_total");
    expect(p.timedOut.value).toBeNull();
    expect(p.withoutOcr.value).toBeNull();
    const c = clauseFacts(base);
    expect(c.applied.value).toBeNull();
    expect(c.applied.source).toContain("checked + ");
  });
  it("sums only stored fields: OCR pending + failed, checked + applies_not_checked", () => {
    const run = { ...base,
      page_coverage: { pages_total: 4, fact_pages: [1], pages_not_read_into_fields: [2, 3, 4], not_read_reasons: {},
                       ocr: { pending: 2, failed: 1, done: 1 } },
      requirement_split: { checked: 5, applies_not_checked: 2, does_not_apply: 1, total: 8,
        applies_not_checked_reasons: [], does_not_apply_reasons: [], repeats_ignored: 0, unchecked_share: null,
        reader: { engine: "off", pages: 4 } } } as ReviewRunSummary;
    const p = pageFacts(run);
    expect(p.withoutOcr.value).toBe(3);
    expect(p.aiOff).toBe(true);
    expect(p.readByAi.value).toBeNull();
    expect(p.timedOut.value).toBeNull();
    expect(clauseFacts(run).applied.value).toBe(7);
  });
});

describe("durations and defaults", () => {
  it("formats seconds and refuses a backwards or missing interval", () => {
    expect(durationSeconds("2026-10-17T08:00:00Z", "2026-10-17T08:00:40Z")).toBe(40);
    expect(durationSeconds("2026-10-17T08:00:40Z", "2026-10-17T08:00:00Z")).toBeNull();
    expect(durationSeconds(null, "2026-10-17T08:00:00Z")).toBeNull();
    expect(durationLabel(40)).toBe("40 s");
    expect(durationLabel(754)).toBe("12 min 34 s");
    expect(durationLabel(3900)).toBe("1 h 5 min");
  });
  it("names rule 1 on every step that is on by default, and says off for the one that is not", () => {
    for (const [key, d] of Object.entries(AI_STEP_DEFAULTS)) {
      expect(defaultLine(key)).toContain(d.setting);
      expect(defaultLine(key)).toMatch(d.onByDefault ? /^On by default .*rule 1/ : /^Off by default/);
    }
    expect(AI_STEP_DEFAULTS.applicability.onByDefault).toBe(false);
  });
});

describe("pagesMeaning reads the stored reading record", () => {
  // Failing-first (review of #1113): the old line said "Every one of the 3
  // pages was read into fields" for both of these runs.
  it("an incomplete reading names the incomplete pages and each stored reason", () => {
    const run = { ...base, page_coverage: {
      pages_total: 3, fact_pages: [1, 2, 3], pages_not_read_into_fields: [], not_read_reasons: {},
      pages_ai_not_read: [2], ai_not_read_reasons: { "2": "the local reader timed out on this page" },
      reading: { status: "incomplete", pages_total: 3, incomplete_pages: [2, 3], reasons: {},
                 failed_pages: { "3": "a reader failed on this page (geometry)" } },
    } } as unknown as ReviewRunSummary;
    const line = pagesMeaning(run);
    expect(line).not.toMatch(/every/i);
    expect(line).toContain("incomplete");
    expect(line).toContain("pages 2-3");
    expect(line).toContain("page 2: the local reader timed out on this page");
    expect(line).toContain("page 3: a reader failed on this page (geometry)");
    expect(pageFacts(run).aiNotRead.value).toEqual([2]);
    expect(pageFacts(run).aiNotRead.source).toBe("page_coverage.pages_ai_not_read");
  });
  it("a run with no pages_not_read_into_fields says not recorded, never zero or every page", () => {
    const run = { ...base, page_coverage: { pages_total: 3, fact_pages: [1, 2, 3], not_read_reasons: {} } } as unknown as ReviewRunSummary;
    expect(pageFacts(run).notRead.value).toBeNull();
    const line = pagesMeaning(run);
    expect(line).not.toMatch(/every/i);
    expect(line).toContain("not recorded");
  });
  it("claims all pages only when the run stored the reading as complete", () => {
    const run = { ...base, page_coverage: {
      pages_total: 2, fact_pages: [1, 2], pages_not_read_into_fields: [], not_read_reasons: {}, pages_ai_not_read: [],
      reading: { status: "complete", pages_total: 2, incomplete_pages: [], reasons: {} },
    } } as unknown as ReviewRunSummary;
    expect(pagesMeaning(run)).toContain("stored the reading as complete for all 2 pages");
  });
});

describe("OCR counts", () => {
  it("reads a missing OCR key as 0 only when the ledger accounted for the pages", () => {
    const withLedger = { ...base, page_coverage: { pages_total: 2, fact_pages: [1, 2], pages_not_read_into_fields: [],
      not_read_reasons: {}, ocr: { not_required: 2 } } } as unknown as ReviewRunSummary;
    expect(pageFacts(withLedger).withoutOcr.value).toBe(0);
    expect(pageFacts(withLedger).ocrDone.value).toBe(0);
    const noLedger = { ...base, page_coverage: { pages_total: null, fact_pages: [], pages_not_read_into_fields: [],
      not_read_reasons: {}, ocr: {} } } as unknown as ReviewRunSummary;
    expect(pageFacts(noLedger).withoutOcr.value).toBeNull();
    expect(pageFacts(noLedger).ocrDone.value).toBeNull();
    expect(NOT_RECORDED).toBe("not recorded on this review");
  });
});
