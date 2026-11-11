/**
 * MUTATION PROOF: draw the button when enabled is false and the first test
 * fails; ignore claude_lane_open and the disabled test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentStartButton, LANE_CLOSED_REASON } from "./AgentStartButton";

const start = vi.fn();
vi.mock("../../../api/agentReview", () => ({ agentReview: { start: (...a: unknown[]) => start(...a) } }));

beforeEach(() => start.mockReset());

describe("AgentStartButton", () => {
  it("draws nothing while the switch is off or unknown", () => {
    const { container, rerender } = render(<AgentStartButton status={null} documentId="d" onStarted={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AgentStartButton status={{ enabled: false, claude_lane_open: true }} documentId="d" onStarted={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("is disabled with a plain reason when the Claude lane is closed", () => {
    render(<AgentStartButton status={{ enabled: true, claude_lane_open: false }} documentId="d" onStarted={() => {}} />);
    const button = screen.getByRole("button", { name: "Start AI review" });
    expect(button).toBeDisabled();
    expect(screen.getByText(LANE_CLOSED_REASON)).toBeInTheDocument();
    expect(button).toHaveAccessibleDescription(LANE_CLOSED_REASON);
  });
  it("starts a run for the open document and hands the run over", async () => {
    start.mockResolvedValue({ ok: true, data: { review_run_id: "r9" } });
    const onStarted = vi.fn();
    render(<AgentStartButton status={{ enabled: true, claude_lane_open: true }} documentId="doc-7" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Start AI review" }));
    expect(start).toHaveBeenCalledWith("doc-7");
    expect(onStarted).toHaveBeenCalledWith({ review_run_id: "r9" });
  });
  it("shows the server's refusal", async () => {
    start.mockResolvedValue({ ok: false, disconnected: false, error: { code: "conflict", message: "A review is already running." } });
    render(<AgentStartButton status={{ enabled: true, claude_lane_open: true }} documentId="d" onStarted={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Start AI review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A review is already running.");
  });
});
