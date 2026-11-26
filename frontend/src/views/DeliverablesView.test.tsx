/**
 * The Deliverables screen: a list whose request failed is not an empty list
 * (audit 2026-09-30). The error box and "No deliverables have been registered
 * yet." once showed together, which states both "it failed" and "there are
 * none".
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverablesView } from "./DeliverablesView";

const list = vi.fn();
const expected = vi.fn();
const ok = (data: unknown) => Promise.resolve({ ok: true, data });
vi.mock("../api/client", () => ({
  deliverables: {
    list: () => list(),
    alerts: () => ok({ alerts: [] }),
    expected: () => expected(),
  },
  management: { escalationRules: () => ok({ rules: [] }) },
  risks: { list: () => ok({ risks: [] }) },
}));

beforeEach(() => { list.mockReset(); expected.mockReset(); expected.mockResolvedValue({ ok: true, data: { deliverables: [] } }); });

describe("the WBS register", () => {
  it("says the register could not be loaded, and never that nothing is registered", async () => {
    list.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "internal_error", message: "the register broke" },
    });
    render(<DeliverablesView />);
    expect(await screen.findByText("the register broke")).toBeInTheDocument();
    expect(screen.getByText(/The deliverables list could not be loaded/)).toBeInTheDocument(); // everyday words (was 'WBS register')
    expect(screen.queryByText("No deliverables have been registered yet.")).toBeNull();
  });

  it("says nothing is registered when the register loaded empty", async () => {
    list.mockResolvedValue({ ok: true, data: { deliverables: [] } });
    render(<DeliverablesView />);
    expect(await screen.findByText("No deliverables have been registered yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});


describe("V2: an inferred expectation is named by its source", () => {
  const row = (over: object) => ({
    id: "e1", wbs_code: "1.2", deliverable_type: "report", title: "Inferred report requirement", required: true,
    deliverable_id: null, status: null, state: "missing", origin: "inferred", ...over,
  });
  it("shows the source file and page, and says when the page was not recorded; never the word null", async () => {
    list.mockResolvedValue({ ok: true, data: { deliverables: [] } });
    expected.mockResolvedValue({ ok: true, data: { deliverables: [
      row({ source_name: "spec-a.pdf", source_page: 7 }),
      row({ id: "e2", wbs_code: "1.3", source_name: "spec-b.pdf", source_page: null }),
    ] } });
    render(<DeliverablesView />);
    expect(await screen.findByText(/from spec-a\.pdf, page 7/)).toBeInTheDocument();
    expect(screen.getByText(/from spec-b\.pdf, page not recorded/)).toBeInTheDocument();
    expect(screen.queryByText(/\bnull\b/)).toBeNull();
  });
});

describe("everyday words and the late count (lead-4, 26 Nov 2026)", () => {
  const item = (status: string, due_date: string | null) => ({ status, due_date }) as never;
  it("late is past the due date, over the open items with a due date; with none it is not counted", async () => {
    const { deliverablesSummary } = await import("./DeliverablesView");
    expect(deliverablesSummary([], [])).toBe("No deliverable is listed yet: add the first one below.");
    expect(deliverablesSummary([item("submitted", null)], [])).toBe("1 deliverable listed; late: not counted, none open has a due date.");
    // due today (days_overdue 0) is not late; an approved item is not in the boundary
    expect(deliverablesSummary([item("submitted", "2026-11-20"), item("planned", "2026-11-26"), item("approved", "2026-01-01")],
      [{ days_overdue: 6 }, { days_overdue: 0 }])).toBe("3 deliverables listed; 1 late, of 2 open with a due date.");
  });
  it("an AI-suggested title loses the word 'Inferred' on screen", async () => {
    const { expectedTitle } = await import("./DeliverablesView");
    expect(expectedTitle("Inferred drawing requirement")).toBe("Drawing requirement");
    expect(expectedTitle("Pump datasheet")).toBe("Pump datasheet");
  });
  it("a replaced deliverable reads in everyday words; the stored value is unchanged", async () => {
    const { statusWords } = await import("./DeliverablesView");
    expect(statusWords("superseded")).toBe("replaced by a later revision");
    expect(statusWords("under_review")).toBe("under review");
  });
});
