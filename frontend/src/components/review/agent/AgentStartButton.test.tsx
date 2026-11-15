/**
 * MUTATION PROOF: draw the button when enabled is false and the first test fails; ignore claude_lane_open and the disabled test fails;
 * start without the pre-start step and "opens the step first" fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentStartButton, LANE_CLOSED_REASON } from "./AgentStartButton";

const stepOpened = vi.fn();
/** THE ONE START: the button opens the shared pre-start step; its Start is `POST /api/reviews/start` with the ids shown. */
vi.mock("../panels/StartReviewStep", () => ({
  StartReviewStep: ({ documentId, filename, onStarted, onCancel }: { documentId: string; filename?: string | null; onStarted: (id: string) => void; onCancel: () => void }) => {
    stepOpened(documentId, filename ?? null);
    return (
      <div data-testid="start-review-step">
        <button type="button" onClick={() => onStarted("r9")}>Start review</button>
        <button type="button" onClick={onCancel}>Cancel step</button>
      </div>
    );
  },
}));

beforeEach(() => stepOpened.mockReset());

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
  it("opens the pre-start step first (nothing starts), and its Start hands the run over", async () => {
    const onStarted = vi.fn();
    render(<AgentStartButton status={{ enabled: true, claude_lane_open: true }} documentId="doc-7" filename="Pump.pdf" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Start AI review" }));
    expect(await screen.findByTestId("start-review-step")).toBeInTheDocument();
    expect(stepOpened).toHaveBeenCalledWith("doc-7", "Pump.pdf");
    expect(onStarted).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(onStarted).toHaveBeenCalledWith("r9");
    expect(screen.queryByTestId("start-review-step")).toBeNull();
  });
  it("Cancel on the step starts nothing and brings the button back", async () => {
    const onStarted = vi.fn();
    render(<AgentStartButton status={{ enabled: true, claude_lane_open: true }} documentId="d" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Start AI review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel step" }));
    expect(onStarted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start AI review" })).toBeEnabled();
  });
});

describe("AgentStartButton: datasheets only", () => {
  const on = { enabled: true, claude_lane_open: true };
  /** MUTATION PROOF: drop the kind check and the other-kind test fails. */
  it("is not drawn for a paper known to be of another kind; drawn for a datasheet or an unknown kind", () => {
    const { container, rerender } = render(<AgentStartButton status={on} documentId="d" paperKind="procedure" onStarted={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AgentStartButton status={on} documentId="d" paperKind="datasheet" onStarted={() => {}} />);
    expect(screen.getByRole("button", { name: "Start AI review" })).toBeInTheDocument();
    rerender(<AgentStartButton status={on} documentId="d" paperKind={null} onStarted={() => {}} />);
    expect(screen.getByRole("button", { name: "Start AI review" })).toBeInTheDocument();
  });
});
