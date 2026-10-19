/**
 * Builder D: a watched review that finishes shows "Your review of X is
 * ready" on any view, with "Open it" and "Dismiss"; the watch list survives
 * a re-mount and a refresh (sessionStorage), and blocked storage never breaks.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reviewRun = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: { reviewRun: (...a: unknown[]) => reviewRun(...a) },
}));

import { FinishedReviewNotice } from "./FinishedReviewNotice";
import { WATCH_STORAGE_KEY, checkWatchedRuns, reloadWatchStoreForTests, watchRun } from "./reviewWatch";

const running = { ok: true, data: { review_run_id: "run-1", status: "running", submittal_filename: "Pump datasheet rev B.pdf" } };
const completed = { ok: true, data: { review_run_id: "run-1", status: "completed", submittal_filename: "Pump datasheet rev B.pdf" } };

/** Some other screen of the app, with the notice mounted beside it as App does. */
function AnotherView({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  return (
    <div>
      <h1>Standards library</h1>
      <FinishedReviewNotice onOpenRun={onOpenRun} />
    </div>
  );
}

beforeEach(() => {
  sessionStorage.clear();
  reloadWatchStoreForTests();
  reviewRun.mockReset();
});

afterEach(() => { vi.restoreAllMocks(); });

describe("FinishedReviewNotice", () => {
  it("shows nothing while the watched review is still running", async () => {
    reviewRun.mockResolvedValue(running);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    render(<AnotherView onOpenRun={vi.fn()} />);
    await act(async () => { await checkWatchedRuns(); });
    expect(reviewRun).toHaveBeenCalledWith("run-1");
    expect(screen.queryByText(/is ready/)).toBeNull();
  });

  it("appears on another view once the run completes, and survives a re-mount and a refresh", async () => {
    reviewRun.mockResolvedValue(running);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    const first = render(<AnotherView onOpenRun={vi.fn()} />);
    await act(async () => { await checkWatchedRuns(); });

    reviewRun.mockResolvedValue(completed);
    await act(async () => { await checkWatchedRuns(); });
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();

    first.unmount();
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(screen.getByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();

    // A refresh: the module store is rebuilt from sessionStorage.
    act(() => { reloadWatchStoreForTests(); });
    expect(screen.getByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
  });

  it("keeps watching across a refresh before the run finishes", async () => {
    watchRun("run-1", "Pump datasheet rev B.pdf");
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toContain("run-1");
    act(() => { reloadWatchStoreForTests(); });
    reviewRun.mockResolvedValue(completed);
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
  });

  it("Open it opens the run and clears the notice", async () => {
    reviewRun.mockResolvedValue(completed);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    const onOpenRun = vi.fn();
    render(<AnotherView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open it" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
    expect(screen.queryByText(/is ready/)).toBeNull();
  });

  it("Dismiss clears it, and it stays cleared after a refresh", async () => {
    reviewRun.mockResolvedValue(completed);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    const onOpenRun = vi.fn();
    render(<AnotherView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/is ready/)).toBeNull();
    act(() => { reloadWatchStoreForTests(); });
    expect(screen.queryByText(/is ready/)).toBeNull();
    expect(onOpenRun).not.toHaveBeenCalled();
  });

  it("says plainly when a watched review failed", async () => {
    reviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", status: "failed", submittal_filename: null } });
    watchRun("run-1", "Pump datasheet rev B.pdf");
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf did not finish")).toBeInTheDocument();
  });

  it("drops a cancelled run without a notice", async () => {
    reviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", status: "cancelled" } });
    watchRun("run-1", "Pump datasheet rev B.pdf");
    render(<AnotherView onOpenRun={vi.fn()} />);
    await act(async () => { await checkWatchedRuns(); });
    expect(screen.queryByTestId("finished-review-notice")).toBeNull();
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).not.toContain("run-1");
  });

  it("keeps watching when a read fails", async () => {
    reviewRun.mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "Cannot reach the backend." } });
    watchRun("run-1", "Pump datasheet rev B.pdf");
    await checkWatchedRuns();
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toContain("run-1");
  });

  it("blocked storage never breaks watching or the notice", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    reloadWatchStoreForTests();
    reviewRun.mockResolvedValue(completed);
    expect(() => watchRun("run-1", "Pump datasheet rev B.pdf")).not.toThrow();
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
  });
});
