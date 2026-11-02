/** PF4 (#884): the run's coverage line, in the server's words. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { RunCoverageLine } from "./RunCoverageLine";

const coverage = vi.fn();
vi.mock("../../api/client", () => ({ reviews: { runCoverage: (...a: unknown[]) => coverage(...a) } }));

beforeEach(() => coverage.mockReset());

describe("RunCoverageLine", () => {
  it("prints the server's line for the run", async () => {
    coverage.mockResolvedValue({ ok: true, data: { line: "4 of 9 applicable requirement(s) checked (44.4%)" } });
    render(<RunCoverageLine runId="run-1" />);
    expect(await screen.findByTestId("run-coverage")).toHaveTextContent(
      "Clause coverage: 4 of 9 applicable requirement(s) checked (44.4%).");
    expect(coverage).toHaveBeenCalledWith("run-1");
  });

  it("plan change 6 B: the pair's line prints as it is, under no 'Clause coverage' label", async () => {
    const line = "Standard rules decided: 1 of 40 that apply (pass 1, fail 0, unknown 39). Risk: not measured.";
    coverage.mockResolvedValue({ ok: true, data: { line } });
    render(<RunCoverageLine runId="run-1" />);
    const shown = await screen.findByTestId("run-coverage");
    expect(shown.textContent).toBe(line);
  });

  it("says when it could not be read, never a blank", async () => {
    coverage.mockResolvedValue({ ok: false, error: { message: "x" } });
    render(<RunCoverageLine runId="run-1" />);
    expect(await screen.findByTestId("run-coverage")).toHaveTextContent("Clause coverage could not be read.");
  });
});
