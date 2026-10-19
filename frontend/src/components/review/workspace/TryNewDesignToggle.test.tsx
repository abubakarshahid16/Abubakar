/**
 * v2.1 W3: "Try new design" is small and in the top right corner: it takes
 * no line of its own above the review's title.
 * MUTATION PROOF: put back the old full-width "flex justify-end" row and
 * the first test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TryNewDesignToggle } from "./TryNewDesignToggle";

describe("TryNewDesignToggle (v2.1 W3)", () => {
  it("takes no height of its own and hangs small in the top right corner", () => {
    render(<><TryNewDesignToggle on={false} onChange={vi.fn()} /><h1>Pump datasheet rev B.pdf</h1></>);
    const wrapper = screen.getByTestId("try-new-design");
    expect(wrapper.className).toContain("h-0");
    expect(wrapper.className).not.toContain("justify-end");
    const label = screen.getByText("Try new design");
    expect(label.className).toContain("absolute");
    expect(label.className).toContain("right-0");
    expect(label.className).toContain("text-xs");
  });

  it("still switches", async () => {
    const onChange = vi.fn();
    render(<TryNewDesignToggle on={false} onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
