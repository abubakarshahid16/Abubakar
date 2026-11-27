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
    const counted = queriesRow({ awaiting_review: 30, approved: 0, send_pending: 0, resolved: 2, duplicate: 1, total: 33, overdue: 4, open_with_due_date: 6 })!;
    expect([counted.inCount, counted.waiting, counted.late, counted.done, counted.lateStatus]).toEqual([32, 30, 4, 2, "counted"]);
    expect(counted.lateNote).toBe("past the due date, of 6 open with a due date");
    const none = queriesRow({ awaiting_review: 33, approved: 0, send_pending: 0, total: 33, overdue: 0, open_with_due_date: 0 })!;
    expect([none.late, none.lateStatus]).toEqual([null, "no_due_dates"]);
    const half = queriesRow({ awaiting_review: 3, approved: 0, send_pending: 0, total: 3, overdue: 1 })!; // the boundary missing: no late number
    expect([half.late, half.lateStatus]).toEqual([null, "unknown"]);
    const noTotal = queriesRow({ awaiting_review: 3, approved: 0, send_pending: 0, duplicate: 1 })!; // never '-1 in'
    expect([noTotal.inCount, noTotal.waiting]).toEqual([null, null]);
    expect(queriesRow("off")).toBeNull();
    // waiting = waiting for a PERSON (F's walk, 27 Nov 2026): the queries the AI is still working on are not counted
    const live = queriesRow({ drafting: 13, awaiting_review: 21, approved: 0, send_pending: 0, total: 34, overdue: 0, open_with_due_date: 0 })!;
    expect([live.inCount, live.waiting]).toEqual([34, 21]);
    // an approved reply not sent yet still waits for a person (H's read of #1998)
    expect(queriesRow({ awaiting_review: 2, approved: 1, send_pending: 1, total: 5, overdue: 0, open_with_due_date: 0 })!.waiting).toBe(4);
  });

  it("deliverables: done = approved; superseded is neither; late = past the due date (not due today), over the open ones with a date", () => {
    const items = [
      { status: "approved", due_date: "2026-01-01" }, { status: "superseded", due_date: null },
      { status: "submitted", due_date: "2026-11-01" }, { status: "planned", due_date: null },
    ] as Deliverable[];
    const row = deliverablesRow(items, [{ days_overdue: 3 }, { days_overdue: 0 }]);
    expect([row.inCount, row.waiting, row.late, row.done, row.lateStatus]).toEqual([4, 2, 1, 1, "counted"]);
    expect(row.lateNote).toBe("past the due date, of 1 open with a due date");
    const unreadable = deliverablesRow([{ status: "planned", due_date: "not-a-date" }] as Deliverable[], []);
    expect(unreadable.lateStatus).toBe("no_due_dates"); // a date the server cannot read can never be late: not in the boundary
    const undated = deliverablesRow([{ status: "planned", due_date: null }] as Deliverable[], []);
    expect([undated.late, undated.lateStatus]).toEqual([null, "no_due_dates"]);
  });

  it("F's walk: a running review is in progress, not waiting for you; the in-progress count is unknown when waiting is", () => {
    const row = reviewsRow({ ...review, reviews_awaiting_decision: 4, reviews_running: 2 } as ReviewDashboard);
    expect([row.inCount, row.waiting, row.working, row.done]).toEqual([7, 4, 2, 1]);
    const q = queriesRow({ awaiting_review: 21, approved: 0, send_pending: 0, drafting: 13, total: 34, overdue: 0, open_with_due_date: 0 })!;
    expect([q.inCount, q.waiting, q.working]).toEqual([34, 21, 13]);
    const missing = queriesRow({ awaiting_review: 21, drafting: 13, total: 34, overdue: 0, open_with_due_date: 0 })!; // a count missing
    expect([missing.waiting, missing.working]).toEqual([null, null]); // unknown, never 0
  });

  it("the line never says 'nothing late' when nothing can be late", () => {
    const rows = [reviewsRow(review), queriesRow({ awaiting_review: 33, approved: 0, send_pending: 0, total: 33, overdue: 0, open_with_due_date: 0 })!, deliverablesRow([{ status: "planned", due_date: null }] as Deliverable[], [])];
    expect(glanceLine(rows)).toBe("39 waiting, nothing has a due date.");
    const some = [reviewsRow(review), queriesRow({ awaiting_review: 33, approved: 0, send_pending: 0, total: 33, overdue: 2, open_with_due_date: 4 })!];
    expect(glanceLine(some)).toBe("38 waiting, 2 late.");
    const clean = [queriesRow({ awaiting_review: 3, approved: 0, send_pending: 0, total: 3, overdue: 0, open_with_due_date: 2 })!];
    expect(glanceLine(clean)).toBe("3 waiting, none late."); // counted over 2 with a due date: a real 0
  });

  it("a figure that could not be loaded is unknown, never 0", () => {
    expect([reviewsRow(null).inCount, queriesRow(null)!.done, deliverablesRow(null, null).waiting]).toEqual([null, null, null]);
    expect(glanceLine([reviewsRow(null), queriesRow({ awaiting_review: 3, approved: 0, send_pending: 0, total: 3, overdue: 0, open_with_due_date: 0 })!])).toBe("3 waiting (some figures could not be loaded), late unknown.");
  });
});
