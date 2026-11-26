/** At a glance (owner's E5, 26 Nov 2026): in, waiting, late, done, from figures the app already serves. Invented numbers. */
import { describe, expect, it } from "vitest";

import type { Deliverable, ReviewDashboard } from "../../types/api";
import { deliverablesRow, glanceLine, queriesRow, reviewsRow } from "./AtAGlance";

describe("at a glance", () => {
  const review = { submittals_total: 5, submittals_awaiting_review: 0, reviews_awaiting_decision: 5, reviews_running: 0, reviews_signed: 1 } as unknown as ReviewDashboard;

  it("document reviews: one unit (reviews) so in = waiting + done; 'late' is not tracked for a review", () => {
    const row = reviewsRow(review);
    expect([row.inCount, row.waiting, row.late, row.done, row.lateStatus]).toEqual([6, 5, null, 1, "not_tracked"]);
  });

  it("queries: late only with its boundary, and never a 0 over nothing (builder H's review)", () => {
    const counted = queriesRow({ drafting: 30, resolved: 2, duplicate: 1, total: 33, overdue: 4, open_with_due_date: 6 })!;
    expect([counted.inCount, counted.waiting, counted.late, counted.done, counted.lateStatus]).toEqual([32, 30, 4, 2, "counted"]);
    expect(counted.lateNote).toBe("past the due date, of 6 open with a due date");
    const none = queriesRow({ drafting: 33, total: 33, overdue: 0, open_with_due_date: 0 })!;
    expect([none.late, none.lateStatus]).toEqual([null, "no_due_dates"]);
    const half = queriesRow({ drafting: 3, total: 3, overdue: 1 })!; // the boundary missing: no late number
    expect([half.late, half.lateStatus]).toEqual([null, "unknown"]);
    const noTotal = queriesRow({ drafting: 3, duplicate: 1 })!; // never '-1 in'
    expect([noTotal.inCount, noTotal.waiting]).toEqual([null, null]);
    expect(queriesRow("off")).toBeNull();
  });

  it("deliverables: done = approved; superseded is neither; late = past the due date (not due today), over the open ones with a date", () => {
    const items = [
      { status: "approved", due_date: "2026-01-01" }, { status: "superseded", due_date: null },
      { status: "submitted", due_date: "2026-11-01" }, { status: "planned", due_date: null },
    ] as Deliverable[];
    const row = deliverablesRow(items, [{ days_overdue: 3 }, { days_overdue: 0 }]);
    expect([row.inCount, row.waiting, row.late, row.done, row.lateStatus]).toEqual([4, 2, 1, 1, "counted"]);
    expect(row.lateNote).toBe("past the due date, of 1 open with a due date");
    const undated = deliverablesRow([{ status: "planned", due_date: null }] as Deliverable[], []);
    expect([undated.late, undated.lateStatus]).toEqual([null, "no_due_dates"]);
  });

  it("the line never says 'nothing late' when nothing can be late", () => {
    const rows = [reviewsRow(review), queriesRow({ drafting: 33, total: 33, overdue: 0, open_with_due_date: 0 })!, deliverablesRow([{ status: "planned", due_date: null }] as Deliverable[], [])];
    expect(glanceLine(rows)).toBe("Waiting: 5 document reviews, 33 queries and CFCs, 1 deliverable. Late: not counted for queries and CFCs or deliverables: none has a due date.");
    const some = [reviewsRow(review), queriesRow({ drafting: 33, total: 33, overdue: 2, open_with_due_date: 4 })!];
    expect(glanceLine(some)).toBe("Waiting: 5 document reviews, 33 queries and CFCs. Late: 2 queries and CFCs.");
  });

  it("a figure that could not be loaded is unknown, never 0", () => {
    expect([reviewsRow(null).inCount, queriesRow(null)!.done, deliverablesRow(null, null).waiting]).toEqual([null, null, null]);
    expect(glanceLine([reviewsRow(null)])).toBe("Waiting: document reviews: unknown. Late: unknown for document reviews.");
  });
});
