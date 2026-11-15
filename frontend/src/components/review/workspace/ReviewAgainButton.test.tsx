/**
 * Builder D's "Review again": asks `mayStart` before anything starts, so a
 * reader who chooses to stay with unsaved decisions starts no review.
 * Before re-running a signed review, or one with the engineer's final code,
 * the reader is asked in the page. Made-up data only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewAgainButton } from "./ReviewAgainButton";

const loadPriorDecision = vi.fn();
vi.mock("./newReview", () => ({
  loadPriorDecision: (...a: unknown[]) => loadPriorDecision(...a),
}));
/** THE ONE START: a fresh review opens the pre-start step (engine, what will leave this Mac, the list); nothing starts before its Start. */
const stepOpened = vi.fn();
vi.mock("../panels/StartReviewStep", () => ({
  StartReviewStep: ({ documentId, filename, onStarted, onCancel }: { documentId: string; filename?: string | null; onStarted: (id: string) => void; onCancel: () => void }) => {
    stepOpened(documentId, filename ?? null);
    return (
      <div data-testid="start-review-step">
        <button type="button" onClick={() => onStarted("run-2")}>Start review</button>
        <button type="button" onClick={onCancel}>Cancel step</button>
      </div>
    );
  },
}));

beforeEach(() => {
  stepOpened.mockReset();
  loadPriorDecision.mockReset().mockResolvedValue({ kind: "none" });
});

describe("ReviewAgainButton", () => {
  it("starts nothing when mayStart says no", async () => {
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} mayStart={() => false} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(stepOpened).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("starts the review and opens it when mayStart says yes", async () => {
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" filename="Pump datasheet rev B.pdf" onStarted={onStarted} mayStart={() => true} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    // the step opens FIRST; nothing has started until its Start
    expect(await screen.findByTestId("start-review-step")).toBeInTheDocument();
    expect(stepOpened).toHaveBeenCalledWith("doc-1", "Pump datasheet rev B.pdf");
    expect(onStarted).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-2"));
  });

  it("a signed latest review asks first; Cancel starts nothing", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "signed", finalCode: "Approved" });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/already signed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(stepOpened).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
  });

  it("a final code on the latest review asks first; Yes starts and opens the new review", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "final_code", finalCode: "Approved with Comments" });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" filename="Pump datasheet rev B.pdf" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/final code "Approved with Comments"/)).toBeInTheDocument();
    expect(stepOpened).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Yes, start a new review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start review" }));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-2"));
    expect(stepOpened).toHaveBeenCalledWith("doc-1", "Pump datasheet rev B.pdf");
  });

  it("when the latest review cannot be checked, it asks rather than assuming", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "unknown" });
    render(<ReviewAgainButton documentId="doc-1" onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/Could not check/)).toBeInTheDocument();
    expect(stepOpened).not.toHaveBeenCalled();
  });

  it("Cancel on the step starts nothing and brings the button back", async () => {
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel step" }));
    expect(onStarted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
  });
});
