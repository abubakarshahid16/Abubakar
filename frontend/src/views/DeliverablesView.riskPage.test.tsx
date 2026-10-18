/**
 * Order 88a: the risk register shows ONE PAGE and the total, never the whole
 * table. The owner's register drew 147,770 rows at once (1.18 million page
 * elements); the browser tab froze.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverablesView } from "./DeliverablesView";

const ok = (data: unknown) => Promise.resolve({ ok: true, data });
const risk = (i: number, extra: object = {}) => ({
  id: `r${i}`, risk_type: "schedule", title: `Risk number ${i}`, description: "3 days overdue",
  severity: "major", status: "open", deliverable_id: null, document_id: null, owner_user_id: null,
  due_date: null, source_finding_id: null, created_at: "2026-10-01", updated_at: "2026-10-01", ...extra,
});

const risksList = vi.fn();
vi.mock("../api/client", () => ({
  deliverables: {
    list: () => ok({ deliverables: [] }),
    alerts: () => ok({ alerts: [] }),
    expected: () => ok({ deliverables: [] }),
  },
  management: { escalationRules: () => ok({ rules: [] }) },
  risks: { list: (type?: string, offset?: number) => risksList(type, offset) },
}));

beforeEach(() => risksList.mockReset());

describe("the risk register is paged", () => {
  it("draws one page, states the total, and loads the next page on request", async () => {
    risksList.mockImplementation((_type: string, offset = 0) => ok({
      risks: Array.from({ length: offset ? 20 : 50 }, (_, i) => risk(offset + i)),
      total: 70, limit: 50, offset,
    }));
    render(<DeliverablesView />);
    expect(await screen.findByText("Showing 50 of 70 schedule risks you may see.")).toBeInTheDocument();
    expect(screen.queryByText("Risk number 50")).toBeNull();
    // the screen asks for the type its filter shows, not every type
    expect(risksList).toHaveBeenCalledWith("schedule", undefined);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Risk number 69")).toBeInTheDocument();
    expect(risksList).toHaveBeenLastCalledWith("schedule", 50);
    expect(screen.getByText("Showing 70 of 70 schedule risks you may see.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("keeps the screen under 5,000 page elements however large the register is", async () => {
    risksList.mockImplementation(() => ok({
      risks: Array.from({ length: 50 }, (_, i) => risk(i)), total: 147770, limit: 50, offset: 0,
    }));
    render(<DeliverablesView />);
    expect(await screen.findByText("Showing 50 of 147770 schedule risks you may see.")).toBeInTheDocument();
    expect(document.querySelectorAll("*").length).toBeLessThan(5000);
  });

  it("names how many findings a grouped row stands for", async () => {
    risksList.mockImplementation(() => ok({
      risks: [risk(1, { risk_type: "review", finding_count: 27, title: "Review response overdue" })],
      total: 1, limit: 50, offset: 0,
    }));
    render(<DeliverablesView />);
    expect(await screen.findByText("AI suggested · 27 review findings on this document")).toBeInTheDocument();
  });
});
