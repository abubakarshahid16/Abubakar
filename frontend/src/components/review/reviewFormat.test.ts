import { readFileSync } from "node:fs";
import { resolve } from "node:path";
/**
 * The honesty rules, as assertions.
 *
 * Each of these is CLAUDE.md rule 4 restated for a screen: null renders as
 * nothing rather than 0, a count never appears without its denominator,
 * confidence never reads "high", a nominal denominator says so, and
 * MISSING_INFORMATION is never given the colour or the wording of a failure.
 */
import { describe, expect, it } from "vitest";

import {
  STATUS_ORDER, groupFindingsByTopic, groupRunsByDocument, kindCounts, kindLabel,
  completenessLine, estimateDetail, pagesReadLine, standardsChangeLine, confidenceLabel,
  findingLabel, matchMethodLabel, orNothing, pageCoverageLine, pageList, statusLabel,
  statusRank, statusTone, summaryTotals, withDenominator,
} from "./reviewFormat";
import type { ReviewRunSummary } from "../../types/api";

describe("attention order", () => {
  it("puts what asserts a breach first and what asserts nothing last", () => {
    expect(STATUS_ORDER[0]).toBe("NON_COMPLIANT");
    // B9: a requirement this submittal type cannot answer asks nothing of
    // anyone on it, so it follows even the contractor's missing fields.
    expect(STATUS_ORDER[STATUS_ORDER.length - 2]).toBe("MISSING_INFORMATION");
    expect(STATUS_ORDER[STATUS_ORDER.length - 1]).toBe("NOT_IN_DOCUMENT_SCOPE");
  });

  it("sorts a real run's statuses so the two actionable rows lead", () => {
    const rows = ["MISSING_INFORMATION", "COMPLIANT", "NEEDS_ENGINEER_REVIEW", "NON_COMPLIANT"];
    expect([...rows].sort((a, b) => statusRank(a) - statusRank(b))).toEqual([
      "NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW", "COMPLIANT", "MISSING_INFORMATION",
    ]);
  });

  it("puts an unknown status last rather than first", () => {
    expect(statusRank("SOMETHING_NEW")).toBeGreaterThan(statusRank("MISSING_INFORMATION"));
  });
});

describe("B9: needing another document is neither a failure nor an omission", () => {
  it("carries the owner's approved wording, and never says 'missing'", () => {
    const label = statusLabel("NOT_IN_DOCUMENT_SCOPE");
    expect(label).toBe(
      "Requires another document - not answerable from this submittal type");
    for (const word of ["missing", "fail", "non-compliant", "no evidence"]) {
      expect(label.toLowerCase()).not.toContain(word);
    }
  });

  it("is never red, and never reads like missing information", () => {
    expect(statusTone("NOT_IN_DOCUMENT_SCOPE")).not.toContain("rose");
    expect(statusTone("NOT_IN_DOCUMENT_SCOPE")).not.toBe(statusTone("MISSING_INFORMATION"));
  });
});

describe("missing information is not a failure", () => {
  it("is not worded as one", () => {
    expect(statusLabel("MISSING_INFORMATION")).toBe("No value found in the fields read");
    expect(statusLabel("MISSING_INFORMATION").toLowerCase()).not.toContain("fail");
    expect(statusLabel("MISSING_INFORMATION").toLowerCase()).not.toContain("non-compliant");
  });

  it("is not coloured as one", () => {
    // The rose palette is the breach colour. A reader scanning a table reads
    // the colour long before the word, and 1,578 rose rows would read as
    // 1,578 accusations against a vendor who was never asked.
    // The breach colour is the "fail" pill token (2g; was Tailwind rose).
    expect(statusTone("MISSING_INFORMATION")).not.toContain("pill-fail");
    expect(statusTone("NON_COMPLIANT")).toContain("pill-fail");
  });
});

