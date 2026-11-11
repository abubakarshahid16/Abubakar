/**
 * The AI review tab: summary, downloads, lines, trace. MUTATION PROOF: point
 * the contractor button at "internal" and the download test fails; show the
 * panel for a classic review (summary 404) and the not-agent test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentReviewPanel, NOT_AGENT_RUN } from "./AgentReviewPanel";

const api = { summary: vi.fn(), lines: vi.fn(), trace: vi.fn(), exportCrs: vi.fn() };
vi.mock("../../../api/agentReview", () => ({
  agentReview: {
    summary: (...a: unknown[]) => api.summary(...a), lines: (...a: unknown[]) => api.lines(...a),
    trace: (...a: unknown[]) => api.trace(...a), exportCrs: (...a: unknown[]) => api.exportCrs(...a),
  },
  isFeatureOff: (r: { ok: boolean; error?: { code: string } }) => !r.ok && r.error?.code === "not_found",
}));

const SUMMARY = { ok: true, data: {
  paper_kind: "datasheet", paper_kind_source: "title", equipment_type: null, counts_by_class: { "Proven by code": 1 },
  usd: null, models: [], stop_reason: null, missing_books: [],
} };
const LINES = { ok: true, data: { lines: [{
  item_id: "L1", verdict_class: "Proven by code", word: "Fail", page: 2, clause: "5.1", rule_book: "Book A", reason: "r", rule_tier: "Owner",
}], next: null } };

beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); });

describe("AgentReviewPanel", () => {
  it("a classic review (summary 404) says it was not made by the AI reviewer", async () => {
    api.summary.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "x" } });
    render(<AgentReviewPanel runId="r1" />);
    expect(await screen.findByText(NOT_AGENT_RUN)).toBeInTheDocument();
    expect(api.lines).not.toHaveBeenCalled();
  });
  it("opens the trace of a clicked line and shows its fields and gate steps", async () => {
    api.summary.mockResolvedValue(SUMMARY);
    api.lines.mockResolvedValue(LINES);
    api.trace.mockResolvedValue({ ok: true, data: {
      item_id: "L1", page: 2, paper_quote: "PQ text", rule_quote: "RQ text", rule_book: "Book A", clause: "5.1",
      model: "model-x", reason: "because", gate: [{ step: "quote check", outcome: "found", reason: "page 2" }],
    } });
    render(<AgentReviewPanel runId="r1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Open the trace of line L1" }));
    expect(api.trace).toHaveBeenCalledWith("r1", "L1");
    const trace = await screen.findByTestId("agent-trace");
    for (const t of ["PQ text", "RQ text", "Book A", "5.1", "model-x", "because"]) expect(trace).toHaveTextContent(t);
    expect(trace).toHaveTextContent("quote check: found (page 2)");
    await userEvent.click(screen.getByRole("button", { name: "Close trace" }));
    expect(screen.queryByTestId("agent-trace")).toBeNull();
  });
  it("each download button asks for its own copy and hands the file to the browser", async () => {
    api.summary.mockResolvedValue(SUMMARY);
    api.lines.mockResolvedValue(LINES);
    api.exportCrs.mockResolvedValue({ ok: true, data: { blob: new Blob(["x"]), filename: "f.xlsx" } });
    const create = vi.fn(() => "blob:x");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    render(<AgentReviewPanel runId="r1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Download CRS, contractor copy" }));
    expect(api.exportCrs).toHaveBeenLastCalledWith("r1", "contractor");
    await userEvent.click(screen.getByRole("button", { name: "Download CRS, internal copy" }));
    expect(api.exportCrs).toHaveBeenLastCalledWith("r1", "internal");
    expect(create).toHaveBeenCalledTimes(2);
  });
  it("a failed download shows the server's words", async () => {
    api.summary.mockResolvedValue(SUMMARY);
    api.lines.mockResolvedValue(LINES);
    api.exportCrs.mockResolvedValue({ ok: false, disconnected: false, error: { code: "internal", message: "No file yet." } });
    render(<AgentReviewPanel runId="r1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Download CRS, internal copy" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No file yet.");
  });
});
