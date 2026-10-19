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

const reviewAgain = vi.fn();
const loadPriorDecision = vi.fn();
vi.mock("./newReview", () => ({
  reviewAgain: (...a: unknown[]) => reviewAgain(...a),
  loadPriorDecision: (...a: unknown[]) => loadPriorDecision(...a),
}));

beforeEach(() => {
  reviewAgain.mockReset().mockResolvedValue({ ok: true, runId: "run-2" });
  loadPriorDecision.mockReset().mockResolvedValue({ kind: "none" });
});

describe("ReviewAgainButton", () => {
  it("starts nothing when mayStart says no", async () => {
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} mayStart={() => false} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(reviewAgain).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("starts the review and opens it when mayStart says yes", async () => {
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" filename="Pump datasheet rev B.pdf" onStarted={onStarted} mayStart={() => true} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(reviewAgain).toHaveBeenCalledWith("doc-1", "Pump datasheet rev B.pdf");
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-2"));
  });

  it("a signed latest review asks first; Cancel starts nothing", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "signed", finalCode: "Approved" });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/already signed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(reviewAgain).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
  });

  it("a final code on the latest review asks first; Yes starts and opens the new review", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "final_code", finalCode: "Approved with Comments" });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" filename="Pump datasheet rev B.pdf" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/final code "Approved with Comments"/)).toBeInTheDocument();
    expect(reviewAgain).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Yes, start a new review" }));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-2"));
    expect(reviewAgain).toHaveBeenCalledWith("doc-1", "Pump datasheet rev B.pdf");
  });

  it("when the latest review cannot be checked, it asks rather than assuming", async () => {
    loadPriorDecision.mockResolvedValue({ kind: "unknown" });
    render(<ReviewAgainButton documentId="doc-1" onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText(/Could not check/)).toBeInTheDocument();
    expect(reviewAgain).not.toHaveBeenCalled();
  });

  it("without onOpenRun, the running review opens through onStarted", async () => {
    reviewAgain.mockResolvedValue({ ok: false, message: "A review of this document is already running.", runningRunId: "run-7" });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    await userEvent.click(await screen.findByRole("button", { name: "Open the review that is running" }));
    expect(onStarted).toHaveBeenCalledWith("run-7");
  });

  it("no button to open a running review when the API did not name one", async () => {
    reviewAgain.mockResolvedValue({ ok: false, message: "A review of this document is already running.", runningRunId: null });
    render(<ReviewAgainButton documentId="doc-1" onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A review of this document is already running.");
    expect(screen.queryByRole("button", { name: "Open the review that is running" })).toBeNull();
  });
});
