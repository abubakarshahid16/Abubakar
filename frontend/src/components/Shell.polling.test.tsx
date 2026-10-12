/**
 * #654: the health poll is one, runs every 15 s while the tab is visible,
 * makes no call in a hidden tab, and backs off while the backend is silent.
 */
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HEALTH_MAX_BACKOFF_MS, HEALTH_POLL_MS, healthDelay, useConnection } from "./Shell";

const HEALTH = { ok: true, embed_model_present: true, answer_model_present: true,
                 ingestion: { alive: true, stalled: false, busy: false } };

let visibility: "visible" | "hidden" = "visible";
let healthCalls = 0;
let healthUp = true;
let held: (() => void) | null = null;   // when set, a /health call waits for this
let holdNext = false;

function Probe() {
  useConnection();
  return null;
}

function setVisibility(v: "visible" | "hidden") {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  healthCalls = 0;
  healthUp = true;
  held = null;
  holdNext = false;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/health")) {
      healthCalls += 1;
      if (holdNext) {
        holdNext = false;
        return new Promise<Response>((resolve) => {
          held = () => resolve(new Response(JSON.stringify(HEALTH), {
            status: 200, headers: { "Content-Type": "application/json" } }));
        });
      }
      if (!healthUp) return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve(new Response(JSON.stringify(HEALTH), {
        status: 200, headers: { "Content-Type": "application/json" } }));
    }
    return Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

describe("the health poll", () => {
  it("is every 15 seconds: a visible tab makes at most 5 calls in 60 seconds", async () => {
    render(<Probe />);
    await advance(60_000);
    expect(HEALTH_POLL_MS).toBe(15_000);
    expect(healthCalls).toBeGreaterThanOrEqual(4);
    expect(healthCalls).toBeLessThanOrEqual(5);
  });

  it("makes no call at all in a hidden tab", async () => {
    visibility = "hidden";
    render(<Probe />);
    await advance(5 * 60_000);
    expect(healthCalls).toBe(0);
  });

  it("stops polling when the tab is hidden and looks at once when it is shown again", async () => {
    render(<Probe />);
    await advance(1_000);
    expect(healthCalls).toBe(1);
    act(() => setVisibility("hidden"));
    await advance(5 * 60_000);
    expect(healthCalls).toBe(1);                      // nothing while hidden
    act(() => setVisibility("visible"));
    await advance(100);
    expect(healthCalls).toBe(2);                      // one at once, not after a wait
    await advance(15_000);
    expect(healthCalls).toBe(3);                      // then the normal pace
  });

  it("backs off while the backend does not answer and returns to the pace when it does", async () => {
    healthUp = false;
    render(<Probe />);
    await advance(5 * 60_000);
    const silent = healthCalls;
    expect(silent).toBeLessThanOrEqual(8);            // 0, 30, 90, 150, ... not 20 calls
    expect(silent).toBeGreaterThanOrEqual(4);
    healthUp = true;
    await advance(HEALTH_MAX_BACKOFF_MS);             // the next poll succeeds
    const after = healthCalls;
    await advance(60_000);
    expect(healthCalls - after).toBeGreaterThanOrEqual(4);   // back to every 15 s
    expect(healthCalls - after).toBeLessThanOrEqual(5);
  });

  it("schedules nothing when the tab was hidden while a check was still in flight", async () => {
    holdNext = true;
    render(<Probe />);
    await advance(100);
    expect(held).not.toBeNull();
    act(() => setVisibility("hidden"));
    await act(async () => { held?.(); await vi.advanceTimersByTimeAsync(10); });
    expect(vi.getTimerCount()).toBe(0);               // no timer is waiting in a hidden tab
  });

  it("the delay doubles with each failure and is capped", () => {
    expect([0, 1, 2, 3, 4, 9].map((n) => healthDelay(15_000, n))).toEqual(
      [15_000, 30_000, 60_000, 60_000, 60_000, 60_000]);
    expect(healthDelay(15_000, -3)).toBe(15_000);
  });

  it("leaves no timer or listener behind when the app is closed", async () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(<Probe />);
    await advance(1_000);
    unmount();
    expect(vi.getTimerCount()).toBe(0);               // the pending poll was cancelled
    const named = (spy: typeof add) => spy.mock.calls.filter((c) => c[0] === "visibilitychange");
    expect(named(add).length).toBeGreaterThan(0);
    expect(named(remove).length).toBe(named(add).length);
    const before = healthCalls;
    await advance(10 * 60_000);
    expect(healthCalls).toBe(before);
    act(() => setVisibility("hidden"));
    act(() => setVisibility("visible"));
    await advance(1_000);
    expect(healthCalls).toBe(before);
    expect(vi.getTimerCount()).toBe(0);
  });
});
