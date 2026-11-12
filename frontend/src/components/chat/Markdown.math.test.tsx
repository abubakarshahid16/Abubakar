import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, texToPlain } from "./Markdown";

describe("formulas in a chat answer", () => {
  it("shows LaTeX as plain readable text, never raw markup", () => {
    render(<Markdown text={"Convert with $P_{\\text{bara}} = P_{\\text{barg}} + 1.013$ at sea level."} />);
    const f = screen.getByTestId("formula");
    expect(f).toHaveTextContent("P_bara = P_barg + 1.013");
    expect(document.body.textContent).not.toMatch(/[$\\]|\{|\}/);
  });
  it("turns common commands into characters", () => {
    expect(texToPlain("$\\frac{a}{b} \\times 2 \\leq x^{2}$")).toBe("(a)/(b) × 2 ≤ x^2");
    expect(texToPlain("$$\\Delta P = \\sqrt{x}$$")).toBe("Δ P = √(x)");
  });
  it("leaves prices and plain dollar text alone", () => {
    expect(texToPlain("$5 to $")).toBeNull();
    render(<Markdown text={"It costs $5 or $10 a day."} />);
    expect(screen.queryByTestId("formula")).toBeNull();
    expect(document.body.textContent).toContain("$5 or $10");
  });
});
