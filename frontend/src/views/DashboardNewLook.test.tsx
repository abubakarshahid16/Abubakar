/**
 * The owner's Dashboard notes (26 Nov 2026), under the new look's way-back switch (forced ON here; off it is the classic markup,
 * which the other Dashboard and Shell tests keep). Look and order only: the same words and numbers, a long line FOLDED behind
 * "Details" (never cut), a status as its word in the spec's colour, the menu's 11 names with an icon each and the hint on hover,
 * the privacy sentence and the admin boundary moved behind an info fold.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../look", () => ({ NEW_LOOK: true }));

import { StatusChip, TileLine } from "../components/look/LookParts";
import { reviewStatusTone } from "../components/look/lookTone";
import { Shell } from "../components/Shell";
import { Headline, Stat } from "./DashboardPrimitives";

const LONG = "0 running · 5 waiting for an engineer's sign-off or code · 120 earlier reviews not counted";

describe("the new look on the Dashboard (owner's notes)", () => {
  it("a tile shows one big number and its label; a long line is folded behind Details, word for word", () => {
    render(<Headline label="Searchable" value="91" unit="%" note={LONG} />);
    expect(screen.getByText("91")).toBeInTheDocument();
    const fold = screen.getByText("Details").closest("details")!;
    expect(fold).not.toHaveAttribute("open");
    expect(within(fold).getByText(LONG)).toBeInTheDocument();
  });

  it("a short line stays in sight, and a late count is the inverted red tile", () => {
    render(<Stat label="Overdue" value={3} hint="requires follow-up" tone="late" />);
    expect(screen.getByText("requires follow-up").closest("details")).toBeNull();
    expect(screen.getByText("3").closest("div")!.className).toMatch(/bg-pill-fail-bg/);
  });

  it("a status is a chip in the spec's colour, and keeps its word", () => {
    expect(reviewStatusTone("Signed off")).toBe("done");
    expect(reviewStatusTone("Not signed off yet")).toBe("check");
    expect(reviewStatusTone("Changed since sign-off")).toBe("check");
    expect(reviewStatusTone("Late")).toBe("late");
    render(<StatusChip tone="done">Signed off</StatusChip>);
    expect(screen.getByText("Signed off").className).toMatch(/bg-pill-pass-bg/);
  });

  it("the menu keeps every name, each with an icon, its hint on hover only, and the privacy line folded at the bottom", () => {
    render(
      <Shell view="dashboard" onNavigate={() => {}} connection={{ state: "connecting" }} theme="light" onThemeChange={() => {}}
        auth={{ technical_queries: true } as never}>
        <p>page</p>
      </Shell>,
    );
    const nav = screen.getByRole("navigation", { name: "Main" });
    const buttons = within(nav).getAllByRole("button").filter((b) => b.getAttribute("title"));
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Dashboard", "AI Submittal Review", "Documents", "Standards Library", "Analysis Hub", "Chat", "CRS & Reports",
      "Deliverables", "Ingestion", "Technical Queries and CFCs", "Administration",
    ]); // the owner's 11 items (Administration for an admin reader)
    for (const b of buttons) expect(b.querySelector("svg")).not.toBeNull();
    expect(buttons[0]).toHaveAttribute("title", "Metrics, models, readiness");
    expect(within(nav).queryByText("Metrics, models, readiness")).toBeNull(); // not a second grey line
    const privacy = within(nav).getByText("Private by design.").closest("details")!;
    expect(privacy).not.toBeNull();
  });

  it("never cuts a long line: the whole text is in the fold", () => {
    render(<TileLine text={LONG} />);
    expect(screen.getByText(LONG)).toBeInTheDocument();
  });
});