describe("2g: status pills are readable in both themes (WCAG AA)", () => {
  const css = readFileSync(resolve(__dirname, "../../index.css"), "utf8");
  function block(selector: string): string {
    const start = css.indexOf(selector);
    return css.slice(start, css.indexOf("}", start));
  }
  function token(text: string, name: string): string {
    const m = new RegExp(`--color-${name}:\\s*(#[0-9A-Fa-f]{6})`).exec(text);
    if (!m) throw new Error(`no ${name}`);
    return m[1];
  }
  function luminance(hex: string): number {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function ratio(a: string, b: string): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  }
  const themes = { default: block("@theme {"), dark: block(':root[data-theme="dark"] {'),
                   light: block(':root[data-theme="light"] {') };

  it.each(Object.entries(themes))("%s theme: every status pill's text is at least 4.5:1 on its fill", (_n, text) => {
    for (const kind of ["review", "fail", "pass", "cond"]) {
      expect(ratio(token(text, `pill-${kind}-fg`), token(text, `pill-${kind}-bg`)),
             `${kind}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the coloured statuses use the pill tokens, not a fixed pale palette", () => {
    for (const status of ["NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW", "CONDITIONAL", "COMPLIANT"]) {
      expect(statusTone(status)).toMatch(/text-pill-\w+-fg/);
      expect(statusTone(status)).not.toMatch(/-200\b/);
    }
  });
});

describe("null renders as nothing, never zero", () => {
  it.each([null, undefined])("%s becomes an empty string", (value) => {
    expect(orNothing(value)).toBe("");
  });

  it("keeps a real zero, which is a different statement", () => {
    expect(orNothing(0)).toBe("0");
  });
});

describe("counts carry their denominator", () => {
  it("states the population and the share", () => {
    expect(withDenominator(2, 1580)).toBe("2 of 1,580 (0.1%)");
  });

  it("does not print a misleading 0.0% for a tiny share", () => {
    expect(withDenominator(1, 100000)).toContain("<0.1%");
  });
});

describe("confidence never reads high", () => {
  it.each(["low", "medium"])("passes %s through", (value) => {
    expect(confidenceLabel(value)).toBe(value);
  });

  it("refuses high even if the API ever sent it", () => {
    expect(confidenceLabel("high")).toBe("not recorded");
  });

  it("renders nothing when there is none", () => {
    expect(confidenceLabel(null)).toBe("");
  });
});

describe("a guess and a rule do not read alike", () => {
  it("names the model tier as a pairing, not a measurement", () => {
    expect(matchMethodLabel("model")).toBe("paired by model");
    expect(matchMethodLabel("containment")).toBe("matched by rule");
  });
});

describe("a nominal denominator says it is nominal - under Details only (2g)", () => {
  const run = {
    completeness: { fields_read: 48, fields_estimated: 385, pages: 11 },
  } as ReviewRunSummary;

  it("the line states only what was counted, in plain words", () => {
    expect(completenessLine(run)).toBe("Checked 48 datasheet fields.");
  });

  it("the detail says NOMINAL and says it is not a count of this document", () => {
    const line = estimateDetail(run);
    expect(line).toContain("48");
    expect(line).toContain("385");
    expect(line).toContain("NOMINAL");
    expect(line).toContain("not a count of this document");
  });

  it("renders nothing when the run recorded no completeness", () => {
    expect(completenessLine({ completeness: null } as ReviewRunSummary)).toBe("");
  });
});

describe("B3: a finding on an unread page says so in plain words", () => {
  it("labels an UNREAD_PAGES finding 'Pages not yet readable - needs engineer review'", () => {
    expect(findingLabel({
      compliance_status: "NEEDS_ENGINEER_REVIEW",
      ai_rationale: "UNREAD_PAGES: no value for this requirement was found ...",
    })).toBe("Pages not yet readable - needs engineer review");
  });

  it("labels a PAGE_READER_ONLY finding as the page reader's miss, for an engineer (entry 68)", () => {
    expect(findingLabel({
      compliance_status: "NEEDS_ENGINEER_REVIEW",
      ai_rationale: "PAGE_READER_ONLY: value not found by the page reader - engineer to check the page 3.",
    })).toBe("Value not found by the page reader - engineer to check the page");
  });

  it("labels an AI engineering check item as a draft, not a verdict (order 2d)", () => {
    expect(findingLabel({ compliance_status: null, ai_rationale: null,
                          origin: "ai_engineering_check" }))
      .toBe("AI engineering check - not from the standard text - engineer to confirm");
  });

  it("leaves every other finding reading as its status does", () => {
    expect(findingLabel({ compliance_status: "NEEDS_ENGINEER_REVIEW",
                          ai_rationale: "UNIT_MISMATCH: ..." })).toBe("Needs engineer review");
    expect(findingLabel({ compliance_status: "MISSING_INFORMATION", ai_rationale: null }))
      .toBe("No value found in the fields read");
  });
});

describe("B3: which pages were read into fields", () => {
  const coverage = (fact: number[], unread: number[], total: number | null = 11) =>
    ({ page_coverage: {
      pages_total: total, fact_pages: fact, pages_not_read_into_fields: unread,
      not_read_reasons: {},
    } } as unknown as ReviewRunSummary);

  it("states the denominator and names the unread pages", () => {
    const line = pageCoverageLine(coverage([4, 5], [1, 2, 3, 6, 7, 8, 9, 10, 11]));
    expect(line).toContain("2 of 11 pages");
    expect(line).toContain("pages 4-5");
    expect(line).toContain("pages 1-3, 6-11 not read into fields");
    expect(line).toContain("may still be there");
  });

  it("does not warn when every page was read", () => {
    const line = pageCoverageLine(coverage([1, 2], [], 2));
    expect(line).toBe("Fields read from 2 of 2 pages (pages 1-2).");
  });

  it("never reads 'no page accounted for' as 'every page read'", () => {
    expect(pageCoverageLine(coverage([], [], null))).toContain("no value can be called missing");
  });

  it("renders nothing for a run made before the ledger existed", () => {
    expect(pageCoverageLine({ page_coverage: null } as ReviewRunSummary)).toBe("");
  });

  it("compresses page runs the way the findings do", () => {
    expect(pageList([7, 1, 2, 3])).toBe("1-3, 7");
    expect(pageList([5])).toBe("5");
  });
});

describe("2e: why the in-scope count moved", () => {
  const base = { completeness: null } as unknown as ReviewRunSummary;
  it("names what was added and removed since the previous run", () => {
    expect(standardsChangeLine({ ...base, standards_change: {
      previous_run_id: "r0", added: ["STD-C.pdf"], removed: ["STD-A.pdf", "STD-B.pdf"] } }))
      .toBe("Since the previous run: 2 standards removed (STD-A.pdf, STD-B.pdf); 1 standard added (STD-C.pdf).");
  });
  it("says nothing changed, and nothing at all for a first run", () => {
    expect(standardsChangeLine({ ...base, standards_change: { previous_run_id: "r0", added: [], removed: [] } }))
      .toBe("Same standards in scope as the previous run.");
    expect(standardsChangeLine({ ...base, standards_change: null })).toBe("");
  });
});

describe("2c: a datasheet check says what kind of comment it is", () => {
  it("labels the kinds, and a comparison finding carries none", () => {
    expect(kindLabel({ origin: "datasheet_check" })).toBe("Datasheet check");
    expect(kindLabel({ origin: "ai_engineering_check" })).toBe("AI engineering check");
    expect(kindLabel({ origin: null })).toBe("");
  });
});

describe("section 3: the run's four totals and counts by kind", () => {
  it("maps each status to its total, and MISSING_INFORMATION is never a meet", () => {
    const totals = summaryTotals([
      { compliance_status: "COMPLIANT" },
      { compliance_status: "NON_COMPLIANT" },
      { compliance_status: "NEEDS_ENGINEER_REVIEW" },
      { compliance_status: "CONDITIONAL" },
      { compliance_status: "NOT_APPLICABLE" },
      { compliance_status: "MISSING_INFORMATION" },
      { compliance_status: "NOT_IN_DOCUMENT_SCOPE" },
    ]);
    expect(totals).toEqual({
      meets: 1, doesNotMeet: 1, needsDecision: 2, couldNotCheck: 2, notApplicable: 1, counted: 7,
    });
  });

  it("never counts an AI engineering check draft, a chat comment, or a rejected finding", () => {
    const totals = summaryTotals([
      { compliance_status: null, origin: "ai_engineering_check" },
      { compliance_status: "NON_COMPLIANT", origin: "chat" },
      { compliance_status: "NON_COMPLIANT", approval_status: "rejected" },
      { compliance_status: "COMPLIANT" },
    ]);
    expect(totals).toEqual({
      meets: 1, doesNotMeet: 0, needsDecision: 0, couldNotCheck: 0, notApplicable: 0, counted: 1,
    });
  });

  it("counts comments by kind, splitting AI engineering check by confirmation", () => {
    const counts = kindCounts([
      { origin: null },
      { origin: "datasheet_check" },
      { origin: "ai_engineering_check", confirmed_by: null },
      { origin: "ai_engineering_check", confirmed_by: "u1" },
      { origin: "chat" },
      { origin: "datasheet_check", approval_status: "rejected" },
    ]);
    expect(counts).toEqual({
      a: 1, b: 1, cConfirmed: 1, cUnconfirmed: 1, dConfirmed: 0, dUnconfirmed: 0,
    });
  });

  it("counts a public web standards check as its own kind D, split by confirmation", () => {
    const counts = kindCounts([
      { origin: "web_standard_check", confirmed_by: null },
      { origin: "web_standard_check", confirmed_by: "u1" },
      { origin: "web_standard_check", confirmed_by: "u1", approval_status: "rejected" },
    ]);
    expect(counts).toEqual({
      a: 0, b: 0, cConfirmed: 0, cUnconfirmed: 0, dConfirmed: 1, dUnconfirmed: 1,
    });
  });
});

describe("section 3: runs grouped per document, latest first", () => {
  it("groups by submittal, sorts within a group and across groups by recency", () => {
    const groups = groupRunsByDocument([
      { review_run_id: "r1", submittal_document_id: "doc-a", created_at: "2026-09-20T00:00:00Z" },
      { review_run_id: "r2", submittal_document_id: "doc-a", created_at: "2026-09-22T00:00:00Z" },
      { review_run_id: "r3", submittal_document_id: "doc-b", created_at: "2026-09-21T00:00:00Z" },
    ]);
    expect(groups.map((g) => g.documentId)).toEqual(["doc-a", "doc-b"]);
    expect(groups[0].latest.review_run_id).toBe("r2");
    expect(groups[0].earlier.map((r) => r.review_run_id)).toEqual(["r1"]);
    expect(groups[1].earlier).toEqual([]);
  });
});

describe("section 3: the readiness strip's page line", () => {
  it("says nothing when the page count is unknown, and states the denominator otherwise", () => {
    expect(pagesReadLine({ pages_total: null, pages_read: 0 })).toBe("");
    expect(pagesReadLine({ pages_total: 5, pages_read: 3 })).toBe("Pages read: 3 of 5");
  });
});

describe("section 3: comments grouped by topic", () => {
  it("groups by the matched field, falls back to equipment tag then Other, sorted with Other last", () => {
    const groups = groupFindingsByTopic([
      { matched_phrase: "Design pressure" },
      { matched_phrase: "Design pressure" },
      { matched_phrase: null, equipment_tag: "V-101" },
      { matched_phrase: null, equipment_tag: null },
    ]);
    expect(groups.map((g) => g.topic)).toEqual(["Design pressure", "V-101", "Other"]);
    expect(groups[0].findings).toHaveLength(2);
  });
});
