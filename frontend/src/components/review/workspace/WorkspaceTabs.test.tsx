/**
 * Builder A: the tab strip is a proper tab list.
 *
 * MUTATION PROOF: remove the ArrowRight branch and the arrow test fails;
 * give every tab tabIndex 0 and the roving test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { WorkspaceTab } from "./contract";
import { WorkspaceTabs } from "./WorkspaceTabs";

function Harness({ onTab, mode, initial = "sheet" }: {
  onTab?: (t: WorkspaceTab) => void; mode?: "simple" | "detailed"; initial?: WorkspaceTab;
}) {
  const [tab, setTab] = useState<WorkspaceTab>(initial);
  return (
    <WorkspaceTabs tab={tab} mode={mode} onTab={(t) => { onTab?.(t); setTab(t); }}>
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

describe("WorkspaceTabs v2.2 Simple view", () => {
  /** MUTATION PROOF: show WORKSPACE_TABS in Simple view and the first
   *  expectation fails; open the Details row always and the closed-row one
   *  fails. */
  it("shows Comment sheet, CRS preview and replies and Details; the engineer tabs wait under Details", async () => {
    const user = userEvent.setup();
    const onTab = vi.fn();
    render(<Harness mode="simple" onTab={onTab} />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Comment sheet", "CRS preview and replies", "Details"]);
    expect(screen.queryByRole("tablist", { name: "Details" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "false");

    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(onTab).toHaveBeenLastCalledWith("how");
    const row = screen.getByRole("tablist", { name: "Details" });
    expect(within(row).getAllByRole("tab").map((t) => t.textContent))
      .toEqual(["How this was reviewed", "Findings", "Standards", "Steps", "Numbers"]);
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    await user.click(within(row).getByRole("tab", { name: "Numbers" }));
    expect(screen.getByText("showing numbers")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Numbers");

    // Back to the sheet closes the row; Details then returns to the last one.
    await user.click(screen.getByRole("tab", { name: "Comment sheet" }));
    expect(screen.queryByRole("tablist", { name: "Details" })).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(screen.getByText("showing numbers")).toBeInTheDocument();
  });

  it("opening on an engineer tab opens the Details row with Details selected", () => {
    render(<Harness mode="simple" initial="steps" />);
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Steps" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("showing steps")).toBeInTheDocument();
  });

  it("arrow keys, Home and End work in both rows", async () => {
    const user = userEvent.setup();
    render(<Harness mode="simple" />);
    await user.click(screen.getByRole("tab", { name: "Comment sheet" }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "CRS preview and replies" })).toHaveFocus();
    expect(screen.getByText("showing crs")).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Details" })).toHaveFocus();
    expect(screen.getByText("showing how")).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Comment sheet" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Details" })).toHaveFocus();
    // In the Details row.
    await user.click(screen.getByRole("tab", { name: "How this was reviewed" }));
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Numbers" })).toHaveFocus();
    expect(screen.getByText("showing numbers")).toBeInTheDocument();
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "How this was reviewed" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("showing findings")).toBeInTheDocument();
  });
});
