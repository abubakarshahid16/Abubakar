import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OlderFileLine } from "./OlderFileLine";

const answer = (body: unknown, status = 200) =>
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }))));

describe("OlderFileLine", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says what the older file holds and where the complete CRS is", async () => {
    answer({ run_id: "r1", ai_lines: 53, paper_points: 113 });
    render(<OlderFileLine runId="r1" />);
    await waitFor(() => expect(screen.getByTestId("older-file-line")).toBeTruthy());
    expect(screen.getByTestId("older-file-line").textContent).toBe("Older file: the AI review's 53 lines only. The complete CRS (113 points) is the download above.");
  });

  it("leaves the points out when they are not known, and says nothing at all when the lines are not known (never 0)", async () => {
    answer({ run_id: "r1", ai_lines: 53, paper_points: null });
    const { unmount } = render(<OlderFileLine runId="r1" where="the one CRS of the paper" />);
    await waitFor(() => expect(screen.getByTestId("older-file-line")).toBeTruthy());
    expect(screen.getByTestId("older-file-line").textContent).toBe("Older file: the AI review's 53 lines only. The complete CRS is the one CRS of the paper.");
    unmount();
    answer({ run_id: "r1", ai_lines: null, paper_points: 113 });
    render(<OlderFileLine runId="r2" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("older-file-line")).toBeNull();
  });
});
