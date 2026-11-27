/** The Dashboard's three tiles (owner, 27 Nov 2026 03:34; the shared kit). Invented values only. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NEW_LOOK } from "../../look";
import { NavigationContext } from "../NavLink";
import { AtAGlance, lateWords, waitingHeadline, type GlanceRow } from "./AtAGlance";

const client = vi.hoisted(() => ({
  reviews: { dashboard: vi.fn() },
  deliverables: { list: vi.fn(), alerts: vi.fn() },
}));
const tq = vi.hoisted(() => ({ technicalQueriesApi: { metrics: vi.fn() } }));
vi.mock("../../api/client", () => client);
vi.mock("../../api/technicalQueries", () => tq);

const row = (over: Partial<GlanceRow>): GlanceRow => ({ label: "Deliverables", inCount: 3, waiting: 2, late: null, done: 1, lateStatus: "no_due_dates", lateNote: "", ...over });

describe("the tiles' words", () => {
  it("says how many items wait, in one plain headline; an unknown figure is said, never 0", () => {
    expect(waitingHeadline([row({ waiting: 16 }), row({ waiting: 25 })])).toBe("41 items are waiting for a decision");
    expect(waitingHeadline([row({ waiting: 1 })])).toBe("1 item is waiting for a decision");
    expect(waitingHeadline([row({ waiting: 4 }), row({ waiting: null })])).toBe("4 items are waiting for a decision (some figures could not be loaded)");
  });
  it("never leaves a dash where nothing can be late", () => {
    expect(lateWords(row({ lateStatus: "no_due_dates" }))).toBe("no due dates set");
    expect(lateWords(row({ lateStatus: "not_tracked" }))).toBe("no due dates set");
    expect(lateWords(row({ lateStatus: "unknown" }))).toBe("late not known");
    expect(lateWords(row({ lateStatus: "counted", late: 0 }))).toBe("none late");
    expect(lateWords(row({ lateStatus: "counted", late: 2 }))).toBeUndefined(); // the red "2 late" says it
  });
});

describe.runIf(NEW_LOOK)("the three tiles on the Dashboard (new look)", () => {
  it("shows a headline and three tiles, each one button that opens its list", async () => {
    client.reviews.dashboard.mockResolvedValue({ ok: true, data: { reviews_awaiting_decision: 14, reviews_running: 2, reviews_signed: 12 } });
    tq.technicalQueriesApi.metrics.mockResolvedValue({ ok: true, data: { total: 30, drafting: 6, awaiting_review: 21, resolved: 3, duplicate: 0, cancelled: 0, overdue: 2, open_with_due_date: 5 } });
    client.deliverables.list.mockResolvedValue({ ok: true, data: { deliverables: [{ status: "approved", due_date: null }, { status: "draft", due_date: null }] } });
    client.deliverables.alerts.mockResolvedValue({ ok: true, data: { alerts: [] } });
    const navigate = vi.fn();
    render(<NavigationContext.Provider value={navigate}><AtAGlance /></NavigationContext.Provider>);
    expect(await screen.findByRole("heading", { level: 2, name: "38 items are waiting for a decision" })).toBeTruthy();
    const tiles = within(screen.getByRole("group", { name: "Waiting for a decision" })).getAllByRole("button");
    expect(tiles.map((t) => t.textContent)).toEqual([
      "Document reviews 16 waiting for you 12 done no due dates set", // real spaces between the parts (read aloud or copied)
      "Queries and CFCs 21 waiting for you 3 done 2 late", // waiting for a person: not the 6 the AI is still drafting (F's walk)
      "Deliverables 1 waiting for you 1 done no due dates set",
    ]);
    expect(screen.queryByRole("table")).toBeNull(); // no table, no dashes (owner 03:34)
    // every count states its boundary (rule 4), one click away
    expect(screen.getByTestId("glance-boundary").textContent).toContain("These counts cover only what you may open.");
    fireEvent.click(tiles[1]);
    expect(navigate).toHaveBeenCalledWith("technicalQueries");
    fireEvent.click(tiles[0]);
    expect(navigate).toHaveBeenCalledWith("review");
  });
});
