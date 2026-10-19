/**
 * Builder D's "Review again": asks `mayStart` before anything starts, so a
 * reader who chooses to stay with unsaved decisions starts no review.
 * Made-up data only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewAgainButton } from "./ReviewAgainButton";

const reviewAgain = vi.fn();
vi.mock("./newReview", () => ({ reviewAgain: (...a: unknown[]) => reviewAgain(...a) }));

beforeEach(() => {
  reviewAgain.mockReset().mockResolvedValue({ ok: true, runId: "run-2" });
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
});
