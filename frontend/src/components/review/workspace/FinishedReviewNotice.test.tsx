/**
 * Builder D: a watched review that finishes shows "Your review of X is
 * ready" on any view, with "Open it" and "Dismiss"; the watch list survives
 * a re-mount and a refresh (sessionStorage), and blocked storage never breaks.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reviewRun = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: { reviewRun: (...a: unknown[]) => reviewRun(...a) },
}));

import { FinishedReviewNotice } from "./FinishedReviewNotice";
import {
  WATCH_STORAGE_KEY, checkWatchedRuns, clearWatchedReviews, reloadWatchStoreForTests, setWatchOwner, watchRun, watchStorageKey,
} from "./reviewWatch";

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

    // A refresh: the module store is rebuilt from sessionStorage, and the
    // notice comes back once the server confirms the run again.
    act(() => { reloadWatchStoreForTests(); });
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
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

/** B6: the "review ready" list names files, so it belongs to whoever is
 *  signed in and is gone after sign-out.
 *  MUTATION PROOF: make clearWatchedReviews leave sessionStorage alone, or
 *  key storage without the user id, and these fail. */
describe("the watch list and sign-out", () => {
  async function finishFor(user: string | null) {
    act(() => { setWatchOwner(user); });
    reviewRun.mockResolvedValue(completed);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    await act(async () => { await checkWatchedRuns(); });
  }

  it("sign-out clears the notice, the module list and this tab's storage", async () => {
    await finishFor("user-a");
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toContain("Pump datasheet rev B.pdf");

    act(() => { clearWatchedReviews(); });
    expect(screen.queryByTestId("finished-review-notice")).toBeNull();
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toBeNull();
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toBeNull();
    // A refresh after sign-out finds nothing either.
    act(() => { reloadWatchStoreForTests(); setWatchOwner("user-a"); });
    expect(screen.queryByTestId("finished-review-notice")).toBeNull();
  });

  it("is kept per user: the next person signed in never sees the last one's file names", async () => {
    await finishFor("user-a");
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toContain("run-1");

    act(() => { setWatchOwner("user-b"); });
    expect(screen.queryByText(/Pump datasheet/)).toBeNull();
    expect(sessionStorage.getItem(watchStorageKey("user-b"))).toBeNull();
  });

  it("a notice restored from storage shows only after the server confirms the run again", async () => {
    sessionStorage.setItem(watchStorageKey("user-a"), JSON.stringify({
      watched: [], finished: [{ runId: "run-gone", filename: "Old datasheet.pdf", status: "completed" }],
    }));
    let answer: (v: unknown) => void = () => {};
    reviewRun.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    act(() => { setWatchOwner("user-a"); });
    render(<AnotherView onOpenRun={vi.fn()} />);
    // Not shown while the re-check is in flight.
    expect(screen.queryByText(/Old datasheet/)).toBeNull();
    await waitFor(() => expect(reviewRun).toHaveBeenCalledWith("run-gone"));
    // The server no longer knows it for this user: dropped, never shown.
    await act(async () => { answer({ ok: true, data: null }); });
    expect(screen.queryByText(/Old datasheet/)).toBeNull();
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).not.toContain("run-gone");
  });

  it("a restored notice the server confirms is shown", async () => {
    sessionStorage.setItem(watchStorageKey("user-a"), JSON.stringify({
      watched: [], finished: [{ runId: "run-1", filename: "Pump datasheet rev B.pdf", status: "completed" }],
    }));
    reviewRun.mockResolvedValue(completed);
    act(() => { setWatchOwner("user-a"); });
    render(<AnotherView onOpenRun={vi.fn()} />);
    expect(await screen.findByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
    expect(reviewRun).toHaveBeenCalledWith("run-1");
  });
});

/** SF1: when the app refuses to leave (unsaved decisions, the reader chose
 *  to stay), the notice stays so the review can still be opened. */
describe("Open it when the app stays", () => {
  it("keeps the notice when onOpenRun returns false", async () => {
    reviewRun.mockResolvedValue(completed);
    watchRun("run-1", "Pump datasheet rev B.pdf");
    const onOpenRun = vi.fn(() => false);
    render(<AnotherView onOpenRun={onOpenRun} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open it" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
    expect(screen.getByText("Your review of Pump datasheet rev B.pdf is ready")).toBeInTheDocument();
  });
});
