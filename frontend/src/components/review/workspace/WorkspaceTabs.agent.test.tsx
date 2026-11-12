/**
 * The AI reviewer's two tabs exist only while its switch is on.
 * MUTATION PROOF: draw them regardless of `agentTabs` and the first test
 * fails; leave them out of the detailed strip when on and the second fails.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceTabs } from "./WorkspaceTabs";
import { parseWorkspaceQuery, reviewPageFor } from "./workspaceRoute";

describe("agent tabs", () => {
  it("switch off: no AI review tab and no Rules used tab, in either view", () => {
    const { rerender } = render(<WorkspaceTabs tab="sheet" onTab={() => {}} />);
    expect(screen.queryByRole("tab", { name: "AI review" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Rules used" })).toBeNull();
    rerender(<WorkspaceTabs tab="how" mode="simple" onTab={() => {}} />);
    expect(screen.queryByRole("tab", { name: "AI review" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Rules used" })).toBeNull();
  });
  it("switch on: both tabs are drawn, after the existing ones", () => {
    render(<WorkspaceTabs tab="sheet" onTab={() => {}} agentTabs />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent).slice(-2)).toEqual(["AI review", "Rules used"]);
  });
  it("switch on, Simple view: they sit under Details", () => {
    render(<WorkspaceTabs tab="rules" mode="simple" onTab={() => {}} agentTabs />);
    expect(screen.getByRole("tab", { name: "Rules used" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "AI review" })).toBeInTheDocument();
  });
  it("U2, Simple view: AI review is a top-level tab; Rules used stays under Details", () => {
    render(<WorkspaceTabs tab="sheet" mode="simple" onTab={() => {}} agentTabs />);
    expect(within(screen.getByRole("tablist", { name: "Review sections" })).getByRole("tab", { name: "AI review" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Rules used" })).toBeNull();
    render(<WorkspaceTabs tab="rules" mode="simple" onTab={() => {}} agentTabs />);
    expect(within(screen.getByTestId("ws-details-row")).getByRole("tab", { name: "Rules used" })).toBeInTheDocument();
    expect(within(screen.getByTestId("ws-details-row")).queryByRole("tab", { name: "AI review" })).toBeNull();
  });
  it("the addresses of the two tabs are understood", () => {
    expect(parseWorkspaceQuery("?tab=rules").tab).toBe("rules");
    expect(parseWorkspaceQuery("?tab=agent").tab).toBe("agent");
    const page = reviewPageFor("run1", "rules", "");
    expect(page.kind === "workspace" && page.location.tab).toBe("rules");
  });
});
