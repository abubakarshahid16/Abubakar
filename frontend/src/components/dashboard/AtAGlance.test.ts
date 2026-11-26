/** At a glance (owner's E5, 26 Nov 2026): in, waiting, late, done, from figures the app already serves. Invented numbers. */
import { describe, expect, it } from "vitest";

import type { Deliverable, ReviewDashboard } from "../../types/api";
import { deliverablesRow, glanceLine, queriesRow, reviewsRow } from "./AtAGlance";

describe("at a glance", () => {
  it("document reviews: one unit (reviews) so in = waiting + done; the documents not reviewed yet are said apart; never 'late'", () => {
    const d = { submittals_total: 5, submittals_awaiting_review: 1, reviews_awaiting_decision: 5, reviews_running: 0, reviews_signed: 1 } as unknown as ReviewDashboard;
    const row = reviewsRow(d);
    expect([row.inCount, row.waiting, row.late, row.done]).toEqual([6, 5, null, 1]);
    expect(row.sentence).toBe("Document reviews: 6 in; 5 waiting (5 to sign off); 1 signed off. 1 of 5 contractor documents not reviewed yet.");
  });
  it("queries: duplicates and cancelled are not 'in'; late is the server's count, with its boundary", () => {
    const row = queriesRow({ drafting: 30, resolved: 2, duplicate: 1, total: 33, overdue: 4, open_with_due_date: 6 })!;
    expect([row.inCount, row.waiting, row.late, row.done]).toEqual([32, 30, 4, 2]);
    expect(row.lateNote).toBe("past the due date, of 6 open with a due date");
    expect(queriesRow("off")).toBeNull(); // switched off: no row
  });
  it("deliverables: done = approved; superseded is neither waiting nor done; late = the overdue alerts", () => {
    const items = [{ status: "approved" }, { status: "superseded" }, { status: "submitted" }, { status: "planned" }] as Deliverable[];
    const row = deliverablesRow(items, 1);
    expect([row.inCount, row.waiting, row.late, row.done]).toEqual([4, 2, 1, 1]);
  });
  it("a figure that could not be loaded is unknown, never 0", () => {
    expect([reviewsRow(null).inCount, queriesRow(null)!.done, deliverablesRow(null, null).waiting]).toEqual([null, null, null]);
    expect(reviewsRow(null).sentence).toBe("Document reviews: could not be loaded.");
  });
  it("the one line says what is waiting and what is late", () => {
    const d = { submittals_total: 5, submittals_awaiting_review: 0, reviews_awaiting_decision: 5, reviews_running: 0, reviews_signed: 1 } as unknown as ReviewDashboard;
    const rows = [reviewsRow(d), queriesRow({ drafting: 33, total: 33, overdue: 2, open_with_due_date: 4 })!, deliverablesRow([], 0)];
    expect(glanceLine(rows)).toBe("Waiting: 5 document reviews, 33 queries and CFCs, 0 deliverables. Late: 2 queries and CFCs.");
  });
});
