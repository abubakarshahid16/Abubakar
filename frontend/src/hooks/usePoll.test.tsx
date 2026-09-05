/**
 * Adaptive polling: the interval must actually follow the worker, and no
 * effect may leak a timer when React runs it twice.
 *
 * The Documents screen polled every 3 seconds whether or not anything was
 * happening - 20 requests a minute on an idle corpus, against a 15 W CPU that
 * is also answering questions.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import { FAST_MS, IDLE_MS, pollInterval, usePoll } from "./usePoll";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the interval follows the work", () => {
  it("is fast while busy and slow while idle", () => {
    expect(pollInterval(true)).toBe(FAST_MS);
    expect(pollInterval(false)).toBe(IDLE_MS);
    expect(FAST_MS).toBeLessThan(IDLE_MS);
  });

  it("polls at the idle interval when nothing is happening", () => {
    vi.useFakeTimers();
    const tick = vi.fn();
    function Probe() {
      usePoll(tick, false);
      return null;
    }
    render(<Probe />);
    expect(tick).toHaveBeenCalledTimes(1); // immediately, once

    vi.advanceTimersByTime(FAST_MS * 3);
    expect(tick).toHaveBeenCalledTimes(1); // ...and NOT at the fast interval

    vi.advanceTimersByTime(IDLE_MS);
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it("polls at the fast interval while busy", () => {
    vi.useFakeTimers();
    const tick = vi.fn();
    function Probe() {
      usePoll(tick, true);
      return null;
    }
    render(<Probe />);
    vi.advanceTimersByTime(FAST_MS * 3);
    expect(tick).toHaveBeenCalledTimes(4); // one immediate + three ticks
  });

  it("returns to the fast interval the moment work starts", () => {
    vi.useFakeTimers();
    const tick = vi.fn();
    function Probe() {
      const [busy, setBusy] = useState(false);
      usePoll(tick, busy);
      return <button onClick={() => setBusy(true)}>start</button>;
    }
    render(<Probe />);
    tick.mockClear();

    // An upload must not wait out the remaining idle interval.
    // fireEvent, not node.click(): a bare DOM click is not wrapped in act(),
    // so the state update it causes has not been applied when the assertion
    // below runs.
    fireEvent.click(screen.getByText("start"));
    expect(tick).toHaveBeenCalled();
    tick.mockClear();
    vi.advanceTimersByTime(FAST_MS);
    expect(tick).toHaveBeenCalledTimes(1);
  });

  it("does not restart the timer when the callback identity changes", () => {
    /** A new closure on every render used to tear down and rebuild the
     *  interval, which polls far more often than either constant says. */
    vi.useFakeTimers();
    const calls: number[] = [];
    function Probe({ n }: { n: number }) {
      usePoll(() => calls.push(n), false);
      return null;
    }
    const { rerender } = render(<Probe n={1} />);
    rerender(<Probe n={2} />);
    rerender(<Probe n={3} />);
    expect(calls).toEqual([1]); // one immediate call, no restarts

    vi.advanceTimersByTime(IDLE_MS);
    expect(calls).toEqual([1, 3]); // and the LATEST callback is the one used
  });
});

describe("StrictMode double-invokes every effect", () => {
  it("leaves no timer behind, so navigating between screens cannot leak", () => {
    vi.useFakeTimers();
    const setSpy = vi.spyOn(window, "setInterval");
    const clearSpy = vi.spyOn(window, "clearInterval");

    function Probe() {
      usePoll(() => {}, true);
      return null;
    }
    const { unmount } = render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
    // StrictMode runs the effect twice, so two timers are created - and both
    // must be cleared. Asserting the COUNTS rather than "at least one clear",
    // because one clear for two timers is exactly the leak.
    unmount();
    expect(clearSpy.mock.calls.length).toBe(setSpy.mock.calls.length);
    expect(setSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});

// --------------------------------------------------- the screens themselves

const health = (busy: boolean): Health => ({
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy },
});

function mockApi(status: string, busy: boolean) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(url);
      const body = url.includes("/health")
        ? health(busy)
        : url.includes("/documents")
          ? [{
              id: "doc_1", filename: "spec.pdf", sha256: "a".repeat(64),
              size_bytes: 1, page_count: 2, pages_done: 2, chunk_count: 3,
              chunk_count_total: 3, embedded_count: 3, status,
              needs_ocr_pages: 0, recognised_pages: 0, equation_pages: 0,
              error: null, uploaded_at: "2026-09-06T00:00:00Z", indexed_at: null,
            }]
          : {};
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
  return calls;
}

describe("Documents polls on what it can already see", () => {
  /** Asserting the INTERVAL REQUESTED rather than counting requests over
   *  wall-clock. The first version of these waited 3.4 real seconds and
   *  compared call counts, which is a race: it read 2 vs 2 and would have
   *  passed against a screen that never polled at all. */
  async function intervalsFor(status: string): Promise<number[]> {
    const spy = vi.spyOn(window, "setInterval");
    mockApi(status, false);
    render(<App />);
    // Wait for the LIST, not merely for a timer: the first interval is
    // registered before the documents arrive, so it is always the idle one
    // and asserting on it would measure the initial render rather than the
    // decision this hook exists to make.
    await screen.findByText("spec.pdf");
    // Every screen and the shell register timers; the poll intervals are the
    // ones this hook uses, and both constants are distinctive.
    return spy.mock.calls
      .map((c) => Number(c[1]))
      .filter((ms) => ms === FAST_MS || ms === IDLE_MS);
  }

  // The LAST interval registered is the one now running. The first is always
  // idle - it is registered before the documents arrive, when the screen
  // genuinely does not know whether anything is happening, and treating that
  // as a failure would be asserting on the initial render instead of on the
  // decision.
  const running = (chosen: number[]) => chosen[chosen.length - 1];

  it("polls fast while a document is still being worked on", async () => {
    const chosen = await intervalsFor("chunking");
    expect(running(chosen)).toBe(FAST_MS);
  });

  it("backs off once every document has settled", async () => {
    const chosen = await intervalsFor("ready");
    // The signal is the list itself: nothing unsettled, so nothing to watch.
    expect(running(chosen)).toBe(IDLE_MS);
    expect(chosen).not.toContain(FAST_MS);
  });
});
