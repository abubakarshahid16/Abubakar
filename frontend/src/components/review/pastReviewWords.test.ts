/**
 * Order 123 item 5: the words of one past review. A machine code alone is a
 * suggestion; findings are never called comments (A-1126); an unfinished run
 * says where it stopped and states no count.
 */
import { describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../types/api";
import { pastFindings, pastResult } from "./pastReviewWords";

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "a.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
    standards_in_scope: 1, findings_total: 3, by_status: {},
    ...over,
  } as ReviewRunSummary;
}

describe("pastResult", () => {
  it("puts the engineer's code first, with who decided it", () => {
    expect(pastResult(run({ engineer_final_code: "A", recommended_code: "C", decided_by_name: "Ali" })))
      .toBe("Code A, decided by Ali");
  });

  it("names no one when the decider's record is gone", () => {
    expect(pastResult(run({ engineer_final_code: "A", decided_by_name: null }))).toBe("Code A, decided");
  });

  it("shows the machine's code as a suggestion, never as the result", () => {
    expect(pastResult(run({ recommended_code: "B" }))).toBe("Suggested code B, not decided yet");
  });

  it("says why a run stopped instead of a code", () => {
    expect(pastResult(run({ status: "failed", failure_reason: "reader timed out", recommended_code: "B" })))
      .toBe("Failed: reader timed out");
  });
});

describe("pastFindings", () => {
  it("counts findings, singular and plural", () => {
    expect(pastFindings(run({ findings_total: 1 }))).toBe("1 finding recorded");
    expect(pastFindings(run({ findings_total: 4476 }))).toBe("4,476 findings recorded");
  });

  it("states no count for a run that did not finish", () => {
    expect(pastFindings(run({ status: "failed", findings_total: 9 }))).toBe("");
  });
});
