/** #1494: the progress block of a running review. Invented numbers only. */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { colourClasses, definedColours } from "../../../test/themeColours";
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
    expect(e).toBe("about 11 min left reading pages (estimate, from the pages done so far)");
  });
  it("is hidden when the total is unknown or all pages are done", () => {
    expect(shown(detail({ pages_done: 5, pages_total: null })).estimate).toBeNull();
    expect(shown(detail({ pages_done: 10 })).estimate).toBeNull();
  });
});

describe("the clause step (#1494)", () => {
  const clauses = (o: Partial<ReviewProgressDetail> = {}) =>
    detail({ pages_done: null, pages_total: null, clauses_done: 11, clauses_total: 60,
      clauses_elapsed_seconds: 330, ...o });
  it("shows clauses checked over clauses total, and the bar from them", () => {
    render(<ReviewProgressBlock job={job(clauses())} />);
    expect(screen.getByTestId("review-progress-detail").textContent).toContain("11 of 60 clauses checked");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "18");
    expect(screen.getByTestId("review-progress-detail").textContent).not.toContain("pages read");
  });
  it("estimate is labelled with its basis, from the clause step's own clock", () => {
    expect(shown(clauses()).estimate)
      .toBe("about 24 min left checking clauses (estimate, from the clauses done so far)");
  });
  it("estimate is hidden before 3 clauses, without a step clock, or without a total", () => {
    expect(shown(clauses({ clauses_done: 2 })).estimate).toBeNull();
    expect(shown(clauses({ clauses_elapsed_seconds: null })).estimate).toBeNull();
    expect(shown(clauses({ clauses_total: null })).estimate).toBeNull();
    expect(shown(clauses({ clauses_done: 60 })).estimate).toBeNull();
  });
  it("renders nothing for clauses when null, never 0", () => {
    expect(shown(detail({ pages_done: null, pages_total: null })).clausesLine).toBeNull();
  });
  it("the stall light works in this step too", () => {
    expect(shown(clauses({ idle_seconds: 200 })).stall?.level).toBe("amber");
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

describe("colours (#1494, live I-06: the fill was invisible)", () => {
  it("every colour class the block draws, bar and stall lights too, is defined by the theme", () => {
    const defined = definedColours();
    const used: string[] = [];
    for (const d of [detail({ pages_done: 4, idle_seconds: 500 }), detail({ pages_done: 4, stale: true })]) {
      const { container, unmount } = render(<ReviewProgressBlock job={job(d)} />);
      container.querySelectorAll("[class]").forEach((el) => used.push(...colourClasses(` ${el.getAttribute("class")}`)));
      unmount();
    }
    expect(used.length).toBeGreaterThan(3);
    expect(used.filter((t) => !defined.has(t))).toEqual([]);
  });
  it("the fill uses the theme's accent token, redefined in light and dark", () => {
    render(<ReviewProgressBlock job={job(detail({ pages_done: 4 }))} />);
    const fill = screen.getByRole("progressbar").firstElementChild as HTMLElement;
    expect(fill.className).toContain("bg-signal-500");
  });
});

describe("Word files (live I-06: a .docx has no pages)", () => {
  it("says parts, never pages, when the server reads parts", () => {
    render(<ReviewProgressBlock job={job(detail({ pages_done: 2, pages_unit: "part" }))} />);
    const text = screen.getByTestId("review-progress-detail").textContent ?? "";
    expect(text).toContain("2 of 10 parts read");
    expect(text).not.toMatch(/page/);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-label", "2 of 10 parts read");
  });
  it("the estimate says parts too", () => {
    expect(shown(detail({ pages_done: 3, elapsed_seconds: 300, pages_unit: "part" })).estimate)
      .toBe("about 11 min left reading parts (estimate, from the parts done so far)");
  });
});

describe("the stall light names what it waits on (live I-06: one slow page)", () => {
  it("names the sub-step in the amber line", () => {
    const s = shown(detail({ idle_seconds: 600, stall_amber_seconds: 480,
      waiting_on: "reading page 3 of 5: waiting for the model" })).stall;
    expect(s).toEqual({ level: "amber",
      text: "No progress for 10 min. Still reading page 3 of 5: waiting for the model." });
  });
  it("uses the server's per-step threshold, so a slow page under it is not a stall", () => {
    expect(shown(detail({ idle_seconds: 300, stall_amber_seconds: 480 })).stall).toBeNull();
  });
});
