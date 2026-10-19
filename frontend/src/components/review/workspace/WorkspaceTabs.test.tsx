/**
 * Builder A: the tab strip is a proper tab list.
 *
 * MUTATION PROOF: remove the ArrowRight branch and the arrow test fails;
 * give every tab tabIndex 0 and the roving test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { WorkspaceTab } from "./contract";
import { WorkspaceTabs } from "./WorkspaceTabs";

function Harness({ onTab }: { onTab?: (t: WorkspaceTab) => void }) {
  const [tab, setTab] = useState<WorkspaceTab>("sheet");
  return (
    <WorkspaceTabs tab={tab} onTab={(t) => { onTab?.(t); setTab(t); }}>
      <p>{`showing ${tab}`}</p>
    </WorkspaceTabs>
  );
}

describe("WorkspaceTabs", () => {
  it("is a tablist with plain names, one selected tab in the Tab order", () => {
    render(<Harness />);
    const list = screen.getByRole("tablist", { name: "Review sections" });
    expect(list).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(
      ["Comment sheet", "How this was reviewed", "Findings", "Standards", "Steps", "Numbers", "CRS preview and replies"]);
    expect(screen.getByRole("tab", { name: "Comment sheet" })).toHaveAttribute("aria-selected", "true");
    expect(tabs.filter((t) => t.tabIndex === 0)).toHaveLength(1);
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Comment sheet");
  });

  it("arrow keys move and select, wrapping; Home and End jump", async () => {
    const user = userEvent.setup();
    const onTab = vi.fn();
    render(<Harness onTab={onTab} />);
    await user.click(screen.getByRole("tab", { name: "Comment sheet" }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "How this was reviewed" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "How this was reviewed" })).toHaveFocus();
    expect(screen.getByText("showing how")).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "CRS preview and replies" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Comment sheet" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "CRS preview and replies" })).toHaveFocus();
    expect(onTab).toHaveBeenLastCalledWith("crs");
  });

  it("a click selects a tab", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("tab", { name: "Standards" }));
    expect(screen.getByText("showing standards")).toBeInTheDocument();
  });
});
