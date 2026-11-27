/** H's audit of the Deliverables page (27 Nov 2026): #28 a one-off green eyebrow over the title; #44 two chips on every expected row;
 *  #45 41 expected rows made a 7,330 px page. Invented values. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DeliverablesView, EXPECTED_SHOWN } from "./DeliverablesView";
import { NEW_LOOK } from "../look";

const ok = (data: unknown) => Promise.resolve({ ok: true, data });
const expectedItem = (i: number) => ({
  id: `e${i}`, wbs_code: `9.${i}`, title: `Inferred invented requirement ${i}`, deliverable_type: "Engineering submittal",
  origin: "inferred", source_name: "Invented standard", source_page: 3, state: "missing",
});
const rows = vi.hoisted(() => ({ list: null as unknown[] | null }));
vi.mock("../api/client", () => ({
  deliverables: {
    list: () => ok({ deliverables: [] }),
    alerts: () => ok({ alerts: [] }),
    expected: () => ok({ deliverables: rows.list ?? Array.from({ length: 20 }, (_, i) => expectedItem(i)) }),
  },
  management: { escalationRules: () => ok({ rules: [] }) },
  risks: { list: () => ok({ risks: [], total: 0, limit: 50, offset: 0 }) },
}));

describe("the Deliverables page in one kit", () => {
  it("shows the kit's page header with no eyebrow line above the title (#28)", async () => {
    render(<DeliverablesView />);
    const title = await screen.findByRole("heading", { level: 1, name: "Deliverables" });
    expect(title.className).toContain("kit-title");
    expect(screen.queryByText("Project documents to deliver")).toBeNull();
  });

  it("gives each expected row one chip, and folds the rows after the first ones with their count (#44, #45)", async () => {
    render(<DeliverablesView />);
    const fold = await screen.findByTestId("expected-more");
    expect(within(fold).getByText(`Show the other ${20 - EXPECTED_SHOWN} expected deliverables`)).toBeInTheDocument();
    expect(fold.tagName).toBe("DETAILS");
    expect(within(fold).getByText(/requirement 19/)).toBeInTheDocument(); // folded, never dropped
    expect(screen.queryByText("AI suggested · review before accepting")).toBeNull();
    // every row has the same state and origin: said ONCE above the list, not on each row (H's gate of #1971)
    expect(screen.getByTestId("expected-said-once").textContent).toBe(
      "All 20 are not in the deliverables list yet. All were suggested by the AI: check each before accepting it.",
    );
    expect(screen.queryByText("not in the list yet")).toBeNull();
    expect(screen.queryByText(/suggested by the AI, check it before accepting/)).toBeNull();
  });

  it("keeps a state or an origin on its row when the rows differ", async () => {
    rows.list = [expectedItem(1), { ...expectedItem(2), state: "matched", origin: "manual" }];
    try {
      render(<DeliverablesView />);
      expect(await screen.findByText("not in the list yet")).toBeTruthy();
      expect(screen.getByText("matched")).toBeTruthy();
      expect(screen.getByText(/suggested by the AI, check it before accepting/)).toBeTruthy();
      expect(screen.getByText(/added by hand/)).toBeTruthy();
      expect(screen.queryByTestId("expected-said-once")).toBeNull();
    } finally {
      rows.list = null;
    }
  });
  it.runIf(NEW_LOOK)("each 'Add deliverable' field says what it is above it (C's walk, 27 Nov 2026)", async () => {
    render(<DeliverablesView />);
    for (const label of ["Item number in the project list", "Deliverable title", "Deliverable type", "Due date"]) {
      const field = await screen.findByLabelText(label);
      expect(field.className).toBe("kit-input");
      expect(document.querySelector(`label[for="${field.id}"]`)?.textContent).toBe(label);
    }
  });
});

