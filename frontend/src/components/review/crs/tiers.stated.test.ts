// #1638: an engineer must never read a stated row as checked. Invented rows only.
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { cardTitle } from "../sheet/sheetCards";
import { countsOfServer, countTiers, EMPTY_FACTS, tierOf, tierOfGroup } from "./tiers";

function finding(extra: Partial<ReviewFinding>): ReviewFinding {
  return {
    id: "f", compliance_status: "COMPLIANT", origin: "datasheet_check", contractor_page: 1, ...extra,
  } as ReviewFinding;
}

const STATED = "Stated, not checked";

describe("a stated row on the screen", () => {
  it("is not Met", () => {
    expect(tierOf(finding({ stated_only: true }))).toEqual({ tier: "A", label: STATED, reason: null });
    expect(tierOf(finding({})).label).toBe("Met");
  });

  it("on an unread page still needs a person", () => {
    const facts = { ...EMPTY_FACTS, pagesNotRead: [1] };
    expect(tierOf(finding({ stated_only: true }), facts).tier).toBe("C");
  });

  it("is counted apart from met", () => {
    const counts = countTiers([tierOf(finding({ stated_only: true })), tierOf(finding({}))]);
    expect(counts.met).toBe(1);
    expect(counts.stated).toBe(1);
    expect(counts.notApplicable).toBe(0);
  });

  it("adds no count when there is none", () => {
    expect(countTiers([tierOf(finding({}))])).not.toHaveProperty("stated");
  });

  it("a group holding one is not Met", () => {
    const got = tierOfGroup([finding({ id: "a" }), finding({ id: "b", stated_only: true })], EMPTY_FACTS, null);
    expect(got.label).toBe(STATED);
  });

  it("reads the server's count", () => {
    const counts = countsOfServer({
      met: 1, not_applicable: 0, another_document: 0, comment: 0, needs_you: 0, removed: 0, total: 3, stated: 2,
    });
    expect(counts.stated).toBe(2);
  });

  it("a safety-tick card does not say it meets the standard", () => {
    const tick = finding({
      stated_only: true, show_for_engineer_tick: true, contractor_section: "Rated flow",
    } as Partial<ReviewFinding>);
    const title = cardTitle({ findings: [tick] } as Parameters<typeof cardTitle>[0]);
    expect(title).toContain("stated, not checked");
    expect(title).not.toContain("meets");
  });
});
