import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MoreText } from "./MoreText";
import { AnalysisHeader } from "../views/analysis/AnalysisHeader";

describe("MoreText", () => {
  it("shows the one line, hides the rest by default, keeps it in the page, and opens on More", async () => {
    render(<MoreText summary="Short line.">The long part.</MoreText>);
    const button = screen.getByRole("button", { name: "More" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("The long part.").closest("[hidden]")).not.toBeNull();
    await userEvent.setup().click(button);
    expect(screen.getByRole("button", { name: "Less" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("The long part.").closest("[hidden]")).toBeNull();
  });
});

describe("Analysis header", () => {
  it("folds the three rule paragraphs behind More, with their text kept", () => {
    render(<AnalysisHeader />);
    const evidence = screen.getByText(/A statement about a document is shown only when the page/); // everyday words (owner, 26 Nov 2026)
    expect(evidence.closest("[hidden]")).not.toBeNull();
    expect(screen.getByRole("button", { name: "More" })).toBeInTheDocument();
  });
  it("keeps the sample-data market rule visible without opening More", () => {
    render(<AnalysisHeader />);
    const market = screen.getByText(/Market prices shown here are sample data/); // everyday words (owner, 26 Nov 2026)
    expect(market.closest("[hidden]")).toBeNull();
  });
});
