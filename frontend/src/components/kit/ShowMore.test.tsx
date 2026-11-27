/** H's audit #10 (27 Nov 2026): a long list drawn all at once. The kit's one "show more". */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShowMore } from "./Kit";

describe("ShowMore", () => {
  it("says how many of how many are shown and offers the next page", () => {
    const onMore = vi.fn();
    render(<ShowMore shown={20} total={45} step={20} onMore={onMore} testId="more" />);
    expect(screen.getByText("Showing 20 of 45.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 20 more" }));
    expect(onMore).toHaveBeenCalledOnce();
  });

  it("offers only what is left, and nothing once everything is shown", () => {
    const { rerender } = render(<ShowMore shown={40} total={45} step={20} onMore={() => {}} testId="more" />);
    expect(screen.getByRole("button", { name: "Show 5 more" })).toBeInTheDocument();
    rerender(<ShowMore shown={45} total={45} step={20} onMore={() => {}} testId="more" />);
    expect(screen.queryByTestId("more")).toBeNull();
  });

  it("is a link, never a boxed button (a link stays a link)", () => {
    render(<ShowMore shown={25} total={272} step={25} onMore={() => {}} testId="more" />);
    const more = screen.getByRole("button", { name: "Show 25 more" });
    expect(more.className).toContain("kit-link");
    expect(more.className).not.toContain("kit-btn");
  });
});
