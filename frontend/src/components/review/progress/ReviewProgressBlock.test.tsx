/** #1494: the progress block of a running review. Invented numbers only. */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewProgressDetail } from "../../../types/api";
import { ReviewProgressBlock } from "./ReviewProgressBlock";
import { shown } from "./reviewProgress";

const detail = (o: Partial<ReviewProgressDetail> = {}): ReviewProgressDetail => ({
  pages_done: 0, pages_total: 10, elapsed_seconds: 60, idle_seconds: 5,
  stall_amber_seconds: 120, stale: false, ...o,
});
const job = (d: ReviewProgressDetail | null) => ({
  id: "j", state: "running", cancel_requested: false, ...(d ? { progress_detail: d } : {}),
});

afterEach(() => vi.useRealTimers());

describe("the bar", () => {
  it("is computed from pages done over pages total, and 0% when nothing was read", () => {
    expect(shown(detail({ pages_done: 0 })).percent).toBe(0);
    expect(shown(detail({ pages_done: 3 })).percent).toBe(30);
    render(<ReviewProgressBlock job={job(detail({ pages_done: 2 }))} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    expect(screen.getByTestId("review-progress-detail").textContent).toContain("2 of 10 pages read");
  });
  it("renders nothing for pages when they are null, never 0", () => {
    render(<ReviewProgressBlock job={job(detail({ pages_done: null, pages_total: null }))} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByTestId("review-progress-detail").textContent).not.toMatch(/pages|%/);
  });
  it("renders nothing at all without progress_detail (switch off)", () => {
    const { container } = render(<ReviewProgressBlock job={job(null)} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("the time-left estimate", () => {
  it("is hidden before 3 pages are done", () => {
    expect(shown(detail({ pages_done: 2 })).estimate).toBeNull();
  });
  it("is labelled an estimate with its basis once 3 pages are done", () => {
    const e = shown(detail({ pages_done: 3, elapsed_seconds: 300 })).estimate;
    expect(e).toBe("about 11 min left (estimate, from the pages done so far)");
  });
  it("is hidden when the total is unknown or all pages are done", () => {
    expect(shown(detail({ pages_done: 5, pages_total: null })).estimate).toBeNull();
    expect(shown(detail({ pages_done: 10 })).estimate).toBeNull();
  });
});

describe("the stall light", () => {
  it("is off before the amber threshold, amber at it, red when stale", () => {
    expect(shown(detail({ idle_seconds: 119 })).stall).toBeNull();
    expect(shown(detail({ idle_seconds: 180 })).stall)
      .toEqual({ level: "amber", text: "No progress for 3 min." });
    expect(shown(detail({ idle_seconds: 1000, stale: true })).stall?.level).toBe("red");
    expect(shown(detail({ stale: true })).stall?.text).toContain("System Health");
  });
  it("uses the configured threshold, and an unknown idle time is not a stall", () => {
    expect(shown(detail({ idle_seconds: 70, stall_amber_seconds: 60 })).stall?.level).toBe("amber");
    expect(shown(detail({ idle_seconds: null })).stall).toBeNull();
  });
  it("turns amber on screen as the clock runs between polls", () => {
    vi.useFakeTimers();
    render(<ReviewProgressBlock job={job(detail({ idle_seconds: 110 }))} />);
    expect(screen.queryByTestId("review-stall")).toBeNull();
    act(() => { vi.advanceTimersByTime(11000); });
    expect(screen.getByTestId("review-stall").getAttribute("data-level")).toBe("amber");
  });
});

describe("the timer", () => {
  it("shows elapsed time from the server's figure", () => {
    expect(shown(detail({ elapsed_seconds: 3725 })).elapsed).toBe("Elapsed 1:02:05");
    expect(shown(detail({ elapsed_seconds: null })).elapsed).toBeNull();
  });
});
