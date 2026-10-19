/**
 * v2.1 landing rules (L3, L4, L5, L9). Made-up sample data only.
 */
import { describe, expect, it } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import { inboxStateOf } from "../../inbox/inboxState";
import { allRunsOf, countsLine, landingRowsOf, matchesName, rowChip } from "./landingRows";

function run(over: Partial<ReviewRunSummary>): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T08:00:00Z", completed_at: null,
    standards_in_scope: 1, findings_total: 0, by_status: {}, recommended_code: null, recommended_reason: null, completeness: null,
    ...over,
  } as ReviewRunSummary;
}
const doc = (id: string, filename: string, uploaded_at: string) => ({ id, filename, uploaded_at, indexed_at: null }) as DocumentRecord;

describe("landingRowsOf (L4)", () => {
  it("sorts by newest activity: a signature or final code counts, not only when the review started", () => {
    const rows = landingRowsOf(
      [doc("doc-3", "Motor sheet.pdf", "2026-09-02T08:00:00Z"), doc("doc-2", "Valve list.pdf", "2026-10-04T08:00:00Z"),
        doc("doc-1", "Pump datasheet rev B.pdf", "2026-09-01T08:00:00Z")],
      [
        run({ review_run_id: "run-1", submittal_document_id: "doc-1", created_at: "2026-10-01T08:00:00Z", crs_issued_at: "2026-10-09T08:00:00Z" }),
        run({ review_run_id: "run-3", submittal_document_id: "doc-3", created_at: "2026-10-03T08:00:00Z" }),
        run({ review_run_id: "run-9", submittal_document_id: "doc-gone", submittal_filename: "Old sheet.pdf", created_at: null }),
      ],
    );
    expect(rows.map((r) => r.filename)).toEqual(["Pump datasheet rev B.pdf", "Valve list.pdf", "Motor sheet.pdf", "Old sheet.pdf"]);
    expect(rows[0].activityAt).toBe("2026-10-09T08:00:00Z");
    // A run whose document record is missing is still listed (under the run's own name), dated last.
    expect(rows[3].activityAt).toBeNull();
  });

  it("the search matches any part of the file name, in any case", () => {
    expect(matchesName("Pump datasheet rev B.pdf", "DATASHEET")).toBe(true);
    expect(matchesName("Pump datasheet rev B.pdf", "  ")).toBe(true);
    expect(matchesName("Valve list.pdf", "pump")).toBe(false);
  });
});

describe("rowChip (L3, L9)", () => {
  it("says each state in plain words, with counts only when known (never 0 for unknown)", () => {
    expect(rowChip(inboxStateOf(undefined), null).text).toBe("Not reviewed");
    expect(rowChip(inboxStateOf(run({ status: "completed" })), null).text).toBe("Ready");
    expect(rowChip(inboxStateOf(run({ status: "completed" })), { findings: 12, needs_you: 3 }).text).toBe("3 need you");
    expect(rowChip(inboxStateOf(run({ status: "completed" })), { findings: 12, needs_you: 0 }).text).toBe("Ready to sign");
    expect(rowChip(inboxStateOf(run({ crs_issued_at: "2026-10-09T08:00:00Z" })), null).text).toBe("Signed");
    expect(rowChip(inboxStateOf(run({ status: "queued" })), null).text).toBe("Waiting to start");
    const running = run({
      status: "running",
      job: { id: "job-1", state: "running", progress_done: 1, progress_total: 4, progress_label: "Reading the standards", cancel_requested: false },
    });
    expect(rowChip(inboxStateOf(running), null).text).toBe("Running (step 2 of 4)");
    expect(rowChip(inboxStateOf(run({ status: "running" })), null).text).toBe("Running");
    expect(rowChip(inboxStateOf(run({ status: "failed", failure_reason: "The file could not be opened." })), null))
      .toEqual({ text: "Failed: The file could not be opened.", tone: "failed" });
    expect(rowChip(inboxStateOf(run({ status: "failed" })), null).text).toBe("Failed: no reason was recorded");
  });

  it("the counts line names findings, and is empty when unknown", () => {
    const ready = inboxStateOf(run({ status: "completed" }));
    expect(countsLine(ready, { findings: 1234, needs_you: 3 })).toBe("1,234 findings to decide");
    expect(countsLine(ready, null)).toBe("");
  });
});

describe("allRunsOf (L5)", () => {
  it("lists every run once, newest started first, named from the document list when it can", () => {
    const items = allRunsOf(
      [doc("doc-1", "Pump datasheet rev B.pdf", "2026-09-01T08:00:00Z")],
      [
        run({ review_run_id: "run-1", created_at: "2026-10-01T08:00:00Z" }),
        run({ review_run_id: "run-2", created_at: "2026-10-05T08:00:00Z" }),
        run({ review_run_id: "run-9", submittal_document_id: "doc-2", submittal_filename: "Valve list.pdf", created_at: "2026-10-03T08:00:00Z" }),
      ],
    );
    expect(items.map((i) => i.run.review_run_id)).toEqual(["run-2", "run-9", "run-1"]);
    expect(items.map((i) => i.filename)).toEqual(["Pump datasheet rev B.pdf", "Valve list.pdf", "Pump datasheet rev B.pdf"]);
  });
});
