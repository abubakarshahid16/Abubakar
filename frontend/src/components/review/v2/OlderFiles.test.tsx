import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OlderFiles } from "./OlderFiles";

describe("OlderFiles", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is History, collapsed, and says under the AI buttons what the older file holds", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ run_id: "r2", ai_lines: 53, paper_points: 113 }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    render(<OlderFiles ruleCheckRun="r1" aiRun="r2" />);
    const box = screen.getByTestId("v2-older-files") as HTMLDetailsElement;
    expect(box.tagName).toBe("DETAILS");
    expect(box.open).toBe(false);
    expect(box.textContent).toContain("History");
    await waitFor(() => expect(screen.getByTestId("older-file-line").textContent).toContain("53 lines only. The complete CRS (113 points) is the download above."));
  });

  it("shows nothing when there is no run", () => {
    const { container } = render(<OlderFiles ruleCheckRun={null} aiRun={null} />);
    expect(container.innerHTML).toBe("");
  });
});
