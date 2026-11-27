/** H's audit of the Analysis page (27 Nov 2026): #28 a one-off green subtitle under the title; #33 a hand-made pill notice; #32 "On" in
 *  mono capitals. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalysisHeader } from "./AnalysisHeader";
import { RunPlan } from "./AnalysisRunPlan";
import { enginesFor } from "./analysisModel";

describe("the Analysis page in one kit", () => {
  it("has the kit's page title, no subtitle line, and the market rule in the kit's notice box", () => {
    render(<AnalysisHeader />);
    expect(screen.getByRole("heading", { level: 1, name: "Analysis Hub" }).className).toContain("kit-title");
    expect(screen.queryByText("Ask about your documents")).toBeNull();
    const rule = screen.getByText("Market rule").closest(".kit-notice");
    expect(rule?.className).toContain("kit-notice--warn");
  });

  it("says On and Off in the body face, not mono capitals", () => {
    render(<RunPlan mode="focused" engines={enginesFor("focused", { gaps: false, market: false, recommendation: false } as Parameters<typeof enginesFor>[1])} />);
    for (const word of screen.getAllByText(/^(On|Off)$/)) expect(word.className).not.toMatch(/font-mono|uppercase/);
  });
});
