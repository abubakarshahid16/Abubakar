import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OlderFiles, PaperHistoryList, type PaperHistory } from "./OlderFiles";

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

  it("labels the box and its files 'Earlier version', and keeps the buttons' own names", () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ run_id: "r2", ai_lines: 5, paper_points: 9 }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    render(<OlderFiles ruleCheckRun="r1" aiRun="r2" />);
    expect(screen.getByTestId("v2-older-files").textContent).toContain("(Earlier version)");
    expect(screen.getByTestId("earlier-version-note").textContent).toContain("Earlier version");
    const buttons = screen.getAllByRole("button", { hidden: true }).map((b) => b.textContent ?? "");
    expect(buttons).toEqual(["Rule check, internal copy", "AI review, internal copy", "AI review, contractor working copy (older file, not the issued one)"]);
  });
});

const HISTORY: PaperHistory = {
  paper_document_id: "doc_inv",
  boundary: "reviews of this paper you may read",
  runs: [
    { run_id: "gen_1", version: "general", part: "general review", status: "done", started_at: "2026-11-18T10:00:00Z", finished_at: null, points: 55,
      files: [{ label: "General review, team copy", url: "/api/reviews/papers/doc_inv/general/sheet?run_id=gen_1&copy=team" }] },
    { run_id: "ai_1", version: "earlier version", part: "AI review", status: "completed", started_at: "2026-11-02T10:00:00Z", finished_at: null, points: 53,
      files: [{ label: "AI review, internal copy", url: "/api/reviews/runs/ai_1/agent/crs?copy=internal" }] },
    { run_id: "rc_1", version: "earlier version", part: "rule check", status: "completed", started_at: "2026-11-01T10:00:00Z", finished_at: null, points: null, files: [] },
  ],
};

describe("PaperHistoryList", () => {
  it("says Earlier version for the older runs and General review for the new one, with a count only where one is stored", () => {
    render(<PaperHistoryList history={HISTORY} onProblem={() => undefined} />);
    const rows = screen.getAllByTestId("history-run").map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("Current method");
    expect(rows[0]).toContain("55 points");
    expect(rows[0]).not.toContain("Earlier version");
    expect(rows[1]).toContain("Earlier version");
    expect(rows[1]).toContain("53 points");
    expect(rows[2]).toContain("Earlier version");
    expect(rows[2]).not.toContain("points");
  });

  it("gives a button only for an earlier run's file; the general review's file is on its own page", () => {
    render(<PaperHistoryList history={HISTORY} onProblem={() => undefined} />);
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual(["Earlier version: AI review, internal copy"]);
  });

  it("shows nothing for a paper with no review", () => {
    const { container } = render(<PaperHistoryList history={{ ...HISTORY, runs: [] }} onProblem={() => undefined} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("OlderFiles with the paper's history", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the history route and lists the runs", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(HISTORY), { status: 200, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", fetchMock);
    render(<OlderFiles ruleCheckRun={null} aiRun={null} documentId="doc_inv" />);
    await waitFor(() => expect(screen.getAllByTestId("history-run")).toHaveLength(3));
    const asked = (fetchMock.mock.calls as unknown as [string][]).map((c) => String(c[0]));
    expect(asked.some((u) => u.includes("/reviews/papers/doc_inv/history"))).toBe(true);
  });
});
