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
  STATUS_ORDER, completenessLine, confidenceLabel, findingLabel, matchMethodLabel,
  orNothing, pageCoverageLine, pageList, statusLabel, statusRank, statusTone,
  withDenominator,
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
    expect(statusTone("MISSING_INFORMATION")).not.toContain("rose");
    expect(statusTone("NON_COMPLIANT")).toContain("rose");
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

describe("a nominal denominator says it is nominal", () => {
  const run = {
    completeness: { fields_read: 48, fields_estimated: 385, pages: 11 },
  } as ReviewRunSummary;

  it("says NOMINAL and says it is not a count of this document", () => {
    const line = completenessLine(run);
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
